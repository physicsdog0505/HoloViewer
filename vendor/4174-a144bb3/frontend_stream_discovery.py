"""Pure presentation helpers for PTT-derived stream discovery surfaces."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping

from live_stream_discovery import LiveDiscoveryCache, LiveThreadSnapshot, cached_day_streams
from youtube_metadata import YoutubeVideo


URL_LINE_RE = re.compile(r"https?://", re.IGNORECASE)
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
SHORT_TEXT_RE = re.compile(r"(?:#\s*shorts?\b|\bshorts?\b|ショート|short\s*video)", re.IGNORECASE)
HOLOSTARS_RE = re.compile(r"(?:holostars?|ホロスターズ|ホロスタ|\buproar!?\b)", re.IGNORECASE)
HOLOLIVE_RE = re.compile(r"(?:hololive|ホロライブ)", re.IGNORECASE)


@dataclass(frozen=True)
class DiscoveryCard:
    video_id: str
    url: str
    label: str
    period: str
    source_aids: tuple[str, ...]
    ptt_start_minutes: int | None = None
    ptt_start_label: str | None = None


def _nearby_lines(snapshot: LiveThreadSnapshot, first_line: int) -> tuple[str, ...]:
    """Return text attributable to this stream's body block.

    PTT stream lists commonly use `time/title/URL` blocks. Walk backward from the
    URL and stop at the previous URL so labels from one stream cannot be borrowed
    by the next adjacent stream. This evidence is also used by conservative
    Shorts/HOLOSTARS filtering, so crossing a URL boundary would be unsafe.
    """
    lines = snapshot.body_text.splitlines()
    index = max(0, first_line - 1)
    candidates: list[str] = []
    for candidate_index in range(index - 1, -1, -1):
        candidate = lines[candidate_index].strip()
        if URL_LINE_RE.search(candidate):
            break
        if not candidate:
            continue
        candidates.append(candidate)
        if len(candidates) >= 8:
            break
    return tuple(candidates)


def _nearby_label(snapshot: LiveThreadSnapshot, first_line: int) -> str:
    """Use attributable PTT body text as a deterministic label when metadata is absent."""
    candidates = _nearby_lines(snapshot, first_line)
    if candidates:
        return candidates[0]
    return f"{snapshot.period}專串直播"


def _nearby_start_time(snapshot: LiveThreadSnapshot, first_line: int) -> tuple[int | None, str | None]:
    """Conservatively associate an HH:MM token with only this stream's text block.

    Walk backward from the stream URL, inspect at most two meaningful text lines,
    and stop at another URL. This supports common `time / title / URL` layouts
    without borrowing a time from the previous stream entry.
    """
    lines = snapshot.body_text.splitlines()
    index = max(0, first_line - 1)
    meaningful = 0
    for candidate_index in range(index - 1, -1, -1):
        candidate = lines[candidate_index].strip()
        if URL_LINE_RE.search(candidate):
            break
        if not candidate:
            continue
        meaningful += 1
        match = TIME_RE.search(candidate)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            return hour * 60 + minute, f"{hour:02d}:{minute:02d}"
        if meaningful >= 2:
            break
    return None, None


def hidden_reason(
    card: DiscoveryCard,
    *,
    title: str = "",
    channel_title: str = "",
) -> str | None:
    """Return a conservative reason to hide entries the picker does not need.

    Shorts are hidden only when the original URL or visible text says so.
    HOLOSTARS is hidden when the channel metadata says so, or when PTT/title text
    is explicitly HOLOSTARS-only. Mixed Hololive/Holostars text is retained to
    avoid hiding a Hololive POV in a cross-group collab.
    """
    text = " ".join(part for part in (card.label, title) if part).strip()
    lowered_url = card.url.lower()
    if "/shorts/" in lowered_url or SHORT_TEXT_RE.search(text):
        return "short"

    if channel_title and HOLOSTARS_RE.search(channel_title):
        return "holostars"
    if HOLOSTARS_RE.search(text) and not HOLOLIVE_RE.search(text):
        return "holostars"
    return None


def filter_discovery_cards(
    cards: tuple[DiscoveryCard, ...] | list[DiscoveryCard],
    *,
    metadata: Mapping[str, YoutubeVideo] | None = None,
) -> tuple[tuple[DiscoveryCard, ...], dict[str, int]]:
    """Conservatively filter discovery cards and report deterministic counts.

    With no metadata this is source-only filtering and is safe before any YouTube
    request. When metadata is supplied, title/channel information is also applied;
    entries with missing metadata are retained rather than guessed away.
    """
    kept: list[DiscoveryCard] = []
    counts = {"shorts": 0, "holostars": 0}
    for card in cards:
        video = metadata.get(card.video_id) if metadata is not None else None
        reason = hidden_reason(
            card,
            title=video.title if video else "",
            channel_title=video.channel_title if video else "",
        )
        if reason == "short":
            counts["shorts"] += 1
            continue
        if reason == "holostars":
            counts["holostars"] += 1
            continue
        kept.append(card)
    return tuple(kept), counts


def build_discovery_cards(
    cache: LiveDiscoveryCache,
    calendar_day: str,
) -> tuple[DiscoveryCard, ...]:
    """Return deduplicated cards for one day, ordered by PTT start time when available."""
    snapshots = cache.for_day(calendar_day)
    snapshots_by_aid = {snapshot.aid: snapshot for snapshot in snapshots}
    cards: list[tuple[int, DiscoveryCard]] = []
    for source_order, (stream, aids) in enumerate(cached_day_streams(cache, calendar_day)):
        primary = snapshots_by_aid.get(aids[0]) if aids else None
        if primary is None:
            continue
        label = _nearby_label(primary, stream.first_line)
        start_minutes, start_label = _nearby_start_time(primary, stream.first_line)
        periods = []
        for aid in aids:
            snapshot = snapshots_by_aid.get(aid)
            if snapshot is not None and snapshot.period not in periods:
                periods.append(snapshot.period)
        cards.append(
            (
                source_order,
                DiscoveryCard(
                    video_id=stream.video_id,
                    url=stream.url,
                    label=label,
                    period=" / ".join(periods) or primary.period,
                    source_aids=aids,
                    ptt_start_minutes=start_minutes,
                    ptt_start_label=start_label,
                ),
            )
        )
    cards.sort(
        key=lambda pair: (
            pair[1].ptt_start_minutes is None,
            pair[1].ptt_start_minutes if pair[1].ptt_start_minutes is not None else 24 * 60,
            pair[0],
        )
    )
    return tuple(card for _order, card in cards)