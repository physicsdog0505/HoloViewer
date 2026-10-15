"""Offline durable evidence seam for realtime stream discovery.

This store is deliberately not wired into the live WebSub, feed, or PTT paths.
It owns append-only normalized evidence and receipts; latest-state sidecars and a
future disposable Content Catalog remain separate lifecycles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Mapping

from channel_push_discovery import ChannelPushEvent
from ptt_stream_discovery import extract_body_urls
from youtube_metadata import YoutubeVideo


SCHEMA_VERSION = 2
NORMALIZER_VERSION = "discovery-evidence-v1"
WEBSUB_PARSER_VERSION = "youtube-atom-v1"
FEED_PARSER_VERSION = "youtube-channel-feed-v1"
PTT_EXTRACTOR_VERSION = "ptt-body-youtube-url-v1"

EVENT_KINDS = frozenset(
    {
        "accepted_discovery",
        "rejected",
        "verification_failure",
        "missing",
        "retraction",
        "deletion_tombstone",
        "metadata_snapshot",
        "parse_rejection",
    }
)


class EvidenceConflictError(ValueError):
    """An existing evidence identity was replayed with incompatible content."""


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _require_sha256(value: str, *, field: str) -> str:
    digest = value.strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return digest


def _key(*parts: object) -> str:
    return _sha256_text("\x1f".join(str(part) for part in parts))


def websub_source_key(channel_id: str) -> str:
    channel = channel_id.strip()
    if not channel:
        raise ValueError("channel_id must not be empty")
    return f"websub:v1:youtube:channel:{channel}"


def feed_source_key(channel_id: str) -> str:
    channel = channel_id.strip()
    if not channel:
        raise ValueError("channel_id must not be empty")
    return f"channel-feed:v1:youtube:channel:{channel}"


def derive_feed_poll_id(*, channel_id: str, raw_feed_payload: bytes) -> str:
    """Derive the only accepted v1 feed-poll identity from canonical input."""
    source_key = feed_source_key(channel_id)
    digest = _key(
        "feed-poll:v1",
        source_key,
        _sha256_bytes(raw_feed_payload),
        FEED_PARSER_VERSION,
        NORMALIZER_VERSION,
    )
    return f"feed-poll:v1:{digest}"


def ptt_source_key(*, board: str, aid: str, source_provenance: str, body_hash: str) -> str:
    values = (board.strip(), aid.strip(), source_provenance.strip(), body_hash.strip())
    if not all(values):
        raise ValueError("PTT source-key fields must not be empty")
    return f"ptt-realtime:v1:{values[0]}:{values[1]}:{values[2]}:{values[3]}"


@dataclass(frozen=True)
class ObservationInput:
    platform: str
    external_video_id: str | None
    channel_id: str | None
    subscription_topic: str | None
    source_kind: str
    source_key: str
    source_event_key: str
    event_kind: str
    provider_published_at: str | None
    provider_updated_at: str | None
    observed_at: datetime
    payload_hash: str
    parser_version: str
    normalizer_version: str
    verification_state: str
    reason: str | None
    normalized_fields: Mapping[str, object]
    raw_payload_retained: bool = False
    raw_payload_locator: str | None = None


@dataclass(frozen=True)
class ReceiptInput:
    received_at: datetime
    observed_at: datetime
    transport_kind: str
    receipt_identity: str
    payload_hash: str
    signature_verified: bool | None = None
    headers_hash: str | None = None


class DiscoveryEvidenceStore:
    """Append-only SQLite evidence store with deduplicated facts and receipts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS evidence_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discovery_observations (
                    observation_id INTEGER PRIMARY KEY,
                    observation_key TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    external_video_id TEXT,
                    channel_id TEXT,
                    subscription_topic TEXT,
                    source_kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    source_event_key TEXT NOT NULL,
                    event_kind TEXT NOT NULL CHECK(event_kind IN (
                        'accepted_discovery', 'rejected', 'verification_failure',
                        'missing', 'retraction', 'deletion_tombstone',
                        'metadata_snapshot', 'parse_rejection'
                    )),
                    provider_published_at TEXT,
                    provider_updated_at TEXT,
                    observed_at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    normalizer_version TEXT NOT NULL,
                    verification_state TEXT NOT NULL,
                    reason TEXT,
                    normalized_fields_json TEXT NOT NULL,
                    raw_payload_retained INTEGER NOT NULL CHECK(raw_payload_retained IN (0, 1)),
                    raw_payload_locator TEXT,
                    CHECK((raw_payload_retained = 1 AND raw_payload_locator IS NOT NULL)
                       OR (raw_payload_retained = 0 AND raw_payload_locator IS NULL))
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_observations_subject
                ON discovery_observations(platform, external_video_id, observed_at);
                CREATE INDEX IF NOT EXISTS idx_discovery_observations_source
                ON discovery_observations(source_kind, source_key, observed_at);

                CREATE TABLE IF NOT EXISTS observation_receipts (
                    receipt_id INTEGER PRIMARY KEY,
                    receipt_key TEXT NOT NULL UNIQUE,
                    observation_id INTEGER NOT NULL REFERENCES discovery_observations(observation_id),
                    received_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    transport_kind TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    signature_verified INTEGER CHECK(signature_verified IN (0, 1)),
                    headers_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_observation_receipts_observation
                ON observation_receipts(observation_id, received_at);

                CREATE TABLE IF NOT EXISTS ptt_stream_evidence (
                    evidence_id INTEGER PRIMARY KEY,
                    evidence_key TEXT NOT NULL UNIQUE,
                    observation_id INTEGER NOT NULL UNIQUE REFERENCES discovery_observations(observation_id),
                    board TEXT NOT NULL,
                    aid TEXT NOT NULL,
                    source_provenance TEXT NOT NULL,
                    external_video_id TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    occurrence_ordinal INTEGER NOT NULL CHECK(occurrence_ordinal >= 1),
                    line_number INTEGER NOT NULL CHECK(line_number >= 1),
                    char_offset INTEGER NOT NULL CHECK(char_offset >= 0),
                    original_value TEXT,
                    original_value_hash TEXT NOT NULL,
                    bounded_context TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    extracted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ptt_stream_evidence_article
                ON ptt_stream_evidence(board, aid, body_hash);
                CREATE INDEX IF NOT EXISTS idx_ptt_stream_evidence_video
                ON ptt_stream_evidence(external_video_id);

                CREATE TABLE IF NOT EXISTS source_snapshots (
                    source_kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(source_kind, source_key, snapshot_id)
                );
                """
            )
            existing = conn.execute(
                "SELECT value FROM evidence_metadata WHERE key='schema_version'"
            ).fetchone()
            if existing is not None and existing[0] != str(SCHEMA_VERSION):
                raise ValueError("unsupported discovery evidence schema version")
            conn.execute(
                "INSERT OR IGNORE INTO evidence_metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @staticmethod
    def _assert_compatible(
        *,
        identity: str,
        existing: sqlite3.Row,
        incoming: Mapping[str, object],
        fields: tuple[str, ...],
    ) -> None:
        differences = [field for field in fields if existing[field] != incoming[field]]
        if differences:
            raise EvidenceConflictError(
                f"{identity} conflicts on canonical field(s): {', '.join(differences)}"
            )

    def _record_on_conn(
        self,
        conn: sqlite3.Connection,
        observation: ObservationInput,
        receipt: ReceiptInput | None = None,
    ) -> int:
        if observation.event_kind not in EVENT_KINDS:
            raise ValueError(f"unsupported event_kind: {observation.event_kind}")
        payload_hash = _require_sha256(observation.payload_hash, field="payload_hash")
        normalized_json = _canonical_json(observation.normalized_fields)
        observation_key = _key(
            observation.source_kind,
            observation.source_key,
            observation.source_event_key,
            payload_hash,
            observation.event_kind,
            observation.verification_state,
            observation.parser_version,
            observation.normalizer_version,
            normalized_json,
        )
        incoming = {
            "observation_key": observation_key,
            "platform": observation.platform,
            "external_video_id": observation.external_video_id,
            "channel_id": observation.channel_id,
            "subscription_topic": observation.subscription_topic,
            "source_kind": observation.source_kind,
            "source_key": observation.source_key,
            "source_event_key": observation.source_event_key,
            "event_kind": observation.event_kind,
            "provider_published_at": observation.provider_published_at,
            "provider_updated_at": observation.provider_updated_at,
            "observed_at": _utc(observation.observed_at),
            "payload_hash": payload_hash,
            "parser_version": observation.parser_version,
            "normalizer_version": observation.normalizer_version,
            "verification_state": observation.verification_state,
            "reason": observation.reason,
            "normalized_fields_json": normalized_json,
            "raw_payload_retained": int(observation.raw_payload_retained),
            "raw_payload_locator": observation.raw_payload_locator,
        }
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM discovery_observations WHERE observation_key=?",
            (observation_key,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO discovery_observations(
                    observation_key, platform, external_video_id, channel_id,
                    subscription_topic, source_kind, source_key, source_event_key,
                    event_kind, provider_published_at, provider_updated_at,
                    observed_at, payload_hash, parser_version, normalizer_version,
                    verification_state, reason, normalized_fields_json,
                    raw_payload_retained, raw_payload_locator
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                tuple(incoming[field] for field in incoming),
            )
            row = conn.execute(
                "SELECT * FROM discovery_observations WHERE observation_key=?",
                (observation_key,),
            ).fetchone()
        else:
            canonical_fields = tuple(field for field in incoming if field != "observed_at")
            self._assert_compatible(
                identity=f"observation {observation_key}",
                existing=row,
                incoming=incoming,
                fields=canonical_fields,
            )
        if row is None:
            raise RuntimeError("failed to persist discovery observation")
        observation_id = int(row["observation_id"])
        if receipt is not None:
            receipt_payload_hash = _require_sha256(receipt.payload_hash, field="receipt payload_hash")
            receipt_key = _key(
                observation_key,
                receipt.transport_kind,
                receipt.receipt_identity,
                receipt_payload_hash,
                _utc(receipt.received_at),
            )
            receipt_incoming = {
                "receipt_key": receipt_key,
                "observation_id": observation_id,
                "received_at": _utc(receipt.received_at),
                "observed_at": _utc(receipt.observed_at),
                "transport_kind": receipt.transport_kind,
                "payload_hash": receipt_payload_hash,
                "signature_verified": None if receipt.signature_verified is None else int(receipt.signature_verified),
                "headers_hash": receipt.headers_hash,
            }
            receipt_row = conn.execute(
                "SELECT * FROM observation_receipts WHERE receipt_key=?",
                (receipt_key,),
            ).fetchone()
            if receipt_row is None:
                conn.execute(
                    """
                    INSERT INTO observation_receipts(
                        receipt_key, observation_id, received_at, observed_at,
                        transport_kind, payload_hash, signature_verified, headers_hash
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    tuple(receipt_incoming.values()),
                )
            else:
                self._assert_compatible(
                    identity=f"receipt {receipt_key}",
                    existing=receipt_row,
                    incoming=receipt_incoming,
                    fields=tuple(receipt_incoming),
                )
        return observation_id

    def record(self, observation: ObservationInput, receipt: ReceiptInput | None = None) -> int:
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            return self._record_on_conn(conn, observation, receipt)

    def record_source_snapshot(
        self,
        *,
        source_kind: str,
        source_key: str,
        snapshot_id: str,
        observed_at: datetime,
        payload_hash: str,
        metadata: Mapping[str, object],
    ) -> None:
        payload_hash = _require_sha256(payload_hash, field="snapshot payload_hash")
        incoming = {
            "source_kind": source_kind,
            "source_key": source_key,
            "snapshot_id": snapshot_id,
            "observed_at": _utc(observed_at),
            "payload_hash": payload_hash,
            "metadata_json": _canonical_json(metadata),
        }
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM source_snapshots WHERE source_kind=? AND source_key=? AND snapshot_id=?",
                (source_kind, source_key, snapshot_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO source_snapshots(
                        source_kind, source_key, snapshot_id, observed_at,
                        payload_hash, metadata_json
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    tuple(incoming.values()),
                )
            else:
                self._assert_compatible(
                    identity=f"source snapshot {source_kind}/{source_key}/{snapshot_id}",
                    existing=row,
                    incoming=incoming,
                    fields=tuple(incoming),
                )

    def receipt_summary(self, observation_id: int) -> dict[str, object]:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT MIN(received_at), MAX(received_at), COUNT(*)
                FROM observation_receipts WHERE observation_id=?
                """,
                (observation_id,),
            ).fetchone()
        return {
            "first_received_at": row[0],
            "last_received_at": row[1],
            "delivery_count": int(row[2]),
        }

    def counts(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as conn:
            return {
                "observations": int(conn.execute("SELECT COUNT(*) FROM discovery_observations").fetchone()[0]),
                "receipts": int(conn.execute("SELECT COUNT(*) FROM observation_receipts").fetchone()[0]),
                "ptt_evidence": int(conn.execute("SELECT COUNT(*) FROM ptt_stream_evidence").fetchone()[0]),
                "source_snapshots": int(conn.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0]),
            }

    def observations(self) -> tuple[dict[str, object], ...]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return tuple(dict(row) for row in conn.execute(
                "SELECT * FROM discovery_observations ORDER BY observation_id"
            ))


def _video_fields(video: YoutubeVideo | None) -> dict[str, object]:
    if video is None:
        return {}
    payload = asdict(video)
    # Verification time is delivery/receipt metadata, not part of the provider's
    # canonical video fact. Rechecking an unchanged fact must remain idempotent.
    payload.pop("checked_at", None)
    for key, value in tuple(payload.items()):
        if isinstance(value, datetime):
            payload[key] = _utc(value)
    return payload


def record_websub_event(
    store: DiscoveryEvidenceStore,
    event: ChannelPushEvent,
    *,
    raw_payload: bytes,
    topic: str,
    received_at: datetime,
    observed_at: datetime,
    event_kind: str,
    verification_state: str,
    video: YoutubeVideo | None = None,
    reason: str | None = None,
    signature_verified: bool = True,
    delivery_identity: str | None = None,
) -> int:
    normalized = {"event": asdict(event), "video": _video_fields(video)}
    payload_hash = _sha256_text(_canonical_json(normalized))
    raw_payload_hash = _sha256_bytes(raw_payload)
    source_event_key = f"entry:v1:{event.channel_id}:{event.video_id}:{event.updated or event.published or 'undated'}"
    return store.record(
        ObservationInput(
            platform="youtube",
            external_video_id=event.video_id,
            channel_id=event.channel_id,
            subscription_topic=topic,
            source_kind="websub",
            source_key=websub_source_key(event.channel_id),
            source_event_key=source_event_key,
            event_kind=event_kind,
            provider_published_at=event.published,
            provider_updated_at=event.updated,
            observed_at=observed_at,
            payload_hash=payload_hash,
            parser_version=WEBSUB_PARSER_VERSION,
            normalizer_version=NORMALIZER_VERSION,
            verification_state=verification_state,
            reason=reason,
            normalized_fields=normalized,
        ),
        ReceiptInput(
            received_at=received_at,
            observed_at=observed_at,
            transport_kind="websub_http_post",
            receipt_identity=delivery_identity or f"{topic}:{raw_payload_hash}",
            payload_hash=raw_payload_hash,
            signature_verified=signature_verified,
        ),
    )


def record_feed_event(
    store: DiscoveryEvidenceStore,
    event: ChannelPushEvent,
    *,
    raw_feed_payload: bytes,
    received_at: datetime,
    observed_at: datetime,
    event_kind: str,
    verification_state: str,
    video: YoutubeVideo | None = None,
    reason: str | None = None,
    delivery_identity: str | None = None,
) -> int:
    poll_id = derive_feed_poll_id(channel_id=event.channel_id, raw_feed_payload=raw_feed_payload)
    normalized = {"event": asdict(event), "video": _video_fields(video), "poll_id": poll_id}
    payload_hash = _sha256_text(_canonical_json(normalized))
    raw_payload_hash = _sha256_bytes(raw_feed_payload)
    source_event_key = f"poll:v1:{poll_id}:entry:{event.video_id}:{event.updated or event.published or 'undated'}"
    return store.record(
        ObservationInput(
            platform="youtube",
            external_video_id=event.video_id,
            channel_id=event.channel_id,
            subscription_topic=f"https://www.youtube.com/feeds/videos.xml?channel_id={event.channel_id}",
            source_kind="channel_feed",
            source_key=feed_source_key(event.channel_id),
            source_event_key=source_event_key,
            event_kind=event_kind,
            provider_published_at=event.published,
            provider_updated_at=event.updated,
            observed_at=observed_at,
            payload_hash=payload_hash,
            parser_version=FEED_PARSER_VERSION,
            normalizer_version=NORMALIZER_VERSION,
            verification_state=verification_state,
            reason=reason,
            normalized_fields=normalized,
        ),
        ReceiptInput(
            received_at=received_at,
            observed_at=observed_at,
            transport_kind="channel_feed_poll",
            receipt_identity=delivery_identity or f"{poll_id}:{event.channel_id}:{raw_payload_hash}",
            payload_hash=raw_payload_hash,
        ),
    )


def record_ptt_body(
    store: DiscoveryEvidenceStore,
    *,
    board: str,
    aid: str,
    source_provenance: str,
    body_text: str,
    extracted_at: datetime,
    extractor_version: str = PTT_EXTRACTOR_VERSION,
) -> tuple[int, ...]:
    body_bytes = body_text.encode("utf-8")
    body_hash = _sha256_bytes(body_bytes)
    source_key = ptt_source_key(
        board=board,
        aid=aid,
        source_provenance=source_provenance,
        body_hash=body_hash,
    )
    lines = body_text.splitlines()
    if not extractor_version.strip():
        raise ValueError("extractor_version must not be empty")
    recorded: list[int] = []
    occurrence = 0
    with sqlite3.connect(store.path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        for item in extract_body_urls(body_text):
            if item.video_id is None:
                continue
            occurrence += 1
            context = lines[item.line_number - 1][:500] if item.line_number <= len(lines) else ""
            source_event_key = f"occurrence:v1:{occurrence}:{item.char_offset}:{item.video_id}"
            observation_id = store._record_on_conn(
                conn,
                ObservationInput(
                    platform="youtube",
                    external_video_id=item.video_id,
                    channel_id=None,
                    subscription_topic=None,
                    source_kind="ptt_realtime",
                    source_key=source_key,
                    source_event_key=source_event_key,
                    event_kind="accepted_discovery",
                    provider_published_at=None,
                    provider_updated_at=None,
                    observed_at=extracted_at,
                    payload_hash=body_hash,
                    parser_version=extractor_version,
                    normalizer_version=NORMALIZER_VERSION,
                    verification_state="extracted",
                    reason=None,
                    normalized_fields={
                        "board": board,
                        "aid": aid,
                        "source_provenance": source_provenance,
                        "video_id": item.video_id,
                        "occurrence_ordinal": occurrence,
                        "line_number": item.line_number,
                        "char_offset": item.char_offset,
                        "url": item.url,
                        "context": context,
                    },
                ),
            )
            evidence_key = _key(
                board,
                aid,
                source_provenance,
                body_hash,
                occurrence,
                item.video_id,
                extractor_version,
            )
            evidence_incoming = {
                "evidence_key": evidence_key,
                "observation_id": observation_id,
                "board": board,
                "aid": aid,
                "source_provenance": source_provenance,
                "external_video_id": item.video_id,
                "body_hash": body_hash,
                "occurrence_ordinal": occurrence,
                "line_number": item.line_number,
                "char_offset": item.char_offset,
                "original_value": item.url,
                "original_value_hash": _sha256_text(item.url),
                "bounded_context": context,
                "extractor_version": extractor_version,
                "extracted_at": _utc(extracted_at),
            }
            evidence_row = conn.execute(
                "SELECT * FROM ptt_stream_evidence WHERE evidence_key=?",
                (evidence_key,),
            ).fetchone()
            if evidence_row is None:
                conn.execute(
                    """
                    INSERT INTO ptt_stream_evidence(
                        evidence_key, observation_id, board, aid, source_provenance,
                        external_video_id, body_hash, occurrence_ordinal, line_number,
                        char_offset, original_value, original_value_hash,
                        bounded_context, extractor_version, extracted_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    tuple(evidence_incoming.values()),
                )
            else:
                canonical_fields = tuple(field for field in evidence_incoming if field != "extracted_at")
                store._assert_compatible(
                    identity=f"PTT evidence {evidence_key}",
                    existing=evidence_row,
                    incoming=evidence_incoming,
                    fields=canonical_fields,
                )
            recorded.append(observation_id)
    return tuple(recorded)
