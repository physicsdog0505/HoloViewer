"""Pure provider-neutral Today projections; network and persistence are adapter-owned."""
from datetime import datetime, timezone, timedelta
import re
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
MAX_STREAMS = 200
SKEW_SECONDS = 300

def utc(value):
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(timezone.utc)

def stamp(value):
    return utc(value).isoformat(timespec="seconds").replace("+00:00","Z")

def normalize_video(raw, *, observed_at, approved_channels, reference_now=None, roster_version="", approved_groups=None):
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not VIDEO_ID.fullmatch(raw["id"]):
        raise ValueError("invalid video id")
    sn, details = raw.get("snippet") or {}, raw.get("liveStreamingDetails") or {}
    channel = sn.get("channelId")
    if not isinstance(channel, str) or not CHANNEL_ID.fullmatch(channel):
        raise ValueError("invalid publisher")
    if channel not in approved_channels:
        return None
    observed = utc(observed_at)
    if observed > utc(reference_now or datetime.now(timezone.utc)) + timedelta(seconds=SKEW_SECONDS):
        raise ValueError("future observation")
    scheduled = utc(details.get("scheduledStartTime"))
    started = utc(details.get("actualStartTime"))
    ended = utc(details.get("actualEndTime"))
    if any(t > observed + timedelta(seconds=SKEW_SECONDS) for t in (started, ended) if t):
        raise ValueError("provider actual timestamp after observation")
    if ended and started and ended < started:
        raise ValueError("end before start")
    broadcast = sn.get("liveBroadcastContent")
    state = ("ended" if ended else "live" if started and broadcast == "live"
             else "upcoming" if scheduled and broadcast == "upcoming" else "unknown")
    return {"video_id":raw["id"],"channel_id":channel,
            "channel_name":str(sn.get("channelTitle") or "")[:160],
            "title":str(sn.get("title") or raw["id"])[:200],
            "group":(approved_groups or {}).get(channel,"other"), "lifecycle_state":state,
            "observed_at":stamp(observed),
            "scheduled_start":stamp(scheduled) if scheduled else None,
            "actual_start":stamp(started) if started else None,
            "actual_end":stamp(ended) if ended else None,
            "roster_version":roster_version,
            "source_label":"YouTube", "avatar_url":None,"member_accent":None}

def apply_observation(old, incoming):
    if old is None:
        return dict(incoming)
    if old["video_id"] != incoming["video_id"]:
        raise ValueError("video identity mismatch")
    if old.get("roster_version") and incoming.get("roster_version") and old["roster_version"] != incoming["roster_version"]:
        raise ValueError("roster version mismatch")
    if utc(incoming["observed_at"]) == utc(old["observed_at"]):
        if incoming != old:
            raise ValueError("conflicting equal-timestamp observation")
        return dict(old)
    if utc(incoming["observed_at"]) < utc(old["observed_at"]):
        return dict(old)
    if old["lifecycle_state"] == "ended" and incoming["lifecycle_state"] != "ended":
        return dict(old)  # never refresh ended evidence with contradictory probes
    return dict(incoming)

def project(rows, *, now, last_success_at=None, expected_channels=66, scanned_channels=0,
            gap=True, ttl_seconds=1800, completeness_evidence=None, checkpoint=None,
            roster_version=None, limit=200):
    if not 1 <= limit <= MAX_STREAMS:
        raise ValueError("invalid Today limit")
    current, last_success = utc(now), utc(last_success_at)
    if last_success is None:
        fresh_status = "unknown"
    elif 0 <= (current-last_success).total_seconds() <= ttl_seconds:
        fresh_status = "fresh"
    else:
        fresh_status = "stale"
    # No external provider mapping can self-certify completeness.
    accepted_complete = False
    complete_status = ("complete" if accepted_complete else
                       "partial" if scanned_channels > 0 or gap else "unverified")
    selected = {}
    for row in rows:
        ident = row["video_id"]
        if not VIDEO_ID.fullmatch(ident):
            continue
        if roster_version is not None and row.get("roster_version") != roster_version:
            continue
        selected[ident] = apply_observation(selected.get(ident),row)
    ordered = sorted(selected.values(),key=lambda r:(r["observed_at"],r["video_id"]),reverse=True)
    items = []
    for row in ordered[:limit]:
        observed = utc(row["observed_at"])
        item_fresh = 0 <= (current-observed).total_seconds() <= ttl_seconds
        item = {k:row.get(k) for k in ("video_id","title","channel_id","channel_name","group",
            "observed_at","source_label","avatar_url","member_accent")}
        if row["lifecycle_state"] == "ended" and row.get("actual_end"):
            item["lifecycle_state"] = "ended"
        elif not item_fresh:
            item["lifecycle_state"] = "stale"
        elif row["lifecycle_state"] == "upcoming" and row.get("scheduled_start") and utc(row["scheduled_start"]) <= current:
            item["lifecycle_state"] = "waiting"
        else:
            item["lifecycle_state"] = row["lifecycle_state"]
        item["start_at"] = row.get("actual_start") or row.get("scheduled_start")
        item["stale"] = not item_fresh and item["lifecycle_state"] != "ended"
        items.append(item)
    return {"schema_version":"public-consumer-v1","as_of":stamp(current),
        "freshness":{"status":fresh_status,
                     "last_success_at":stamp(last_success) if last_success else None},
        "completeness":{"status":complete_status,"gap":bool(gap)},
        "checkpoint":checkpoint if isinstance(checkpoint,str) and re.fullmatch(r"cp_[A-Za-z0-9_-]{8,128}",checkpoint) else None, "streams":items}
