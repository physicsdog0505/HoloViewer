"""Read-only ARK multi-POV candidate discovery for the 4174 prototype.

Candidate grouping is NOT proof of an actual collab. The viewer must not
activate event-clock offset synchronization based on these groups alone.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Protocol
from zoneinfo import ZoneInfo
import re


class StreamLike(Protocol):
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    source_label: str
    start_at: datetime | None
    start_label: str
    state: str


@dataclass(frozen=True)
class CollabCandidate:
    label: str
    video_ids: tuple[str, ...]
    confidence: str = "candidate"
    event_key: str = "ark"
    event_id: str = ""


_ARK = re.compile(r"(?<![a-z])ARK(?![a-z])|ホロARK|ロゼキャンARK|ホロ鯖ARK", re.I)
_EVENT = re.compile(r"#?ホロARK|ホロ鯖ARK|ロゼキャンARK", re.I)
_TAIPEI = ZoneInfo("Asia/Taipei")
_START_LABEL = re.compile(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})\s+(?P<hour>\d{1,2}):(?P<minute>\d{2})")
_EVENT_ROLLOVER = timedelta(hours=6)


def _event_day(value: datetime):
    """Canonical event day with a 06:00 Taipei rollover for late-night POVs."""
    local = value if value.tzinfo is None else value.astimezone(_TAIPEI)
    return (local - _EVENT_ROLLOVER).date()


def _label_event_month_day(stream: StreamLike) -> tuple[int, int] | None:
    """Recover event-day evidence from the already-rendered MM/DD HH:MM fallback.

    This is presentation/discovery evidence only. It never becomes a verified
    YouTube actual_start and is used solely to keep explicit collab POVs grouped
    when lifecycle metadata has not hydrated their start_at yet.
    """
    match = _START_LABEL.search(str(getattr(stream, "start_label", "") or ""))
    if match is None:
        return None
    try:
        value = datetime(
            2000,
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
        ) - _EVENT_ROLLOVER
    except ValueError:
        return None
    return value.month, value.day


def resolve_collab_candidate(
    candidates: Iterable[CollabCandidate],
    requested_video_ids: Iterable[str],
) -> CollabCandidate | None:
    """Resolve only an unambiguous candidate containing every requested POV."""
    requested = {video_id for video_id in requested_video_ids if video_id}
    if not requested:
        return None
    matches = [
        candidate for candidate in candidates
        if requested.issubset(set(candidate.video_ids))
    ]
    return matches[0] if len(matches) == 1 else None


def detect_ark_candidates(
    streams: Iterable[StreamLike],
) -> tuple[CollabCandidate, ...]:
    """Cluster explicit Hololive ARK POV candidates by calendar-day event.

    This is deliberately conservative: generic ARK titles alone do not prove
    shared server/event identity. It never performs timeline alignment.
    """
    eligible = [
        stream for stream in streams
        if _ARK.search(f"{stream.title} {getattr(stream, 'source_label', '')}")
        and _EVENT.search(f"{stream.title} {getattr(stream, 'source_label', '')}")
        and stream.state in {"live", "ended", "upcoming"}
        and (
            stream.start_at is not None
            or _label_event_month_day(stream) is not None
        )
    ]
    eligible.sort(
        key=lambda stream: (
            stream.start_at is None,
            stream.start_at or datetime.max,
            stream.video_id,
        )
    )

    # Hololive ARK sessions routinely continue past midnight. Treat 00:00–05:59
    # as the previous event day, and let an MM/DD HH:MM fallback attach an
    # explicit POV to a unique known date when verified start_at is still absent.
    clusters_by_day: dict[object, list[StreamLike]] = {}
    unresolved: list[StreamLike] = []
    for stream in eligible:
        if stream.start_at is not None:
            clusters_by_day.setdefault(_event_day(stream.start_at), []).append(stream)
        else:
            unresolved.append(stream)

    for stream in unresolved:
        month_day = _label_event_month_day(stream)
        matches = [
            day for day in clusters_by_day
            if (day.month, day.day) == month_day
        ]
        if len(matches) == 1:
            clusters_by_day[matches[0]].append(stream)
        elif month_day is not None:
            clusters_by_day.setdefault(("fallback", *month_day), []).append(stream)

    clusters = list(clusters_by_day.values())
    candidates = []
    for cluster in clusters:
        by_channel: dict[str, StreamLike] = {}
        for stream in cluster:
            channel = stream.channel_id or stream.channel_title
            if channel:
                by_channel.setdefault(channel, stream)
        if len(by_channel) > 1:
            known_start = next(
                (stream.start_at for stream in cluster if stream.start_at is not None),
                None,
            )
            if known_start is not None:
                event_day = _event_day(known_start).isoformat()
            else:
                month_day = _label_event_month_day(cluster[0])
                event_day = (
                    f"{month_day[0]:02d}-{month_day[1]:02d}"
                    if month_day is not None
                    else "unknown"
                )
            candidates.append(CollabCandidate(
                label="ホロARK · 多人連動候選",
                video_ids=tuple(stream.video_id for stream in by_channel.values()),
                event_id=f"ark:{event_day}",
            ))
    return tuple(candidates)


_STOPWORDS = {
    "hololive", "ホロライブ", "live", "配信", "初見", "雑談", "vtuber",
    "ホロドリ", "holodream", "コラボ", "collab",
}


def _title_tokens(stream: StreamLike) -> set[str]:
    text = f"{stream.title} {getattr(stream, 'source_label', '')}".lower()
    tokens = set(re.findall(r"[a-z0-9]{4,}|[ァ-ヶー]{4,}|[一-龠]{3,}", text))
    return {token for token in tokens if token not in _STOPWORDS}


def detect_collab_candidates(streams: Iterable[StreamLike]) -> tuple[CollabCandidate, ...]:
    """Return explicit event groups plus conservative same-time shared-topic groups."""
    rows = tuple(streams)
    explicit = list(detect_ark_candidates(rows))
    claimed = {video_id for candidate in explicit for video_id in candidate.video_ids}
    remaining = [
        stream for stream in rows
        if stream.video_id not in claimed
        and stream.start_at is not None
        and stream.state in {"live", "ended", "upcoming"}
    ]
    pairs: list[set[str]] = []
    for index, left in enumerate(remaining):
        left_channel = left.channel_id or left.channel_title
        if not left_channel:
            continue
        for right in remaining[index + 1:]:
            right_channel = right.channel_id or right.channel_title
            if not right_channel or right_channel == left_channel:
                continue
            if abs(right.start_at - left.start_at) > timedelta(minutes=20):
                continue
            shared = _title_tokens(left) & _title_tokens(right)
            if shared:
                pairs.append({left.video_id, right.video_id})
    groups: list[set[str]] = []
    for pair in pairs:
        overlaps = [group for group in groups if group & pair]
        if overlaps:
            merged = set(pair)
            for group in overlaps:
                merged |= group
                groups.remove(group)
            groups.append(merged)
        else:
            groups.append(set(pair))
    for group in groups:
        ordered = tuple(stream.video_id for stream in remaining if stream.video_id in group)
        if len(ordered) > 1:
            explicit.append(CollabCandidate(
                label="多人連動",
                video_ids=ordered,
                confidence="shared-topic",
                event_key="shared-topic",
                event_id="shared-topic:" + min(ordered),
            ))
    return tuple(explicit)
