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


def _home_row(row: dict, home_stream_cls: Callable, *, feed_freshness: str = "unknown"):
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
    state = lifecycle
    # A positive LIVE assertion requires fresh feed evidence, not simply
    # an old persisted lifecycle label from the canonical store.
    if state == "live" and feed_freshness != "fresh":
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
        start_label=start.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Taipei")).strftime("%m/%d %H:%M") if start else "",
        state=state,
        source_label=str(row.get("source_label") or ""),
        channel_id=str(row.get("channel_id") or ""),
        avatar_url=str(row.get("avatar_url") or ""),
        group=group,
        start_at=start,
    )


def home_groups_from_payload(payload: dict, home_stream_cls: Callable):
    """Adapt one already-fetched Today envelope without any extra I/O."""
    rows = payload.get("streams", payload.get("items"))
    if not isinstance(rows, list):
        raise PublicAPIUnavailable("Today rows missing")
    groups = {"live": [], "upcoming": [], "ended": [], "unknown": []}
    freshness_envelope = payload.get("freshness")
    freshness = (
        freshness_envelope.get("status")
        if isinstance(freshness_envelope, dict) else None
    )
    if freshness not in {"fresh", "stale", "unknown"}:
        freshness = "unknown"
    for raw in rows:
        item = _home_row(raw, home_stream_cls, feed_freshness=freshness)
        if item is None:
            continue
        bucket = ("upcoming" if item.state == "waiting" else
                  "unknown" if item.state == "stale" else
                  item.state if item.state in groups else "unknown")
        groups[bucket].append(item)
    return tuple(groups[key] for key in ("live", "upcoming", "ended", "unknown"))


def bind_home_reader(api: PublicAPI, home_stream_cls: Callable):
    """Return the accepted 4174 four-list shape using only Public API evidence."""
    def read_home(*, now=None, runtime_root=None):
        return home_groups_from_payload(api.read_today(), home_stream_cls)
    return read_home

def bind_history_reader(api: PublicAPI, home_stream_cls: Callable):
    """Map legacy-compatible History pages into accepted 4174 cards."""
    def read_history_day(selected, *, page=1, source=None):
        # Explicit fixture/source overrides stay outside the production adapter.
        if source is not None:
            raise ValueError("Cannot combine local source override with Public API")
        if not 1 <= page <= 10000:
            raise ValueError("history page outside accepted bounded range")
        result = api.read_day(selected, limit=50, offset=(page - 1) * 50)
        items = result.get("items")
        if not isinstance(items, list):
            raise PublicAPIUnavailable("History list missing")
        cards = []
        for raw in items:
            item = _home_row(raw, home_stream_cls)
            if item is not None:
                # History is a dated archive listing, not authoritative evidence
                # that the stream has transitioned to ENDED.
                cards.append(item)
        return cards, result.get("has_more") is True
    return read_history_day
