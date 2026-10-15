"""Watchalong's user-triggered bridge to corpus translation artifacts."""
from __future__ import annotations

from dataclasses import dataclass, replace

from corpus_translation import CorpusTranslationOutcome, CorpusTranslationService
from resilient_translation import load_state, partial_segments
from transcript_corpus import TranscriptCorpus, TranscriptRecord
from transcript_pipeline import TranscriptSegment


WATCHALONG_TRANSLATION_TARGET = "zh-TW"
# Bump this whenever GeminiTranslationProvider's translation instructions change.
WATCHALONG_TRANSLATION_RULES_VERSION = "watchalong-gemini-zh-tw-prompt-v1"


@dataclass(frozen=True, slots=True)
class WatchalongTranslationView:
    segments: tuple[TranscriptSegment, ...]
    ready_batches: int
    total_batches: int
    failure: dict | None
    complete: bool
    reused: bool


def _record_segments(record: TranscriptRecord) -> tuple[TranscriptSegment, ...]:
    return tuple(
        TranscriptSegment(
            item.start_ms,
            item.end_ms,
            item.source_text,
            provider=record.source_type,
        )
        for item in record.segments
    )


def inspect_watchalong_translation(
    corpus: TranscriptCorpus,
    record: TranscriptRecord,
    provider,
) -> CorpusTranslationOutcome:
    return CorpusTranslationService(corpus).inspect(
        record,
        provider,
        model=provider.model,
        target_language=WATCHALONG_TRANSLATION_TARGET,
        rules_version=WATCHALONG_TRANSLATION_RULES_VERSION,
    )


def translate_watchalong_record(
    corpus: TranscriptCorpus,
    record: TranscriptRecord,
    provider,
    **resume_options,
) -> CorpusTranslationOutcome:
    """Translate only after the existing UI button explicitly calls this seam."""
    return CorpusTranslationService(corpus).translate(
        record,
        provider,
        model=provider.model,
        target_language=WATCHALONG_TRANSLATION_TARGET,
        rules_version=WATCHALONG_TRANSLATION_RULES_VERSION,
        provenance={"ui": "watchalong"},
        **resume_options,
    )


def watchalong_translation_view(
    record: TranscriptRecord,
    provider,
    outcome: CorpusTranslationOutcome,
) -> WatchalongTranslationView:
    segments = _record_segments(record)
    if outcome.artifact is not None:
        translated = tuple(
            replace(segment, translated_text=text)
            for segment, text in zip(
                segments, outcome.artifact.translations, strict=True
            )
        )
        return WatchalongTranslationView(
            translated, 1, 1, None, True, outcome.reused
        )
    state = load_state(
        segments,
        provider,
        outcome.checkpoint_path,
        target_language=outcome.identity.target_language,
    )
    ready = sum(batch["status"] == "ready" for batch in state["batches"])
    return WatchalongTranslationView(
        partial_segments(segments, state),
        ready,
        len(state["batches"]),
        state["failure"],
        False,
        False,
    )
