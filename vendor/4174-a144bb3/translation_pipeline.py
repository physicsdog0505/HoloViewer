"""Provider-neutral translation contracts for normalized transcript chunks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from transcript_pipeline import TranscriptSegment


class TranslationError(RuntimeError):
    """Base error for translation failures."""


class TranslationProviderError(TranslationError):
    """A provider could not translate a batch safely."""


@dataclass(frozen=True, slots=True)
class TranslationAttempt:
    provider: str
    ok: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TranslationBatch:
    start_index: int
    end_index: int
    source_texts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranslationResult:
    segments: tuple[TranscriptSegment, ...]
    provider: str
    attempts: tuple[TranslationAttempt, ...]


class TranslationProvider(Protocol):
    name: str

    def translate(self, texts: Sequence[str], *, target_language: str) -> Sequence[str]:
        """Translate ``texts`` in-order and return exactly one item per input."""


def build_translation_batches(
    segments: Sequence[TranscriptSegment],
    *,
    max_segments: int = 20,
    max_chars: int = 2_000,
) -> tuple[TranslationBatch, ...]:
    if max_segments <= 0:
        raise ValueError("max_segments must be > 0")
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    batches: list[TranslationBatch] = []
    start = 0
    current: list[str] = []
    current_chars = 0

    def flush(end_index: int) -> None:
        nonlocal start, current, current_chars
        if current:
            batches.append(
                TranslationBatch(
                    start_index=start,
                    end_index=end_index,
                    source_texts=tuple(current),
                )
            )
        current = []
        current_chars = 0

    for index, segment in enumerate(segments):
        text = segment.source_text
        if not text.strip():
            raise ValueError("segment source_text must not be empty")
        if len(text) > max_chars:
            flush(index)
            batches.append(
                TranslationBatch(index, index + 1, (text,))
            )
            start = index + 1
            continue

        would_exceed_count = len(current) >= max_segments
        would_exceed_chars = current and current_chars + len(text) > max_chars
        if would_exceed_count or would_exceed_chars:
            flush(index)
            start = index

        if not current:
            start = index
        current.append(text)
        current_chars += len(text)

    flush(len(segments))
    return tuple(batches)


def translate_segments(
    segments: Sequence[TranscriptSegment],
    provider: TranslationProvider,
    *,
    target_language: str = "zh-TW",
    max_segments: int = 20,
    max_chars: int = 2_000,
) -> TranslationResult:
    if not target_language.strip():
        raise ValueError("target_language must not be empty")

    name = getattr(provider, "name", provider.__class__.__name__)
    batches = build_translation_batches(
        segments,
        max_segments=max_segments,
        max_chars=max_chars,
    )
    translated: list[TranscriptSegment] = []
    attempts: list[TranslationAttempt] = []

    for batch in batches:
        try:
            response = tuple(
                str(item).strip()
                for item in provider.translate(
                    batch.source_texts,
                    target_language=target_language,
                )
            )
            if len(response) != len(batch.source_texts):
                raise TranslationProviderError(
                    "provider returned mismatched translation count: "
                    f"expected {len(batch.source_texts)}, got {len(response)}"
                )
            if any(not item for item in response):
                raise TranslationProviderError("provider returned an empty translation")
        except Exception as exc:
            attempts.append(
                TranslationAttempt(
                    provider=name,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise TranslationProviderError(
                f"translation batch {batch.start_index}:{batch.end_index} failed: {exc}"
            ) from exc

        attempts.append(TranslationAttempt(provider=name, ok=True))
        for offset, text in enumerate(response):
            source = segments[batch.start_index + offset]
            translated.append(
                TranscriptSegment(
                    start_ms=source.start_ms,
                    end_ms=source.end_ms,
                    source_text=source.source_text,
                    translated_text=text,
                    provider=source.provider,
                )
            )

    return TranslationResult(
        segments=tuple(translated),
        provider=name,
        attempts=tuple(attempts),
    )
