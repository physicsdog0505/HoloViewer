"""Bridge the existing Watchalong session UX to the reusable transcript corpus."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from frontend_time import youtube_video_id
from transcript_corpus import TranscriptCorpus, TranscriptRecord
from transcript_ingest import IngestOutcome, PublicCaptionOutcome, TranscriptIngestService
from watchalong_archive_store import (
    SavedWatchalongSession,
    load_latest_session_for_master_identity,
    save_watchalong_session,
)
from watchalong_transcript import format_timestamp_ms


@dataclass(frozen=True, slots=True)
class WatchalongTranscriptLoad:
    saved_session: SavedWatchalongSession | None
    transcript_text: str
    record: TranscriptRecord | None
    reused: bool
    legacy_imported: bool = False
    public_outcome: PublicCaptionOutcome | None = None
    compatibility_error: str | None = None


@dataclass(frozen=True, slots=True)
class WatchalongTranscriptSave:
    saved_session: SavedWatchalongSession
    ingest: IngestOutcome


def watchalong_master_identity(master_url: str) -> str:
    """Stable UI load key; equivalent YouTube URLs intentionally compare equal."""
    value = master_url.strip()
    return youtube_video_id(value) or value


def _display_text(corpus: TranscriptCorpus, record: TranscriptRecord) -> str:
    if record.source_type == "manual_paste":
        return corpus.raw_evidence(record)
    return "\n".join(
        f"{format_timestamp_ms(segment.start_ms)} {segment.source_text}"
        for segment in record.segments
    )


def load_watchalong_transcript(
    master_url: str,
    *,
    archive_path: str | Path | None = None,
    corpus: TranscriptCorpus | None = None,
    ingest_service: TranscriptIngestService | None = None,
    read_only: bool = False,
) -> WatchalongTranscriptLoad:
    """Restore session metadata and resolve its transcript from one owning corpus.

    ``read_only`` is for 4174 consumers: it never imports legacy text into the
    corpus and never contacts a caption provider. 8501 keeps the historical
    acquisition/import behavior by using the default ``False``.
    """
    corpus = corpus or TranscriptCorpus()
    service = ingest_service or TranscriptIngestService(corpus)
    saved = load_latest_session_for_master_identity(master_url, archive_path)

    if read_only:
        selected = corpus.select_transcript(master_url)
        if selected is not None:
            return WatchalongTranscriptLoad(
                saved, _display_text(corpus, selected), selected, reused=True
            )
        if saved is not None and saved.transcript_text.strip():
            return WatchalongTranscriptLoad(
                saved, saved.transcript_text, None, reused=True
            )
        return WatchalongTranscriptLoad(saved, "", None, reused=False)

    if saved is not None and saved.transcript_text.strip():
        try:
            imported = service.ingest_manual(
                master_url,
                saved.transcript_text,
                provenance={"legacy_archive_session_id": saved.id},
            )
        except (OSError, ValueError) as exc:
            # Keep old sessions usable even if historical free-form text cannot
            # satisfy the new timestamped corpus contract.
            selected = corpus.select_transcript(master_url)
            if selected is not None:
                return WatchalongTranscriptLoad(
                    saved,
                    _display_text(corpus, selected),
                    selected,
                    reused=True,
                    compatibility_error=f"{type(exc).__name__}: {exc}",
                )
            return WatchalongTranscriptLoad(
                saved,
                saved.transcript_text,
                None,
                reused=False,
                compatibility_error=f"{type(exc).__name__}: {exc}",
            )
        selected = corpus.select_transcript(master_url)
        if selected is None:
            raise RuntimeError("imported legacy transcript was not selectable")
        return WatchalongTranscriptLoad(
            saved,
            _display_text(corpus, selected),
            selected,
            reused=imported.reused,
            legacy_imported=not imported.reused,
        )

    selected = corpus.select_transcript(master_url)
    if selected is not None:
        return WatchalongTranscriptLoad(
            saved, _display_text(corpus, selected), selected, reused=True
        )

    public = service.fetch_public_caption(master_url)
    if public.available:
        assert public.ingest is not None
        selected = public.ingest.selected_transcript
        return WatchalongTranscriptLoad(
            saved,
            _display_text(corpus, selected),
            selected,
            reused=public.ingest.reused,
            public_outcome=public,
        )
    return WatchalongTranscriptLoad(
        saved,
        "",
        None,
        reused=False,
        public_outcome=public,
    )


def save_watchalong_transcript(
    *,
    master_url: str,
    source_urls: list[str] | tuple[str, ...],
    transcript_text: str,
    archive_path: str | Path | None = None,
    corpus: TranscriptCorpus | None = None,
    ingest_service: TranscriptIngestService | None = None,
) -> WatchalongTranscriptSave:
    """Save session metadata, then register the same manual evidence in corpus."""
    corpus = corpus or TranscriptCorpus()
    service = ingest_service or TranscriptIngestService(corpus)
    saved = save_watchalong_session(
        master_url=master_url,
        source_urls=source_urls,
        transcript_text=transcript_text,
        path=archive_path,
    )
    ingest = service.ingest_manual(
        master_url,
        transcript_text,
        provenance={"watchalong_archive_session_id": saved.id},
    )
    return WatchalongTranscriptSave(saved, ingest)
