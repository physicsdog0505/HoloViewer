"""Reusable Gemini quality-v2 translation service for transcript corpus records.

This module is the production-facing seam for Issue #198.  It owns the final
translation-artifact identity and orchestration, but no Streamlit UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from gemini_translation_provider import GeminiTranslationProvider
from gemini_translation_quality import (
    GeminiQualityTranslationProvider,
    GeminiTranslationPostEditor,
    GeminiTranslationReviewer,
    normalize_bracketed_cues,
)
from resilient_translation import checkpoint_path, partial_segments, translate_resumable
from transcript_corpus import (
    TranscriptCorpus,
    TranscriptRecord,
    TranslationArtifact,
    TranslationIdentity,
)
from transcript_pipeline import TranscriptSegment
from translation_benchmark import DEFAULT_GLOSSARY
from translation_quality_benchmark import evaluate_post_edit_diff
from translation_quality_pipeline import post_edit_in_batches, review_in_batches


QUALITY_V2_TARGET = "zh-TW"
QUALITY_V2_RULES_VERSION = "gemini-quality-v2-glossary-qe-postedit-v1"
QUALITY_V2_DEFAULT_MODEL = "gemini-3.5-flash-lite"
QUALITY_V2_CHECKPOINT_ROOT = Path("data/watchalong/translations/quality_v2")


@dataclass(frozen=True, slots=True)
class QualityV2TranslationOutcome:
    artifact: TranslationArtifact
    reused: bool
    metadata: dict[str, object]


def quality_v2_provider_name(model: str) -> str:
    return f"gemini-quality-v2:{model}:glossary+qe+selective-post-edit"


def quality_v2_identity(
    record: TranscriptRecord,
    *,
    model: str = QUALITY_V2_DEFAULT_MODEL,
) -> TranslationIdentity:
    return TranslationIdentity(
        transcript_hash=record.content_hash,
        translation_provider=quality_v2_provider_name(model),
        model=model,
        target_language=QUALITY_V2_TARGET,
        rules_version=QUALITY_V2_RULES_VERSION,
    )


def inspect_quality_v2_translation(
    corpus: TranscriptCorpus,
    record: TranscriptRecord,
    *,
    model: str = QUALITY_V2_DEFAULT_MODEL,
) -> TranslationArtifact | None:
    return corpus.load_translation(
        record.video_id,
        quality_v2_identity(record, model=model),
    )


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


def translate_quality_v2_record(
    corpus: TranscriptCorpus,
    record: TranscriptRecord,
    *,
    model: str = QUALITY_V2_DEFAULT_MODEL,
    checkpoint_root: Path = QUALITY_V2_CHECKPOINT_ROOT,
    translation_batch_size: int = 20,
    qe_batch_size: int = 20,
    qe_context_size: int = 2,
    request_interval_seconds: float = 4.2,
    provenance: dict[str, object] | None = None,
    on_stage: Callable[[str], None] | None = None,
    generation_guard: Callable[[str, str], None] | None = None,
) -> QualityV2TranslationOutcome:
    """Translate one corpus record and persist/reuse the immutable final artifact."""
    if translation_batch_size <= 0 or qe_batch_size <= 0:
        raise ValueError("batch sizes must be > 0")
    if qe_context_size < 0:
        raise ValueError("QE context size must be >= 0")
    if request_interval_seconds < 0:
        raise ValueError("request interval must be >= 0")

    identity = quality_v2_identity(record, model=model)
    existing = corpus.load_translation(record.video_id, identity)
    if existing is not None:
        return QualityV2TranslationOutcome(
            artifact=existing,
            reused=True,
            metadata=dict(existing.provenance),
        )

    segments = _record_segments(record)
    base = GeminiTranslationProvider(model=model, generation_guard=generation_guard)
    initial_provider = GeminiQualityTranslationProvider(
        provider=base,
        glossary=DEFAULT_GLOSSARY,
    )
    reviewer = GeminiTranslationReviewer(provider=base)
    editor = GeminiTranslationPostEditor(provider=base)

    if on_stage:
        on_stage("configuration")
    base.preflight(target_language=QUALITY_V2_TARGET)

    path = checkpoint_path(
        segments,
        initial_provider,
        base_dir=checkpoint_root,
        target_language=QUALITY_V2_TARGET,
        max_segments=translation_batch_size,
        max_chars=2_000,
    )
    if on_stage:
        on_stage("initial_translation")
    state = translate_resumable(
        segments,
        initial_provider,
        path=path,
        target_language=QUALITY_V2_TARGET,
        max_segments=translation_batch_size,
        max_chars=2_000,
        request_interval_seconds=request_interval_seconds,
    )
    if state["status"] != "ready":
        failure = state.get("failure") or {}
        raise RuntimeError(
            f"initial translation stopped: {failure.get('message', 'unknown failure')}; "
            f"checkpoint kept at {path}"
        )

    translated_segments = partial_segments(segments, state)
    raw_initial = tuple(
        str(item.translated_text or "").strip() for item in translated_segments
    )
    if any(not item for item in raw_initial):
        raise RuntimeError("ready initial-translation checkpoint contains empty text")
    initial = tuple(normalize_bracketed_cues(item) for item in raw_initial)
    cue_normalized_count = sum(
        before != after
        for before, after in zip(raw_initial, initial, strict=True)
    )
    sources = tuple(item.source_text for item in segments)

    if request_interval_seconds and getattr(initial_provider, "request_count", 0):
        time.sleep(request_interval_seconds)
    if on_stage:
        on_stage("qe")
    findings = review_in_batches(
        reviewer,
        sources,
        initial,
        batch_size=qe_batch_size,
        context_size=qe_context_size,
        glossary=DEFAULT_GLOSSARY,
        request_interval_seconds=request_interval_seconds,
    )

    if request_interval_seconds and any(item.needs_revision for item in findings):
        time.sleep(request_interval_seconds)
    if on_stage:
        on_stage("post_edit")
    revised = post_edit_in_batches(
        editor,
        sources,
        initial,
        findings,
        batch_size=qe_batch_size,
        context_size=qe_context_size,
        glossary=DEFAULT_GLOSSARY,
        request_interval_seconds=request_interval_seconds,
    )
    revised = tuple(normalize_bracketed_cues(item) for item in revised)
    diff = evaluate_post_edit_diff(initial, revised, findings)

    metadata: dict[str, object] = {
        "pipeline": "gemini-quality-v2",
        "model": model,
        "checkpoint": str(path),
        "translation_batch_size": translation_batch_size,
        "qe_batch_size": qe_batch_size,
        "qe_context_size": qe_context_size,
        "cue_normalized_count": cue_normalized_count,
        "diff": diff.to_dict(),
        "usage": {
            "scope": (
                "current invocation; resumed ready initial batches are not re-counted"
            ),
            "initial_translation": dict(initial_provider.last_usage),
            "qe": dict(reviewer.last_usage),
            "post_edit": dict(editor.last_usage),
        },
        "findings": [
            {
                "id": item.id,
                "needs_revision": item.needs_revision,
                "severity": item.severity,
                "issues": list(item.issues),
                "instruction": item.instruction,
            }
            for item in findings
        ],
        **dict(provenance or {}),
    }
    artifact = corpus.save_translation(
        record,
        identity,
        revised,
        provenance=metadata,
    )
    if on_stage:
        on_stage("ready")
    return QualityV2TranslationOutcome(
        artifact=artifact,
        reused=False,
        metadata=metadata,
    )


def quality_v2_segments(
    record: TranscriptRecord,
    artifact: TranslationArtifact,
) -> tuple[TranscriptSegment, ...]:
    if artifact.identity.transcript_hash != record.content_hash:
        raise ValueError("translation artifact does not match transcript")
    if len(artifact.translations) != record.segment_count:
        raise ValueError("translation artifact segment count mismatch")
    return tuple(
        TranscriptSegment(
            item.start_ms,
            item.end_ms,
            item.source_text,
            translated_text=translated,
            provider=record.source_type,
        )
        for item, translated in zip(
            record.segments, artifact.translations, strict=True
        )
    )
