"""Bridge resumable translation checkpoints to immutable corpus artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from resilient_translation import load_state, partial_segments, translate_resumable
from transcript_corpus import (
    TranscriptCorpus,
    TranscriptRecord,
    TranslationArtifact,
    TranslationIdentity,
)
from transcript_pipeline import TranscriptSegment


DEFAULT_CHECKPOINT_ROOT = Path("data/watchalong/translations/corpus")


@dataclass(frozen=True, slots=True)
class CorpusTranslationOutcome:
    identity: TranslationIdentity
    artifact: TranslationArtifact | None
    checkpoint_path: Path
    checkpoint_status: str
    reused: bool

    @property
    def complete(self) -> bool:
        return self.artifact is not None


class CorpusTranslationService:
    def __init__(
        self,
        corpus: TranscriptCorpus,
        *,
        checkpoint_root: str | Path = DEFAULT_CHECKPOINT_ROOT,
    ) -> None:
        self.corpus = corpus
        self.checkpoint_root = Path(checkpoint_root)

    def _context(
        self,
        record: TranscriptRecord,
        provider,
        *,
        model: str,
        target_language: str = "zh-TW",
        rules_version: str,
        max_segments: int = 20,
        max_chars: int = 2_000,
    ) -> tuple[TranslationIdentity, Path, tuple[TranscriptSegment, ...]]:
        identity = TranslationIdentity(
            transcript_hash=record.content_hash,
            translation_provider=provider.name,
            model=model,
            target_language=target_language,
            rules_version=rules_version,
        )
        path = (
            self.checkpoint_root
            / record.video_id
            / record.transcript_id
            / f"{identity.artifact_id}.json"
        )
        segments = tuple(
            TranscriptSegment(
                segment.start_ms,
                segment.end_ms,
                segment.source_text,
                provider=record.source_type,
            )
            for segment in record.segments
        )
        return identity, path, segments

    def inspect(
        self,
        record: TranscriptRecord,
        provider,
        *,
        model: str,
        target_language: str = "zh-TW",
        rules_version: str,
        max_segments: int = 20,
        max_chars: int = 2_000,
    ) -> CorpusTranslationOutcome:
        """Read final/checkpoint state without invoking the translation provider."""
        identity, path, segments = self._context(
            record,
            provider,
            model=model,
            target_language=target_language,
            rules_version=rules_version,
        )
        artifact = self.corpus.load_translation(record.video_id, identity)
        if artifact is not None:
            return CorpusTranslationOutcome(identity, artifact, path, "ready", True)
        state = load_state(
            segments,
            provider,
            path,
            target_language=target_language,
            max_segments=max_segments,
            max_chars=max_chars,
        )
        return CorpusTranslationOutcome(identity, None, path, state["status"], False)

    def translate(
        self,
        record: TranscriptRecord,
        provider,
        *,
        model: str,
        target_language: str = "zh-TW",
        rules_version: str,
        max_segments: int = 20,
        max_chars: int = 2_000,
        provenance: Mapping[str, object] | None = None,
        **resume_options,
    ) -> CorpusTranslationOutcome:
        current = self.inspect(
            record,
            provider,
            model=model,
            target_language=target_language,
            rules_version=rules_version,
            max_segments=max_segments,
            max_chars=max_chars,
        )
        if current.artifact is not None:
            return current
        identity, path, segments = self._context(
            record,
            provider,
            model=model,
            target_language=target_language,
            rules_version=rules_version,
        )
        state = translate_resumable(
            segments,
            provider,
            path=path,
            target_language=target_language,
            max_segments=max_segments,
            max_chars=max_chars,
            **resume_options,
        )
        if state["status"] != "ready":
            return CorpusTranslationOutcome(
                identity, None, path, state["status"], False
            )

        completed = partial_segments(segments, state)
        translations = tuple(segment.translated_text for segment in completed)
        if any(value is None for value in translations):
            raise ValueError("ready checkpoint contains incomplete translations")
        artifact = self.corpus.save_translation(
            record,
            identity,
            translations,
            provenance={
                "checkpoint_identity": state["identity"],
                **dict(provenance or {}),
            },
        )
        return CorpusTranslationOutcome(identity, artifact, path, "ready", False)
