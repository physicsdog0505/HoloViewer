"""Reusable old-VOD transcript/translation facade.

This module is UI-neutral. Inspecting state never calls Gemini or a caption provider;
network/provider work happens only through explicit acquire/translate methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from quality_v2_translation_service import (
    QualityV2TranslationOutcome,
    inspect_quality_v2_translation,
    quality_v2_segments,
    translate_quality_v2_record,
)
from subtitle_translation_component import SubtitleTranslationComponent
from transcript_corpus import TranscriptCorpus, TranscriptRecord, TranslationArtifact
from transcript_ingest import TranscriptIngestService
from transcript_pipeline import TranscriptSegment


@dataclass(frozen=True, slots=True)
class ArchiveTranslationSnapshot:
    status: str
    record: TranscriptRecord | None
    artifact: TranslationArtifact | None
    segments: tuple[TranscriptSegment, ...]
    reused_transcript: bool | None = None

    @property
    def has_transcript(self) -> bool:
        return self.record is not None

    @property
    def has_translation(self) -> bool:
        return self.artifact is not None


class ArchiveTranslationService:
    """Shared translation readiness/read path for completed YouTube VOD surfaces."""

    def __init__(
        self,
        corpus: TranscriptCorpus | None = None,
        *,
        ingest_service: TranscriptIngestService | None = None,
    ) -> None:
        self.corpus = corpus or TranscriptCorpus()
        self.component = SubtitleTranslationComponent(
            self.corpus,
            ingest_service=ingest_service,
        )

    def inspect(self, video_url: str) -> ArchiveTranslationSnapshot:
        """Read corpus/artifact state without acquiring captions or calling Gemini."""
        record = self.corpus.select_transcript(video_url)
        if record is None:
            return ArchiveTranslationSnapshot(
                status="missing_transcript",
                record=None,
                artifact=None,
                segments=(),
            )

        artifact = inspect_quality_v2_translation(self.corpus, record)
        if artifact is None:
            return ArchiveTranslationSnapshot(
                status="transcript_ready",
                record=record,
                artifact=None,
                segments=self.component.record_segments(record),
            )

        return ArchiveTranslationSnapshot(
            status="translation_ready",
            record=record,
            artifact=artifact,
            segments=quality_v2_segments(record, artifact),
        )

    def acquire_public_transcript(
        self,
        video_url: str,
        *,
        refresh: bool = False,
    ) -> ArchiveTranslationSnapshot:
        """Explicitly acquire/reuse a public caption, then return current readiness."""
        acquired = self.component.acquire_public_transcript(
            video_url,
            refresh=refresh,
        )
        snapshot = self.inspect(video_url)
        return ArchiveTranslationSnapshot(
            status=snapshot.status,
            record=snapshot.record,
            artifact=snapshot.artifact,
            segments=snapshot.segments,
            reused_transcript=acquired.reused_transcript,
        )

    def translate_quality_v2(
        self,
        video_url: str,
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> tuple[ArchiveTranslationSnapshot, QualityV2TranslationOutcome]:
        """Explicitly create/reuse the quality-v2 artifact for the selected transcript."""
        snapshot = self.inspect(video_url)
        if snapshot.record is None:
            raise ValueError("archive translation requires a transcript first")
        outcome = translate_quality_v2_record(
            self.corpus,
            snapshot.record,
            provenance={"consumer": "archive_translation"},
            on_stage=on_stage,
        )
        return self.inspect(video_url), outcome
