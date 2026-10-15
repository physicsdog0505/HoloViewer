"""Adapt Public consumer rows to the frozen 4174 HomeStream data contract.

This deliberately does not reproduce any 4174 renderer, player or navigation
logic. The caller is responsible for exposing these read functions through the
already accepted product data-entry seams.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from platform_adapter.public_api import PublicAPI, PublicAPIUnavailable

ALLOWED_STATES = frozenset({"live", "waiting", "upcoming", "ended", "stale", "unknown"})
VISIBLE_GROUPS = frozenset({"hololive", "holostars", "mekpark"})
VIDEO_ID_LEN = 11


def _timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return instant.astimezone(timezone.utc) if instant.tzinfo else None


def _home_row(row: dict, home_stream_cls: Callable):
    if not isinstance(row, dict):
        return None
    video_id = row.get("video_id")
    if not isinstance(video_id, str) or len(video_id) != VIDEO_ID_LEN or not all(
        ch.isascii() and (ch.isalnum() or ch in "_-") for ch in video_id
    ):
        return None
    # Missing or stale lifecycle evidence stays unknown; never revive stale LIVE.
    lifecycle = str(row.get("lifecycle_state") or row.get("state") or "unknown").lower()
    if lifecycle not in ALLOWED_STATES:
        lifecycle = "unknown"
    state = "upcoming" if lifecycle == "waiting" else lifecycle
    if state == "stale":
        state = "unknown"
    group = str(row.get("group") or "").lower()
    if group not in VISIBLE_GROUPS:
        group = "unknown"  # Never classify an unverified channel as Hololive.
    start = _timestamp(
        row.get("actual_start") or row.get("scheduled_start") or row.get("start_at")
    )
    return home_stream_cls(
        video_id=video_id,
        title=str(row.get("title") or video_id),
        channel_title=str(row.get("channel_name") or row.get("channel_title") or ""),
        start_label=start.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")).strftime("%H:%M") if start else "",
        state=state,
        source_label="",
        channel_id=str(row.get("channel_id") or ""),
        avatar_url=str(row.get("avatar_url") or ""),
        group=group,
        start_at=start,
    )


def bind_home_reader(api: PublicAPI, home_stream_cls: Callable):
    """Return the accepted 4174 four-list shape using only Public API evidence."""
    def read_home(*, now=None, runtime_root=None):
        payload = api.read_today()
        rows = payload.get("streams", payload.get("items"))
        # Missing list is an error, not a silently empty 'complete' result.
        if not isinstance(rows, list):
            raise PublicAPIUnavailable("Today rows missing")
        groups = {"live": [], "upcoming": [], "ended": [], "unknown": []}
        for raw in rows:
            item = _home_row(raw, home_stream_cls)
            if item is None:
                continue
            bucket = item.state if item.state in groups else "unknown"
            groups[bucket].append(item)
        return tuple(groups[key] for key in ("live", "upcoming", "ended", "unknown"))
    return read_home
