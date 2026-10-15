"""Reusable transcript -> translated subtitle component.

This module intentionally owns no Streamlit or Watchalong UI.  Pages and acceptance
tools share the same transcript acquisition and timestamp-preserving payload seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from transcript_corpus import (
    TranscriptCorpus,
    TranscriptRecord,
    TranslationArtifact,
    TranslationIdentity,
)
from transcript_ingest import PublicCaptionOutcome, TranscriptIngestService
from transcript_pipeline import TranscriptSegment


@dataclass(frozen=True, slots=True)
class SubtitleTranslationInput:
    record: TranscriptRecord
    reused_transcript: bool
    acquisition: PublicCaptionOutcome


@dataclass(frozen=True, slots=True)
class SubtitleTranslationResult:
    record: TranscriptRecord
    segments: tuple[TranscriptSegment, ...]
    translation_provider: str
    metadata: dict[str, object]


class SubtitleTranslationComponent:
    """Provider-neutral orchestration seam for translated subtitles.

    Transcript acquisition is shared with Watchalong.  Translation itself is injected
    as a callable so Gemini quality-v2, a future local model, OpenAI, or a cached
    artifact can all reuse the same page/component contract.
    """

    def __init__(
        self,
        corpus: TranscriptCorpus | None = None,
        *,
        ingest_service: TranscriptIngestService | None = None,
    ) -> None:
        self.corpus = corpus or TranscriptCorpus()
        self.ingest = ingest_service or TranscriptIngestService(self.corpus)

    def acquire_public_transcript(
        self,
        video_url: str,
        *,
        refresh: bool = False,
    ) -> SubtitleTranslationInput:
        outcome = self.ingest.fetch_public_caption(video_url, refresh=refresh)
        if not outcome.available or outcome.ingest is None:
            reason = outcome.unavailable_reason or "public transcript unavailable"
            raise ValueError(reason)
        # Honor corpus selection policy (reviewed/default transcript can intentionally
        # override the newly fetched caption), while keeping the acquisition evidence.
        record = outcome.ingest.selected_transcript
        return SubtitleTranslationInput(
            record=record,
            reused_transcript=outcome.ingest.reused,
            acquisition=outcome,
        )

    @staticmethod
    def record_segments(record: TranscriptRecord) -> tuple[TranscriptSegment, ...]:
        return tuple(
            TranscriptSegment(
                item.start_ms,
                item.end_ms,
                item.source_text,
                provider=record.source_type,
            )
            for item in record.segments
        )

    def translate(
        self,
        transcript: SubtitleTranslationInput,
        translator: Callable[
            [tuple[TranscriptSegment, ...]],
            tuple[Sequence[str], str, dict[str, object]],
        ],
    ) -> SubtitleTranslationResult:
        source_segments = self.record_segments(transcript.record)
        translations, provider_name, metadata = translator(source_segments)
        values = tuple(str(value).strip() for value in translations)
        if len(values) != len(source_segments):
            raise ValueError("translator must return exactly one translation per segment")
        if any(not value for value in values):
            raise ValueError("translator returned an empty translation")
        translated = tuple(
            TranscriptSegment(
                segment.start_ms,
                segment.end_ms,
                segment.source_text,
                translated_text=value,
                provider=segment.provider,
            )
            for segment, value in zip(source_segments, values, strict=True)
        )
        return SubtitleTranslationResult(
            record=transcript.record,
            segments=translated,
            translation_provider=str(provider_name),
            metadata=dict(metadata),
        )

    def save_translation_artifact(
        self,
        result: SubtitleTranslationResult,
        *,
        model: str,
        target_language: str = "zh-TW",
        rules_version: str,
        provenance: dict[str, object] | None = None,
    ) -> TranslationArtifact:
        """Persist one immutable reusable artifact for future page consumers."""
        identity = TranslationIdentity(
            transcript_hash=result.record.content_hash,
            translation_provider=result.translation_provider,
            model=model,
            target_language=target_language,
            rules_version=rules_version,
        )
        translations = tuple(
            str(item.translated_text or "").strip() for item in result.segments
        )
        return self.corpus.save_translation(
            result.record,
            identity,
            translations,
            provenance={
                "component": "subtitle_translation",
                **dict(result.metadata),
                **dict(provenance or {}),
            },
        )

    @staticmethod
    def preview_payload(result: SubtitleTranslationResult) -> dict[str, object]:
        return {
            "source": result.record.canonical_url,
            "asr_provider": result.record.source_type,
            "translation_provider": result.translation_provider,
            "translation_metadata": result.metadata,
            "segments": [
                {
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "source_text": item.source_text,
                    "translated_text": item.translated_text,
                    "provider": item.provider,
                }
                for item in result.segments
            ],
        }
