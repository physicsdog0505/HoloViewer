"""Manual transcript ingestion and lightweight watch-along cue inference.

This module intentionally avoids network/ASR work. It accepts user-pasted,
timestamped transcript text and turns it into existing ``TranscriptSegment``
objects so the established normalization / translation pipeline can be reused.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from transcript_pipeline import TranscriptSegment


_TIMESTAMP_RE = re.compile(
    r"^\s*(?:\[)?(?P<time>(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)(?:\])?"
    r"(?:\s*minutes?\s*,?\s*\d+(?:[.,]\d+)?\s*seconds?)?"
    r"\s*(?:[-–—>]\s*)?(?P<text>.*)$",
    re.I,
)
_PROSE_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<minutes>\d+)\s*minutes?\s*,?\s*(?P<seconds>\d+(?:[.,]\d+)?)\s*seconds?\s*(?P<text>.*)$",
    re.I,
)
_COUNTDOWN_PATTERNS = (
    re.compile(r"(?:^|\D)3\s*[、,，]?\s*2\s*[、,，]?\s*1(?:\D|$)", re.I),
    re.compile(r"(?:^|\D)３\s*[、,，]?\s*２\s*[、,，]?\s*１(?:\D|$)"),
    re.compile(r"(?:^|\D)321(?:\D|$)", re.I),
    re.compile(r"(?:^|\D)３２１(?:\D|$)"),
)
_EXPLICIT_START_PATTERN = re.compile(r"せーの|せえの|スタート|再生(?:します|する|して)?", re.I)
_PLAYBACK_START_PATTERN = re.compile(r"スタート|再生(?:します|する|して)?", re.I)
_COUNTDOWN_CONFIRMATION_PATTERN = re.compile(r"^はい[!！。.]?$", re.I)
_GENERIC_START_PATTERN = re.compile(r"いくよ|いきます|行きます", re.I)
_PAUSE_PATTERNS = (
    re.compile(r"一時停止|止めます|止める|休憩|ちょっと休|いったん休|一旦休", re.I),
)
_RESUME_PATTERNS = (
    re.compile(r"続き(?:から)?|再開|再生再開|戻ります|戻ろう|再び再生", re.I),
)
_NEXT_PATTERNS = (
    re.compile(r"次(?:の)?(?:話|回|エピソード)|第\s*\d+\s*話|next\s*episode", re.I),
)


@dataclass(frozen=True, slots=True)
class ParsedManualTranscript:
    segments: tuple[TranscriptSegment, ...]
    ignored_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WatchalongCue:
    kind: str
    start_ms: int
    text: str
    confidence: str
    reason: str


def _timestamp_to_ms(raw: str) -> int:
    text = raw.replace(",", ".")
    parts = text.split(":")
    if len(parts) == 2:
        hours = 0
        minutes_text, seconds_text = parts
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes_text, seconds_text = parts[1], parts[2]
    else:
        raise ValueError(f"invalid timestamp: {raw}")

    minutes = int(minutes_text)
    seconds = float(seconds_text)
    if minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60:
        raise ValueError(f"invalid timestamp: {raw}")
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


def _prose_timestamp_to_ms(minutes_text: str, seconds_text: str) -> int:
    minutes = int(minutes_text)
    seconds = float(seconds_text.replace(",", "."))
    if minutes < 0 or seconds < 0 or seconds >= 60:
        raise ValueError("invalid prose timestamp")
    return int(round((minutes * 60 + seconds) * 1000))


def parse_manual_transcript(
    text: str,
    *,
    default_segment_ms: int = 2_000,
    provider: str = "manual-paste",
) -> ParsedManualTranscript:
    """Parse common timestamped transcript lines."""
    if default_segment_ms <= 0:
        raise ValueError("default_segment_ms must be > 0")

    pending_start: int | None = None
    pending_text: list[str] = []
    raw_items: list[tuple[int, str]] = []
    ignored: list[str] = []

    def flush() -> None:
        nonlocal pending_start, pending_text
        if pending_start is not None and pending_text:
            joined = " ".join(part.strip() for part in pending_text if part.strip()).strip()
            if joined:
                raw_items.append((pending_start, joined))
        pending_start = None
        pending_text = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        prose_match = _PROSE_TIMESTAMP_RE.match(line)
        match = _TIMESTAMP_RE.match(line) if prose_match is None else None
        if match or prose_match:
            flush()
            try:
                if prose_match is not None:
                    pending_start = _prose_timestamp_to_ms(
                        prose_match.group("minutes"), prose_match.group("seconds")
                    )
                    remainder = prose_match.group("text").strip()
                else:
                    pending_start = _timestamp_to_ms(match.group("time"))
                    remainder = match.group("text").strip()
            except ValueError:
                ignored.append(raw_line)
                pending_start = None
                continue
            if remainder:
                pending_text.append(remainder)
            continue

        if pending_start is None:
            ignored.append(raw_line)
        else:
            pending_text.append(line)

    flush()
    raw_items.sort(key=lambda item: item[0])

    segments: list[TranscriptSegment] = []
    for index, (start_ms, source_text) in enumerate(raw_items):
        next_start = raw_items[index + 1][0] if index + 1 < len(raw_items) else None
        if next_start is not None and next_start > start_ms:
            end_ms = next_start
        else:
            end_ms = start_ms + default_segment_ms
        segments.append(
            TranscriptSegment(
                start_ms=start_ms,
                end_ms=end_ms,
                source_text=source_text,
                provider=provider,
            )
        )

    return ParsedManualTranscript(tuple(segments), tuple(ignored))


def _matches_any(text: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def _first_match(text: str, patterns: Sequence[re.Pattern[str]]) -> re.Match[str] | None:
    matches = [match for pattern in patterns if (match := pattern.search(text)) is not None]
    if not matches:
        return None
    return min(matches, key=lambda match: match.start())


def _cue_time_inside_segment(segment: TranscriptSegment, text: str, match: re.Match[str] | None) -> int:
    """Estimate an in-segment cue time when a dense transcript line contains earlier speech.

    Manual/YouTube transcript exports timestamp the whole line at its first word. If a
    countdown appears near the end of a short, densely-timestamped segment, using the
    segment start makes Watchalong begin several seconds early. Interpolate only when
    the span is long enough to plausibly come from a real next timestamp; very short
    synthetic/default spans and sparse rows keep the conservative segment-start fallback.
    """
    if match is None or not text:
        return segment.start_ms
    duration_ms = max(0, int(segment.end_ms) - int(segment.start_ms))
    if duration_ms < 3_000 or duration_ms > 15_000:
        return segment.start_ms
    match_start = max(0, match.start())
    if match_start <= 0:
        return segment.start_ms
    ratio = min(1.0, match_start / max(1, len(text)))
    return int(round(segment.start_ms + duration_ms * ratio))


def _start_cue_priority(cue: WatchalongCue) -> int:
    if cue.kind != "start":
        return -1
    if cue.reason in {"countdown + start wording", "explicit start after countdown"}:
        return 4
    if cue.reason.startswith("countdown"):
        return 3
    if cue.reason == "explicit start wording":
        return 2
    if cue.reason == "generic start wording":
        return 1
    return 0


def select_episode_start_cues(
    cues: Sequence[WatchalongCue],
    *,
    proximity_ms: int = 20_000,
) -> tuple[WatchalongCue, ...]:
    """Collapse nearby starts, preferring the actual start after a countdown."""
    if proximity_ms <= 0:
        raise ValueError("proximity_ms must be > 0")
    starts = sorted((cue for cue in cues if cue.kind == "start"), key=lambda cue: cue.start_ms)
    if not starts:
        return ()

    selected: list[WatchalongCue] = []
    cluster: list[WatchalongCue] = [starts[0]]
    cluster_start = starts[0].start_ms

    def flush_cluster() -> None:
        best = max(cluster, key=lambda cue: (_start_cue_priority(cue), cue.start_ms))
        selected.append(best)

    for cue in starts[1:]:
        if cue.start_ms - cluster_start < proximity_ms:
            cluster.append(cue)
            continue
        flush_cluster()
        cluster = [cue]
        cluster_start = cue.start_ms
    flush_cluster()
    return tuple(selected)



def confirmed_episode_start_cues(cues: Sequence[WatchalongCue]) -> tuple[WatchalongCue, ...]:
    """Only confirmed countdown playback may trigger automatic VOD episode changes.

    Weaker starts remain visible as diagnostics, never as episode boundaries.
    """
    confirmed = [
        cue for cue in cues
        if cue.kind == "start" and cue.confidence == "high"
        and cue.reason in {"countdown + start wording", "explicit start after countdown"}
    ]
    return select_episode_start_cues(confirmed)


def infer_watchalong_cues(segments: Sequence[TranscriptSegment]) -> tuple[WatchalongCue, ...]:
    """Infer conservative start/pause/resume/next-episode candidates.

    Nearby start phrases are collapsed here so archive alignment never sees an
    early ``いきます`` as a separate episode start when a real 3-2-1 countdown
    follows a few seconds later.
    """
    cues: list[WatchalongCue] = []
    previous_countdown_ms: int | None = None
    for segment in segments:
        text = segment.source_text.strip()
        compact = re.sub(r"\s+", "", text)

        countdown_match = _first_match(text, _COUNTDOWN_PATTERNS)
        countdown = countdown_match is not None
        countdown_ms = _cue_time_inside_segment(segment, text, countdown_match)
        explicit_start_match = _EXPLICIT_START_PATTERN.search(text)
        explicit_start = explicit_start_match is not None
        playback_start_match = _PLAYBACK_START_PATTERN.search(text)
        next_episode = _matches_any(compact, _NEXT_PATTERNS)
        generic_start = bool(_GENERIC_START_PATTERN.search(text)) and not next_episode
        if countdown and explicit_start:
            # ``せーの`` is an explicit lead-in, not the instant playback starts.
            # When the same caption also names the actual playback action, retain
            # PR #160's bounded interpolation but anchor it to that later wording.
            cue_match = playback_start_match or countdown_match
            cue_ms = _cue_time_inside_segment(segment, text, cue_match)
            cues.append(WatchalongCue("start", cue_ms, text, "high", "countdown + start wording"))
        elif countdown:
            cues.append(WatchalongCue("start", countdown_ms, text, "medium", "countdown candidate"))
        elif explicit_start:
            follows_countdown = (
                previous_countdown_ms is not None
                and 0 <= segment.start_ms - previous_countdown_ms <= 8_000
            )
            cues.append(
                WatchalongCue(
                    "start",
                    segment.start_ms,
                    text,
                    "high" if follows_countdown else "medium",
                    "explicit start after countdown" if follows_countdown else "explicit start wording",
                )
            )
        elif (
            previous_countdown_ms is not None
            and 0 <= segment.start_ms - previous_countdown_ms <= 8_000
            and _COUNTDOWN_CONFIRMATION_PATTERN.fullmatch(compact)
        ):
            # YouTube automatic captions commonly split ``…321`` and the spoken
            # playback confirmation ``はい。`` into adjacent segments. Treat only
            # this tightly bounded standalone form as the actual start; ordinary
            # conversational ``はい`` remains untouched.
            cues.append(
                WatchalongCue(
                    "start",
                    segment.start_ms,
                    text,
                    "high",
                    "explicit start after countdown",
                )
            )
        elif generic_start:
            cues.append(WatchalongCue("start", segment.start_ms, text, "low", "generic start wording"))

        previous_countdown_ms = countdown_ms if countdown else None

        if _matches_any(compact, _PAUSE_PATTERNS):
            cues.append(WatchalongCue("pause", segment.start_ms, text, "high", "explicit pause/rest wording"))
        if _matches_any(compact, _RESUME_PATTERNS):
            cues.append(WatchalongCue("resume", segment.start_ms, text, "high", "explicit resume wording"))
        if next_episode:
            cues.append(WatchalongCue("next_episode", segment.start_ms, text, "medium", "next-episode wording"))

    selected_starts = select_episode_start_cues(cues)
    non_starts = [cue for cue in cues if cue.kind != "start"]
    collapsed = [*non_starts, *selected_starts]
    collapsed.sort(key=lambda cue: (cue.start_ms, cue.kind))
    return tuple(collapsed)


def pair_pause_resume_windows(cues: Sequence[WatchalongCue]) -> tuple[tuple[int, int], ...]:
    """Pair explicit pause/resume cues into conservative archive pause windows."""
    windows: list[tuple[int, int]] = []
    pending_pause: int | None = None
    for cue in sorted(cues, key=lambda item: (item.start_ms, item.kind)):
        if cue.kind == "pause":
            if pending_pause is None:
                pending_pause = cue.start_ms
            continue
        if cue.kind == "resume" and pending_pause is not None:
            if cue.start_ms > pending_pause:
                windows.append((pending_pause, cue.start_ms))
            pending_pause = None
    return tuple(windows)


def format_timestamp_ms(value: int) -> str:
    seconds = max(0, int(value // 1000))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
