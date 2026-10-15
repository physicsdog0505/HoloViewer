"""Local, provider-neutral transcript corpus for Watchalong.

The corpus is deliberately filesystem-backed and independent of Streamlit and
the Collector databases. Raw evidence is immutable; normalized segments and
translation artifacts are rebuildable, deterministic JSON documents.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping, Sequence

from frontend_time import youtube_video_id
from transcript_pipeline import TranscriptSegment, normalize_segments
from watchalong_transcript import parse_manual_transcript


SCHEMA_VERSION = 1
DEFAULT_ROOT = Path("data/watchalong/transcripts")
SOURCE_TYPES = frozenset({"manual_paste", "youtube_caption", "asr"})
SOURCE_PRIORITY = {"youtube_caption": 0, "manual_paste": 1, "asr": 2}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_youtube_identity(value: str) -> tuple[str, str]:
    video_id = youtube_video_id(value)
    if video_id is None:
        raise ValueError("a valid YouTube video URL or id is required")
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True, slots=True)
class CorpusSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    source_text: str


@dataclass(frozen=True, slots=True)
class TranscriptRecord:
    transcript_id: str
    provider: str
    video_id: str
    canonical_url: str
    source_type: str
    language: str
    raw_sha256: str
    content_hash: str
    segment_count: int
    created_at: str
    observed_at: str
    parser_version: str
    provenance_identity: Mapping[str, str]
    provenance: Mapping[str, object]
    segments: tuple[CorpusSegment, ...]


@dataclass(frozen=True, slots=True)
class IngestResult:
    record: TranscriptRecord
    created: bool
    ignored_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranslationIdentity:
    transcript_hash: str
    translation_provider: str
    model: str
    target_language: str
    rules_version: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not str(value).strip():
                raise ValueError(f"{name} must not be empty")

    @property
    def artifact_id(self) -> str:
        return _sha256(_canonical_json(asdict(self)))


@dataclass(frozen=True, slots=True)
class TranslationArtifact:
    artifact_id: str
    identity: TranslationIdentity
    translations: tuple[str, ...]
    created_at: str
    provenance: Mapping[str, object]


def _normalized_payload(segments: Sequence[TranscriptSegment]) -> list[dict[str, object]]:
    return [
        {"start_ms": item.start_ms, "end_ms": item.end_ms, "source_text": item.source_text}
        for item in normalize_segments(segments)
    ]


def _corpus_segments(payload: Sequence[Mapping[str, object]]) -> tuple[CorpusSegment, ...]:
    result = []
    for index, item in enumerate(payload):
        identity = _sha256(_canonical_json({"index": index, **item}))[:24]
        result.append(CorpusSegment(segment_id=identity, **item))
    return tuple(result)


def _provenance_identity(
    source_type: str, provenance: Mapping[str, object]
) -> dict[str, str]:
    required = {
        "manual_paste": (),
        "youtube_caption": ("provider", "track_id"),
        "asr": ("provider", "model"),
    }[source_type]
    identity: dict[str, str] = {}
    for name in required:
        value = provenance.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{source_type} provenance requires non-empty {name}")
        identity[name] = value.strip()
    # An optional caller-controlled revision distinguishes acquisition settings
    # without making volatile diagnostic metadata part of transcript identity.
    revision = provenance.get("revision")
    if revision is not None:
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("provenance revision must be a non-empty string")
        identity["revision"] = revision.strip()
    return identity


class TranscriptCorpus:
    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        self.root = Path(root)

    def _video_root(self, video_id: str) -> Path:
        return self.root / "youtube" / video_id

    def _transcript_path(self, video_id: str, transcript_id: str) -> Path:
        return self._video_root(video_id) / "transcripts" / transcript_id

    def ingest_transcript(
        self,
        video_url: str,
        raw_text: str,
        source_type: str,
        language: str,
        *,
        segments: Sequence[TranscriptSegment] | None = None,
        provenance: Mapping[str, object] | None = None,
        observed_at: str | None = None,
    ) -> IngestResult:
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source_type}")
        if not raw_text:
            raise ValueError("raw_text must not be empty")
        if not language.strip():
            raise ValueError("language must not be empty")
        provenance_values = dict(provenance or {})
        provenance_identity = _provenance_identity(source_type, provenance_values)
        video_id, canonical_url = canonical_youtube_identity(video_url)
        ignored: tuple[str, ...] = ()
        if segments is None:
            if source_type != "manual_paste":
                raise ValueError("segments are required for non-manual transcript sources")
            parsed = parse_manual_transcript(raw_text)
            segments = parsed.segments
            ignored = parsed.ignored_lines
        payload = _normalized_payload(segments)
        if not payload:
            raise ValueError("transcript contains no valid timestamped segments")

        raw_bytes = raw_text.encode("utf-8")
        raw_hash = _sha256(raw_bytes)
        content_hash = _sha256(_canonical_json(payload))
        version_identity = {
            "provider": "youtube",
            "video_id": video_id,
            "source_type": source_type,
            "language": language.strip(),
            "raw_sha256": raw_hash,
            "content_hash": content_hash,
            "provenance_identity": provenance_identity,
        }
        transcript_id = _sha256(_canonical_json(version_identity))
        target = self._transcript_path(video_id, transcript_id)
        metadata_path = target / "metadata.json"
        if metadata_path.exists():
            return IngestResult(self.load_transcript(video_id, transcript_id), False, ignored)

        now = datetime.now(timezone.utc).isoformat()
        record = TranscriptRecord(
            transcript_id=transcript_id,
            provider="youtube",
            video_id=video_id,
            canonical_url=canonical_url,
            source_type=source_type,
            language=language.strip(),
            raw_sha256=raw_hash,
            content_hash=content_hash,
            segment_count=len(payload),
            created_at=now,
            observed_at=observed_at or now,
            parser_version="watchalong-manual-v1" if source_type == "manual_paste" else "supplied-segments-v1",
            provenance_identity=provenance_identity,
            provenance=provenance_values,
            segments=_corpus_segments(payload),
        )
        # Metadata is the commit marker, so readers never observe a partial record.
        _atomic_write(target / "raw.txt", raw_bytes)
        _atomic_write(target / "segments.json", _canonical_json([asdict(s) for s in record.segments]))
        metadata = asdict(record)
        metadata.pop("segments")
        _atomic_write(metadata_path, _canonical_json({"schema_version": SCHEMA_VERSION, **metadata}))
        return IngestResult(record, True, ignored)

    def load_transcript(self, video_id: str, transcript_id: str) -> TranscriptRecord:
        target = self._transcript_path(video_id, transcript_id)
        metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
        if metadata.pop("schema_version", None) != SCHEMA_VERSION:
            raise ValueError("unsupported transcript corpus schema")
        segments = tuple(
            CorpusSegment(**item)
            for item in json.loads((target / "segments.json").read_text(encoding="utf-8"))
        )
        if metadata["segment_count"] != len(segments):
            raise ValueError("transcript segment count mismatch")
        return TranscriptRecord(**metadata, segments=segments)

    def raw_evidence(self, record: TranscriptRecord) -> str:
        return (self._transcript_path(record.video_id, record.transcript_id) / "raw.txt").read_text(
            encoding="utf-8"
        )

    def list_transcripts(self, video_url: str) -> tuple[TranscriptRecord, ...]:
        video_id, _ = canonical_youtube_identity(video_url)
        directory = self._video_root(video_id) / "transcripts"
        if not directory.exists():
            return ()
        records = [self.load_transcript(video_id, path.parent.name) for path in directory.glob("*/metadata.json")]
        return tuple(sorted(records, key=lambda item: (item.created_at, item.transcript_id)))

    def _selection_path(self, video_id: str) -> Path:
        return self._video_root(video_id) / "selection.json"

    def _load_selection(self, video_id: str) -> dict[str, str | None]:
        path = self._selection_path(video_id)
        if not path.exists():
            return {"reviewed_transcript_id": None, "default_transcript_id": None}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.pop("schema_version", None) != SCHEMA_VERSION:
            raise ValueError("unsupported transcript selection schema")
        return payload

    def _set_selection(
        self, video_url: str, field: str, transcript_id: str | None
    ) -> None:
        video_id, _ = canonical_youtube_identity(video_url)
        if transcript_id is not None:
            self.load_transcript(video_id, transcript_id)
        selection = self._load_selection(video_id)
        selection[field] = transcript_id
        _atomic_write(
            self._selection_path(video_id),
            _canonical_json({"schema_version": SCHEMA_VERSION, **selection}),
        )

    def set_reviewed_transcript(
        self, video_url: str, transcript_id: str | None
    ) -> None:
        """Set or clear the human-reviewed transcript for a video."""
        self._set_selection(video_url, "reviewed_transcript_id", transcript_id)

    def set_default_transcript(
        self, video_url: str, transcript_id: str | None
    ) -> None:
        """Set or clear the explicit non-reviewed default for a video."""
        self._set_selection(video_url, "default_transcript_id", transcript_id)

    def select_transcript(self, video_url: str) -> TranscriptRecord | None:
        """Choose reviewed, then default, then deterministic source priority."""
        video_id, _ = canonical_youtube_identity(video_url)
        records = self.list_transcripts(video_url)
        if not records:
            return None
        by_id = {record.transcript_id: record for record in records}
        selection = self._load_selection(video_id)
        for field in ("reviewed_transcript_id", "default_transcript_id"):
            transcript_id = selection.get(field)
            if transcript_id in by_id:
                return by_id[transcript_id]
        # Stable sorts make the tie-break policy explicit: source priority,
        # newest observation, then lexical transcript ID.
        ranked = sorted(records, key=lambda item: item.transcript_id)
        ranked.sort(key=lambda item: item.observed_at, reverse=True)
        ranked.sort(key=lambda item: SOURCE_PRIORITY[item.source_type])
        return ranked[0]

    def _artifact_path(self, video_id: str, identity: TranslationIdentity) -> Path:
        return self._video_root(video_id) / "translations" / f"{identity.artifact_id}.json"

    def load_translation(
        self, video_id: str, identity: TranslationIdentity
    ) -> TranslationArtifact | None:
        path = self._artifact_path(video_id, identity)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.pop("schema_version", None) != SCHEMA_VERSION:
            raise ValueError("unsupported translation artifact schema")
        saved_identity = TranslationIdentity(**payload.pop("identity"))
        artifact = TranslationArtifact(identity=saved_identity, translations=tuple(payload.pop("translations")), **payload)
        if artifact.identity != identity or artifact.artifact_id != identity.artifact_id:
            raise ValueError("translation artifact identity mismatch")
        return artifact

    def save_translation(
        self,
        record: TranscriptRecord,
        identity: TranslationIdentity,
        translations: Sequence[str],
        *,
        provenance: Mapping[str, object] | None = None,
    ) -> TranslationArtifact:
        if identity.transcript_hash != record.content_hash:
            raise ValueError("translation identity does not match transcript content")
        values = tuple(str(value).strip() for value in translations)
        if len(values) != record.segment_count or any(not value for value in values):
            raise ValueError("translations must contain one non-empty value per segment")
        existing = self.load_translation(record.video_id, identity)
        if existing is not None:
            if existing.translations != values:
                raise ValueError("translation artifact is immutable")
            return existing
        artifact = TranslationArtifact(
            artifact_id=identity.artifact_id,
            identity=identity,
            translations=values,
            created_at=datetime.now(timezone.utc).isoformat(),
            provenance=dict(provenance or {}),
        )
        _atomic_write(
            self._artifact_path(record.video_id, identity),
            _canonical_json({"schema_version": SCHEMA_VERSION, **asdict(artifact)}),
        )
        return artifact

    def translate_or_reuse(
        self,
        record: TranscriptRecord,
        identity: TranslationIdentity,
        translate: Callable[[tuple[str, ...]], Sequence[str]],
    ) -> tuple[TranslationArtifact, bool]:
        existing = self.load_translation(record.video_id, identity)
        if existing is not None:
            return existing, True
        source_texts = tuple(segment.source_text for segment in record.segments)
        return self.save_translation(record, identity, translate(source_texts)), False
