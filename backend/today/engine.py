"""Public Today isolated offline core. Importing this module performs no I/O."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
import re

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
STATES = {"unknown", "upcoming", "live", "ended"}
MAX_STREAMS = 200

def utc(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("UTC offset required")
    return dt.astimezone(timezone.utc)

def stamp(dt):
    return utc(dt).isoformat(timespec="seconds").replace("+00:00", "Z")

def normalize_video(raw, *, observed_at, approved_channels):
    """Positive YouTube videos.list metadata only; never infer state by clock."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        raise ValueError("invalid video payload")
    video_id = raw["id"]
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("invalid video id")
    snippet = raw.get("snippet") or {}
    details = raw.get("liveStreamingDetails") or {}
    publisher = snippet.get("channelId")
    if not isinstance(publisher, str) or not CHANNEL_ID.fullmatch(publisher):
        raise ValueError("invalid publisher channel")
    if publisher not in approved_channels:
        return None  # foreign owner / needs_review: do not certify
    observed = utc(observed_at)
    if observed > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("future observation")
    started, ended = utc(details.get("actualStartTime")), utc(details.get("actualEndTime"))
    scheduled = utc(details.get("scheduledStartTime"))
    broadcast = snippet.get("liveBroadcastContent")
    if ended and started and ended < started:
        raise ValueError("end before start")
    if ended is not None:
        state = "ended"
    elif started is not None and broadcast == "live":
        state = "live"
    elif broadcast == "upcoming" and scheduled is not None:
        state = "upcoming"
    else:
        state = "unknown"
    return {"video_id": video_id, "channel_id": publisher,
            "channel_name": str(snippet.get("channelTitle") or "")[:160],
            "title": str(snippet.get("title") or video_id)[:200],
            "lifecycle_state": state, "observed_at": stamp(observed),
            "scheduled_start": stamp(scheduled) if scheduled else None,
            "actual_start": stamp(started) if started else None,
            "actual_end": stamp(ended) if ended else None,
            "source_label": "YouTube videos.list"}

def apply_observation(old, incoming):
    """Latest observed wins, except immutable positive ended evidence survives contradictions."""
    if old is None:
        return incoming.copy()
    if incoming["video_id"] != old["video_id"]:
        raise ValueError("identity mismatch")
    if utc(incoming["observed_at"]) <= utc(old["observed_at"]):
        return old.copy()
    if old["lifecycle_state"] == "ended" and incoming["lifecycle_state"] != "ended":
        return {**old, "observed_at": incoming["observed_at"]}
    return incoming.copy()

def project(rows, *, now, last_success_at=None, expected_channels=66,
            scanned_channels=0, gap=True, ttl_seconds=1800):
    current = utc(now)
    last_success = utc(last_success_at)
    age = (current - last_success).total_seconds() if last_success else float("inf")
    fresh = age >= 0 and age <= ttl_seconds and not gap and scanned_channels == expected_channels
    items = []
    seen = set()
    for row in sorted(rows, key=lambda r: (r["observed_at"], r["video_id"]), reverse=True):
        ident = row["video_id"]
        if ident in seen or len(items) >= MAX_STREAMS:
            continue
        seen.add(ident)
        observed_age = (current - utc(row["observed_at"])).total_seconds()
        valid_age = 0 <= observed_age <= ttl_seconds
        item = {k: row[k] for k in ("video_id", "channel_id", "channel_name", "title",
                 "lifecycle_state", "observed_at", "source_label")}
        if not valid_age:
            item["lifecycle_state"] = "unknown"
        item["stale"] = not valid_age
        items.append(item)
    return {"schema_version": "public-today-v1", "as_of": stamp(current),
            "freshness": {"status": "fresh" if fresh else "degraded",
                          "last_success_at": stamp(last_success) if last_success else None},
            "completeness": {"status": "complete" if fresh else "unverified",
                             "expected_channels": expected_channels,
                             "scanned_channels": scanned_channels, "gap": bool(gap)},
            "streams": items}
