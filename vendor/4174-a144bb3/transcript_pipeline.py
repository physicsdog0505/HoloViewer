"""Provider-agnostic VOD transcript primitives and fallback orchestration.

This module deliberately contains no YouTube, browser-cookie, model, database, or
network integration. Providers normalize their output into ``TranscriptSegment``
so acquisition, ASR, translation, and UI code can evolve independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class TranscriptError(RuntimeError):
    """Base error for transcript pipeline failures."""


class TranscriptProviderError(TranscriptError):
    """A provider could not produce a usable transcript."""


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    source_text: str
    translated_text: str | None = None
    provider: str | None = None

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must be >= 0")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")


@dataclass(frozen=True, slots=True)
class TimelineIssue:
    kind: str
    start_ms: int
    end_ms: int
    duration_ms: int
    previous_index: int
    next_index: int


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    segments: tuple[TranscriptSegment, ...]
    provider: str
    attempts: tuple[ProviderAttempt, ...]


class TranscriptProvider(Protocol):
    name: str

    def transcribe(self, source: str) -> Sequence[TranscriptSegment]:
        """Return timestamped source-language segments for ``source``."""


def normalize_segments(
    segments: Sequence[TranscriptSegment], *, provider: str | None = None
) -> tuple[TranscriptSegment, ...]:
    """Validate and sort provider output without hiding timeline problems."""
    normalized: list[TranscriptSegment] = []
    for segment in segments:
        normalized.append(
            TranscriptSegment(
                start_ms=int(segment.start_ms),
                end_ms=int(segment.end_ms),
                source_text=segment.source_text.strip(),
                translated_text=(
                    segment.translated_text.strip()
                    if segment.translated_text is not None
                    else None
                ),
                provider=segment.provider or provider,
            )
        )
    normalized.sort(key=lambda item: (item.start_ms, item.end_ms))
    return tuple(normalized)


def inspect_timeline(
    segments: Sequence[TranscriptSegment], *, minimum_gap_ms: int = 1,
    video_duration_ms: int | None = None,
) -> tuple[TimelineIssue, ...]:
    """Report deterministic gaps and overlaps across normalized segments.

    A reported gap is only a timing diagnostic; it can represent real silence.
    ``video_duration_ms`` enables optional leading/trailing boundary diagnostics.
    """
    if minimum_gap_ms < 0:
        raise ValueError("minimum_gap_ms must be >= 0")
    if video_duration_ms is not None and video_duration_ms < 0:
        raise ValueError("video_duration_ms must be >= 0")

    ordered = normalize_segments(segments)
    issues: list[TimelineIssue] = []
    if not ordered:
        if video_duration_ms and video_duration_ms >= minimum_gap_ms:
            issues.append(
                TimelineIssue(
                    kind="gap",
                    start_ms=0,
                    end_ms=video_duration_ms,
                    duration_ms=video_duration_ms,
                    previous_index=-1,
                    next_index=0,
                )
            )
        return tuple(issues)

    if ordered[0].start_ms >= minimum_gap_ms and ordered[0].start_ms > 0:
        issues.append(
            TimelineIssue(
                kind="gap",
                start_ms=0,
                end_ms=ordered[0].start_ms,
                duration_ms=ordered[0].start_ms,
                previous_index=-1,
                next_index=0,
            )
        )

    max_end_ms = ordered[0].end_ms
    max_end_index = 0
    for index in range(1, len(ordered)):
        current = ordered[index]
        if current.start_ms < max_end_ms:
            overlap_end = min(current.end_ms, max_end_ms)
            issues.append(
                TimelineIssue(
                    kind="overlap",
                    start_ms=current.start_ms,
                    end_ms=overlap_end,
                    duration_ms=overlap_end - current.start_ms,
                    previous_index=max_end_index,
                    next_index=index,
                )
            )
        else:
            delta = current.start_ms - max_end_ms
            if delta >= minimum_gap_ms and delta > 0:
                issues.append(
                    TimelineIssue(
                        kind="gap",
                        start_ms=max_end_ms,
                        end_ms=current.start_ms,
                        duration_ms=delta,
                        previous_index=max_end_index,
                        next_index=index,
                    )
                )

        if current.end_ms > max_end_ms:
            max_end_ms = current.end_ms
            max_end_index = index

    if video_duration_ms is not None:
        if video_duration_ms < max_end_ms:
            issues.append(
                TimelineIssue(
                    kind="overlap",
                    start_ms=video_duration_ms,
                    end_ms=max_end_ms,
                    duration_ms=max_end_ms - video_duration_ms,
                    previous_index=max_end_index,
                    next_index=len(ordered),
                )
            )
        else:
            trailing = video_duration_ms - max_end_ms
            if trailing >= minimum_gap_ms and trailing > 0:
                issues.append(
                    TimelineIssue(
                        kind="gap",
                        start_ms=max_end_ms,
                        end_ms=video_duration_ms,
                        duration_ms=trailing,
                        previous_index=max_end_index,
                        next_index=len(ordered),
                    )
                )

    return tuple(issues)


def transcribe_with_fallback(
    source: str, providers: Sequence[TranscriptProvider]
) -> TranscriptResult:
    """Try providers in order and return the first non-empty valid result.

    Provider-specific failures are recorded so the caller/UI can explain which
    fallbacks were used instead of silently switching engines.
    """
    if not source.strip():
        raise ValueError("source must not be empty")
    if not providers:
        raise ValueError("at least one transcript provider is required")

    attempts: list[ProviderAttempt] = []
    for provider in providers:
        name = getattr(provider, "name", provider.__class__.__name__)
        try:
            segments = normalize_segments(provider.transcribe(source), provider=name)
            if not segments:
                raise TranscriptProviderError("provider returned no segments")
        except Exception as exc:
            attempts.append(
                ProviderAttempt(provider=name, ok=False, error=f"{type(exc).__name__}: {exc}")
            )
            continue

        attempts.append(ProviderAttempt(provider=name, ok=True))
        return TranscriptResult(
            segments=segments,
            provider=name,
            attempts=tuple(attempts),
        )

    summary = "; ".join(
        f"{attempt.provider}: {attempt.error}" for attempt in attempts
    )
    raise TranscriptProviderError(f"all transcript providers failed: {summary}")
