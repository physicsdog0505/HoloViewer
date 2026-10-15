"""Reusable transcript preview, ingest, and public-caption orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from transcript_corpus import (
    IngestResult,
    TranscriptCorpus,
    TranscriptRecord,
    canonical_youtube_identity,
)
from transcript_pipeline import TranscriptProviderError
from watchalong_transcript import parse_manual_transcript
from direct_youtube_caption_provider import DirectYouTubeCaptionProvider
from innertube_youtube_caption_provider import InnerTubeCaptionProvider
from youtube_transcript_provider import PublicCaptionResult, YtDlpSubtitleProvider


@dataclass(frozen=True, slots=True)
class IngestPreview:
    video_id: str
    canonical_url: str
    source_type: str
    language: str
    provenance: Mapping[str, object]
    valid_segment_count: int
    ignored_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    preview: IngestPreview
    record: TranscriptRecord
    selected_transcript: TranscriptRecord
    reused: bool


@dataclass(frozen=True, slots=True)
class AcquisitionAttempt:
    provider: str
    ok: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class PublicCaptionOutcome:
    ingest: IngestOutcome | None
    unavailable_reason: str | None
    attempts: tuple["AcquisitionAttempt", ...] = ()
    fallback_sources: tuple[str, ...] = ("asr", "manual_paste")

    @property
    def available(self) -> bool:
        return self.ingest is not None


class PublicCaptionProvider(Protocol):
    name: str

    def acquire(self, source: str) -> PublicCaptionResult:
        """Return public caption evidence without authentication."""


class TranscriptIngestService:
    def __init__(
        self,
        corpus: TranscriptCorpus,
        *,
        caption_provider: PublicCaptionProvider | None = None,
        caption_providers: Sequence[PublicCaptionProvider] | None = None,
    ) -> None:
        self.corpus = corpus
        if caption_provider is not None and caption_providers is not None:
            raise ValueError("choose caption_provider or caption_providers, not both")
        if caption_provider is not None:
            self.caption_providers = (caption_provider,)
        elif caption_providers is not None:
            self.caption_providers = tuple(caption_providers)
        else:
            self.caption_providers = (
                InnerTubeCaptionProvider("ANDROID"),
                InnerTubeCaptionProvider("IOS"),
                DirectYouTubeCaptionProvider(),
                YtDlpSubtitleProvider(),
            )
        if not self.caption_providers:
            raise ValueError("at least one public caption provider is required")

    def preview_manual(
        self,
        video_url: str,
        raw_text: str,
        *,
        language: str = "ja",
        provenance: Mapping[str, object] | None = None,
    ) -> IngestPreview:
        video_id, canonical_url = canonical_youtube_identity(video_url)
        if not language.strip():
            raise ValueError("language must not be empty")
        parsed = parse_manual_transcript(raw_text)
        return IngestPreview(
            video_id=video_id,
            canonical_url=canonical_url,
            source_type="manual_paste",
            language=language.strip(),
            provenance=dict(provenance or {}),
            valid_segment_count=len(parsed.segments),
            ignored_lines=parsed.ignored_lines,
        )

    def ingest_manual(
        self,
        video_url: str,
        raw_text: str,
        *,
        language: str = "ja",
        provenance: Mapping[str, object] | None = None,
    ) -> IngestOutcome:
        preview = self.preview_manual(
            video_url, raw_text, language=language, provenance=provenance
        )
        result = self.corpus.ingest_transcript(
            video_url,
            raw_text,
            "manual_paste",
            language,
            provenance=provenance,
        )
        return self._outcome(video_url, preview, result)

    def fetch_public_caption(
        self, video_url: str, *, refresh: bool = False
    ) -> PublicCaptionOutcome:
        video_id, canonical_url = canonical_youtube_identity(video_url)
        if not refresh:
            captions = tuple(
                record
                for record in self.corpus.list_transcripts(canonical_url)
                if record.source_type == "youtube_caption"
            )
            if captions:
                # Apply corpus policy to all versions first. If a reviewed/manual
                # record wins, keep it as selected while reusing the newest
                # existing caption as the source-specific ingest result.
                caption = max(
                    captions, key=lambda item: (item.observed_at, item.transcript_id)
                )
                preview = IngestPreview(
                    video_id=caption.video_id,
                    canonical_url=caption.canonical_url,
                    source_type=caption.source_type,
                    language=caption.language,
                    provenance=caption.provenance,
                    valid_segment_count=caption.segment_count,
                    ignored_lines=(),
                )
                selected = self.corpus.select_transcript(canonical_url)
                if selected is None:
                    raise RuntimeError("stored transcript was not selectable")
                return PublicCaptionOutcome(
                    ingest=IngestOutcome(preview, caption, selected, True),
                    unavailable_reason=None,
                    attempts=(),
                )
        attempts = []
        caption = None
        for provider in self.caption_providers:
            provider_name = getattr(provider, "name", provider.__class__.__name__)
            try:
                caption = provider.acquire(canonical_url)
            except TranscriptProviderError as exc:
                attempts.append(AcquisitionAttempt(provider_name, False, str(exc)))
                continue
            attempts.append(AcquisitionAttempt(provider_name, True, None))
            break
        if caption is None:
            summary = "; ".join(
                f"{attempt.provider}: {attempt.error}" for attempt in attempts
            )
            return PublicCaptionOutcome(
                ingest=None,
                unavailable_reason=(
                    f"Public captions unavailable after all providers: {summary}. "
                    "Use an ASR source or manual paste instead."
                ),
                attempts=tuple(attempts),
            )
        provenance = {
            "provider": caption.provider,
            "track_id": caption.track_id,
            "access": "public_no_auth",
            **caption.provenance,
        }
        preview = IngestPreview(
            video_id=video_id,
            canonical_url=canonical_url,
            source_type="youtube_caption",
            language=caption.language,
            provenance=provenance,
            valid_segment_count=len(caption.segments),
            ignored_lines=(),
        )
        result = self.corpus.ingest_transcript(
            canonical_url,
            caption.raw_text,
            "youtube_caption",
            caption.language,
            segments=caption.segments,
            provenance=provenance,
        )
        return PublicCaptionOutcome(
            ingest=self._outcome(canonical_url, preview, result),
            unavailable_reason=None,
            attempts=tuple(attempts),
        )

    def _outcome(
        self, video_url: str, preview: IngestPreview, result: IngestResult
    ) -> IngestOutcome:
        selected = self.corpus.select_transcript(video_url)
        if selected is None:
            raise RuntimeError("ingested transcript was not selectable")
        return IngestOutcome(
            preview=preview,
            record=result.record,
            selected_transcript=selected,
            reused=not result.created,
        )
