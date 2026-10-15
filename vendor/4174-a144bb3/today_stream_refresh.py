"""Bounded background refresh policy for the canonical 今日直播 snapshot.

This module never logs into PTT and never renders UI. It only consumes existing
rebuildable discovery sidecars/cache plus batched YouTube lifecycle metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Callable, Iterable, Mapping

from channel_push_discovery import (
    ChannelPushStore,
    cards_for_day,
    merge_cards,
    statuses_for_day,
)
from frontend_stream_discovery import DiscoveryCard, build_discovery_cards
from frontend_time import TAIPEI
from live_stream_discovery import LiveDiscoveryCache
from today_stream_status import (
    fetch_video_statuses,
    load_status_snapshot,
    save_status_snapshot,
    stream_state,
)
from youtube_metadata import YoutubeVideo
from stream_catalog_runtime import StreamCatalogRuntimeWriter


LIVE_INTERVAL = timedelta(minutes=1)
NEAR_START_INTERVAL = timedelta(minutes=1)
MID_UPCOMING_INTERVAL = timedelta(minutes=5)
LATE_UPCOMING_INTERVAL = timedelta(minutes=15)
UNKNOWN_INTERVAL = timedelta(minutes=5)
TODAY_ROLLOVER_HOUR = 6


def _source_days(now: datetime) -> tuple[date, ...]:
    local = now.astimezone(TAIPEI)
    today = local.date()
    if local.hour < TODAY_ROLLOVER_HOUR:
        return (today - timedelta(days=1), today)
    return (today,)


def _snapshot_day(now: datetime) -> date:
    local = now.astimezone(TAIPEI)
    return (
        local.date() - timedelta(days=1)
        if local.hour < TODAY_ROLLOVER_HOUR
        else local.date()
    )


StatusVerifier = Callable[[Iterable[str]], Mapping[str, YoutubeVideo]]


@dataclass(frozen=True, slots=True)
class CatalogCadenceHint:
    lifecycle_state: str
    last_checked_at: datetime | None
    scheduled_start: datetime | None


def _hint_refresh_interval(
    hint: CatalogCadenceHint,
    *,
    now: datetime,
) -> timedelta | None:
    state = hint.lifecycle_state
    if state == "live":
        return LIVE_INTERVAL
    if state == "upcoming":
        if hint.scheduled_start is None:
            return UNKNOWN_INTERVAL
        remaining = hint.scheduled_start.astimezone(timezone.utc) - now.astimezone(timezone.utc)
        if remaining <= timedelta(minutes=30):
            return NEAR_START_INTERVAL
        if remaining <= timedelta(hours=3):
            return MID_UPCOMING_INTERVAL
        return LATE_UPCOMING_INTERVAL
    return UNKNOWN_INTERVAL


def refresh_interval(video: YoutubeVideo | None, *, now: datetime) -> timedelta | None:
    """Return lifecycle refresh interval, or None when no further polling is needed."""

    if video is None:
        return UNKNOWN_INTERVAL
    state = stream_state(video, now=now)
    if state in {"ended", "non_live"}:
        return None
    if state == "live":
        return LIVE_INTERVAL
    if state in {"waiting", "upcoming"}:
        if video.scheduled_start is None:
            return UNKNOWN_INTERVAL
        remaining = video.scheduled_start.astimezone(timezone.utc) - now.astimezone(timezone.utc)
        if remaining <= timedelta(minutes=30):
            return NEAR_START_INTERVAL
        if remaining <= timedelta(hours=3):
            return MID_UPCOMING_INTERVAL
        return LATE_UPCOMING_INTERVAL
    return UNKNOWN_INTERVAL


def due_video_ids(
    cards: Iterable[DiscoveryCard],
    statuses: Mapping[str, YoutubeVideo],
    attempted_at: Mapping[str, datetime],
    *,
    now: datetime,
    cadence_hints: Mapping[str, CatalogCadenceHint] | None = None,
) -> tuple[str, ...]:
    """Choose candidates whose state-dependent refresh window has elapsed."""

    due: list[str] = []
    hints = cadence_hints or {}
    for card in cards:
        video_id = card.video_id
        video = statuses.get(video_id)
        hint = hints.get(video_id)
        interval = (
            refresh_interval(video, now=now)
            if video is not None
            else (_hint_refresh_interval(hint, now=now) if hint is not None else UNKNOWN_INTERVAL)
        )
        if interval is None:
            continue
        evidence_times = [
            value
            for value in (
                attempted_at.get(video_id),
                video.checked_at if video is not None else None,
                hint.last_checked_at if video is None and hint is not None else None,
            )
            if value is not None
        ]
        last_attempt = max(
            (value.astimezone(timezone.utc) for value in evidence_times),
            default=None,
        )
        if last_attempt is None or now.astimezone(timezone.utc) - last_attempt >= interval:
            due.append(video_id)
    return tuple(dict.fromkeys(due))


def _parse_catalog_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _catalog_candidates(
    base: Path,
) -> tuple[tuple[DiscoveryCard, ...], dict[str, CatalogCadenceHint]]:
    """Return active catalog-only candidates plus read-only cadence evidence.

    Catalog lifecycle/last_checked_at may choose when to re-verify a row, but
    these hints are never inserted into the authoritative YouTube status map and
    therefore never refresh snapshot/catalog observation clocks by themselves.
    """
    path = base / "hololive_stream_catalog.sqlite3"
    if not path.is_file():
        return (), {}
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve()}?mode=ro", uri=True, timeout=2
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            rows = connection.execute(
                """
                SELECT video_id,title,lifecycle_state,scheduled_start,last_checked_at
                FROM streams
                WHERE lifecycle_state IN ('live','upcoming')
                ORDER BY video_id
                LIMIT 500
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return (), {}

    cards: list[DiscoveryCard] = []
    hints: dict[str, CatalogCadenceHint] = {}
    for row in rows:
        video_id = str(row["video_id"] or "")
        if not video_id:
            continue
        cards.append(
            DiscoveryCard(
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                label=str(row["title"] or video_id),
                period="catalog",
                source_aids=(),
            )
        )
        hints[video_id] = CatalogCadenceHint(
            lifecycle_state=str(row["lifecycle_state"] or "unknown"),
            last_checked_at=_parse_catalog_time(row["last_checked_at"]),
            scheduled_start=_parse_catalog_time(row["scheduled_start"]),
        )
    return tuple(cards), hints


def load_today_candidates(
    root: str | Path,
    *,
    now: datetime,
) -> tuple[
    tuple[DiscoveryCard, ...],
    dict[str, YoutubeVideo],
    dict[str, datetime],
    dict[str, CatalogCadenceHint],
]:
    """Load current-day candidates/statuses from local persisted evidence only."""

    base = Path(root).expanduser().resolve()
    source_days = _source_days(now)
    snapshot_day = _snapshot_day(now)
    ptt_cache = LiveDiscoveryCache(base / ".ptt_stream_discovery_cache.json")
    push_store = ChannelPushStore(base / ".channel_push_discovery.json")
    reconcile_store = ChannelPushStore(base / ".channel_feed_reconcile.json")

    cards = ()
    for source_day in source_days:
        try:
            cards = merge_cards(
                cards,
                build_discovery_cards(ptt_cache, source_day.isoformat()),
            )
        except (OSError, ValueError, TypeError, KeyError):
            continue

    statuses: dict[str, YoutubeVideo] = {}
    for store in (push_store, reconcile_store):
        for source_day in source_days:
            try:
                cards = merge_cards(cards, cards_for_day(store, source_day))
                statuses.update(statuses_for_day(store, source_day))
            except (OSError, ValueError, TypeError, KeyError):
                continue

    snapshot_statuses, attempted = load_status_snapshot(
        base / ".today_stream_status.json",
        day=snapshot_day.isoformat(),
    )
    statuses.update(snapshot_statuses)

    known = {card.video_id for card in cards}
    raw_catalog_cards, raw_hints = _catalog_candidates(base)
    catalog_cards = tuple(
        card for card in raw_catalog_cards if card.video_id not in known
    )
    cadence_hints = {
        video_id: hint
        for video_id, hint in raw_hints.items()
        if video_id not in known
    }
    cards = tuple(cards) + catalog_cards
    return tuple(cards), statuses, attempted, cadence_hints


def reconcile_due(
    store: ChannelPushStore,
    *,
    now: datetime,
    interval: timedelta,
) -> bool:
    """Return whether the low-frequency channel-feed recovery pass is due."""

    latest: datetime | None = None
    try:
        diagnostics = store.diagnostics()
    except (OSError, ValueError, TypeError, KeyError):
        return True
    for row in diagnostics:
        if not isinstance(row, dict) or row.get("kind") != "reconcile":
            continue
        raw = row.get("at")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        if latest is None or value > latest:
            latest = value
    if latest is None:
        return True
    return now.astimezone(timezone.utc) - latest >= interval


def refresh_today_snapshot(
    root: str | Path,
    *,
    now: datetime | None = None,
    verify: StatusVerifier = fetch_video_statuses,
) -> tuple[int, int]:
    """Refresh due IDs once and atomically publish the canonical day snapshot.

    Returns (candidate_count, refreshed_count). Verification failures propagate
    before any snapshot write, preserving the previous last-good file.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    base = Path(root).expanduser().resolve()
    day = _snapshot_day(current).isoformat()
    cards, statuses, attempted, cadence_hints = load_today_candidates(base, now=current)
    due = due_video_ids(
        cards,
        statuses,
        attempted,
        now=current,
        cadence_hints=cadence_hints,
    )
    if not due:
        return len(cards), 0

    fetched = dict(verify(due))
    merged = dict(statuses)
    merged.update(fetched)
    attempts = dict(attempted)
    attempt_time = current.astimezone(timezone.utc)
    for video_id in due:
        attempts[video_id] = attempt_time

    save_status_snapshot(
        base / ".today_stream_status.json",
        day=day,
        statuses=merged,
        attempted_at=attempts,
        updated_at=current,
    )
    # Keep the durable projection moving with the exact same verified metadata.
    # The writer is failure-isolated and monotonic, so a snapshot success never
    # depends on the catalog being writable.
    catalog_path = base / "hololive_stream_catalog.sqlite3"
    if catalog_path.is_file() and fetched:
        StreamCatalogRuntimeWriter(catalog_path).verified_statuses(
            fetched, received_at=current
        )
    return len(cards), len(fetched)
