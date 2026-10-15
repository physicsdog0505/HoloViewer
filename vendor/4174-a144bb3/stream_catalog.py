"""Durable SQLite registry for Hololive livestream metadata.

This database is intentionally separate from the PTT collector database and from
append-only DiscoveryEvidenceStore. Runtime/evidence stores own raw observations;
this registry keeps durable channel/stream identity, current selected projections,
source-presence links, and bounded post-stream workflow state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3


DEFAULT_STREAM_CATALOG_DB = "hololive_stream_catalog.sqlite3"
SCHEMA_VERSION = 1
_METADATA_TABLE = "stream_catalog_metadata"
_REQUIRED_TABLES = {
    _METADATA_TABLE,
    "channels",
    "streams",
    "stream_sources",
    "post_stream_state",
}
_REQUIRED_COLUMNS = {
    _METADATA_TABLE: {"key", "value"},
    "channels": {
        "channel_id",
        "channel_name",
        "avatar_url",
        "branch",
        "generation",
        "default_language",
        "is_active",
        "first_seen_at",
        "last_seen_at",
        "profile_checked_at",
    },
    "streams": {
        "video_id",
        "channel_id",
        "youtube_url",
        "title",
        "scheduled_start",
        "actual_start",
        "actual_end",
        "lifecycle_state",
        "projection_observed_at",
        "first_seen_at",
        "last_seen_at",
        "last_checked_at",
        "is_livestream",
        "is_short",
        "is_public",
        "duration_seconds",
    },
    "stream_sources": {
        "id",
        "video_id",
        "source_type",
        "source_ref",
        "evidence_key",
        "first_seen_at",
        "last_seen_at",
    },
    "post_stream_state": {
        "video_id",
        "transcript_status",
        "transcript_source",
        "transcript_language",
        "transcript_ready_at",
        "transcript_last_attempt_at",
        "transcript_next_attempt_at",
        "transcript_attempt_count",
        "summary_status",
        "summary_ready_at",
        "summary_version",
        "clip_status",
        "clip_ready_at",
        "daily_digest_status",
        "last_error_stage",
        "last_error_code",
        "updated_at",
    },
}


def _utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds")


def _bool_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


class StreamCatalog:
    """Idempotent SQLite store for the durable stream-registry projection.

    Current/mutable stream fields are a selected projection. Callers must supply an
    observation timestamp representing the already-selected authoritative state.
    Older replay/backfill observations are allowed, but cannot replace a newer
    selected projection.
    """

    def __init__(self, path: str | Path = DEFAULT_STREAM_CATALOG_DB) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self._initialize_or_validate_schema()
            self.connection.execute("PRAGMA journal_mode = WAL")
        except Exception:
            self.connection.close()
            raise

    def _user_tables(self) -> set[str]:
        return {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    def _initialize_or_validate_schema(self) -> None:
        user_version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        tables = self._user_tables()
        if not tables and user_version == 0:
            self._create_schema()
            return
        if user_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported stream catalog schema version: {user_version}; "
                f"expected {SCHEMA_VERSION}"
            )
        if _METADATA_TABLE not in tables:
            raise ValueError("stream catalog schema metadata is missing")
        row = self.connection.execute(
            f"SELECT value FROM {_METADATA_TABLE} WHERE key='schema_version'"
        ).fetchone()
        if row is None or str(row[0]) != str(SCHEMA_VERSION):
            raise ValueError("unsupported stream catalog metadata version")
        missing = _REQUIRED_TABLES - tables
        if missing:
            raise ValueError(
                "incomplete stream catalog schema: missing " + ", ".join(sorted(missing))
            )
        for table, required_columns in _REQUIRED_COLUMNS.items():
            present_columns = {
                str(column["name"])
                for column in self.connection.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            missing_columns = required_columns - present_columns
            if missing_columns:
                raise ValueError(
                    "incomplete stream catalog schema: "
                    f"{table} missing columns "
                    + ", ".join(sorted(missing_columns))
                )

    def _create_schema(self) -> None:
        self.connection.executescript(
            f"""
            CREATE TABLE {_METADATA_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE channels (
                channel_id TEXT PRIMARY KEY,
                channel_name TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                branch TEXT NOT NULL DEFAULT '',
                generation TEXT NOT NULL DEFAULT '',
                default_language TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                profile_checked_at TEXT
            );

            CREATE TABLE streams (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT REFERENCES channels(channel_id),
                youtube_url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                scheduled_start TEXT,
                actual_start TEXT,
                actual_end TEXT,
                lifecycle_state TEXT NOT NULL DEFAULT 'unknown'
                    CHECK (lifecycle_state IN (
                        'unknown', 'upcoming', 'live', 'ended', 'missing'
                    )),
                projection_observed_at TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_checked_at TEXT,
                is_livestream INTEGER CHECK (
                    is_livestream IS NULL OR is_livestream IN (0, 1)
                ),
                is_short INTEGER CHECK (
                    is_short IS NULL OR is_short IN (0, 1)
                ),
                is_public INTEGER CHECK (
                    is_public IS NULL OR is_public IN (0, 1)
                ),
                duration_seconds INTEGER CHECK (
                    duration_seconds IS NULL OR duration_seconds >= 0
                )
            );

            CREATE INDEX streams_channel_start
                ON streams(channel_id, scheduled_start);
            CREATE INDEX streams_actual_end
                ON streams(actual_end);
            CREATE INDEX streams_lifecycle
                ON streams(lifecycle_state);

            CREATE TABLE stream_sources (
                id INTEGER PRIMARY KEY,
                video_id TEXT NOT NULL REFERENCES streams(video_id) ON DELETE CASCADE,
                source_type TEXT NOT NULL,
                source_ref TEXT NOT NULL DEFAULT '',
                evidence_key TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(video_id, source_type, source_ref)
            );

            CREATE INDEX stream_sources_type
                ON stream_sources(source_type, last_seen_at);

            CREATE TABLE post_stream_state (
                video_id TEXT PRIMARY KEY REFERENCES streams(video_id) ON DELETE CASCADE,
                transcript_status TEXT NOT NULL DEFAULT 'not_started',
                transcript_source TEXT NOT NULL DEFAULT '',
                transcript_language TEXT NOT NULL DEFAULT '',
                transcript_ready_at TEXT,
                transcript_last_attempt_at TEXT,
                transcript_next_attempt_at TEXT,
                transcript_attempt_count INTEGER NOT NULL DEFAULT 0
                    CHECK (transcript_attempt_count >= 0),
                summary_status TEXT NOT NULL DEFAULT 'not_started',
                summary_ready_at TEXT,
                summary_version TEXT NOT NULL DEFAULT '',
                clip_status TEXT NOT NULL DEFAULT 'not_started',
                clip_ready_at TEXT,
                daily_digest_status TEXT NOT NULL DEFAULT 'not_started',
                last_error_stage TEXT NOT NULL DEFAULT '',
                last_error_code TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            INSERT INTO {_METADATA_TABLE}(key, value)
            VALUES ('schema_version', '{SCHEMA_VERSION}');
            PRAGMA user_version = {SCHEMA_VERSION};
            """
        )
        self.connection.commit()

    def upsert_channel(
        self,
        channel_id: str,
        *,
        channel_name: str = "",
        avatar_url: str = "",
        branch: str = "",
        generation: str = "",
        default_language: str = "",
        is_active: bool | None = None,
        seen_at: datetime | None = None,
        profile_checked_at: datetime | None = None,
    ) -> None:
        """Upsert explicit channel/profile metadata without arrival-order regression.

        Activity uses the same profile_checked_at observation clock as profile
        metadata. A strictly newer activity observation may change is_active;
        older or equal-timestamp replays preserve the stored activity state.
        """

        if not channel_id:
            raise ValueError("channel_id is required")
        observed = _utc_iso(seen_at)
        profile_observed = _utc_iso(profile_checked_at or seen_at)
        activity_supplied = is_active is not None
        inserted_active = 1 if is_active is None else (1 if is_active else 0)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO channels (
                    channel_id, channel_name, avatar_url, branch, generation,
                    default_language, is_active, first_seen_at, last_seen_at,
                    profile_checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    channel_name = CASE
                        WHEN excluded.profile_checked_at >=
                             COALESCE(channels.profile_checked_at, '')
                             AND excluded.channel_name != ''
                            THEN excluded.channel_name
                        ELSE channels.channel_name
                    END,
                    avatar_url = CASE
                        WHEN excluded.profile_checked_at >=
                             COALESCE(channels.profile_checked_at, '')
                             AND excluded.avatar_url != ''
                            THEN excluded.avatar_url
                        ELSE channels.avatar_url
                    END,
                    branch = CASE
                        WHEN excluded.profile_checked_at >=
                             COALESCE(channels.profile_checked_at, '')
                             AND excluded.branch != ''
                            THEN excluded.branch
                        ELSE channels.branch
                    END,
                    generation = CASE
                        WHEN excluded.profile_checked_at >=
                             COALESCE(channels.profile_checked_at, '')
                             AND excluded.generation != ''
                            THEN excluded.generation
                        ELSE channels.generation
                    END,
                    default_language = CASE
                        WHEN excluded.profile_checked_at >=
                             COALESCE(channels.profile_checked_at, '')
                             AND excluded.default_language != ''
                            THEN excluded.default_language
                        ELSE channels.default_language
                    END,
                    is_active = CASE
                        WHEN ?
                             AND excluded.profile_checked_at >
                                 COALESCE(channels.profile_checked_at, '')
                            THEN excluded.is_active
                        ELSE channels.is_active
                    END,
                    first_seen_at = MIN(channels.first_seen_at, excluded.first_seen_at),
                    last_seen_at = MAX(channels.last_seen_at, excluded.last_seen_at),
                    profile_checked_at = CASE
                        WHEN channels.profile_checked_at IS NULL
                            THEN excluded.profile_checked_at
                        WHEN excluded.profile_checked_at IS NULL
                            THEN channels.profile_checked_at
                        ELSE MAX(
                            channels.profile_checked_at,
                            excluded.profile_checked_at
                        )
                    END
                """,
                (
                    channel_id,
                    channel_name,
                    avatar_url,
                    branch,
                    generation,
                    default_language,
                    inserted_active,
                    observed,
                    observed,
                    profile_observed,
                    1 if activity_supplied else 0,
                ),
            )

    def _ensure_channel_placeholder(
        self,
        channel_id: str,
        *,
        seen_at: datetime | None,
    ) -> None:
        """Create identity only; never mutate existing profile/activity state."""

        observed = _utc_iso(seen_at)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO channels (
                    channel_id, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    first_seen_at = MIN(
                        channels.first_seen_at,
                        excluded.first_seen_at
                    ),
                    last_seen_at = MAX(
                        channels.last_seen_at,
                        excluded.last_seen_at
                    )
                """,
                (channel_id, observed, observed),
            )

    def upsert_stream(
        self,
        video_id: str,
        *,
        channel_id: str | None = None,
        youtube_url: str | None = None,
        title: str = "",
        scheduled_start: datetime | None = None,
        actual_start: datetime | None = None,
        actual_end: datetime | None = None,
        lifecycle_state: str = "unknown",
        seen_at: datetime | None = None,
        projection_observed_at: datetime | None = None,
        last_checked_at: datetime | None = None,
        is_livestream: bool | None = None,
        is_short: bool | None = None,
        is_public: bool | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        """Upsert one already-selected stream projection.

        first_seen_at is the earliest observation, while last_seen_at and
        last_checked_at are monotonic maxima. Mutable/current fields only advance
        when projection_observed_at is newer than the stored selected projection,
        so historical replay cannot regress current lifecycle state.
        """

        if not video_id:
            raise ValueError("video_id is required")
        observed = _utc_iso(seen_at)
        projection_at = _utc_iso(projection_observed_at or seen_at)
        if channel_id:
            self._ensure_channel_placeholder(channel_id, seen_at=seen_at)

        values = (
            video_id,
            channel_id,
            youtube_url or f"https://www.youtube.com/watch?v={video_id}",
            title,
            _utc_iso(scheduled_start) if scheduled_start else None,
            _utc_iso(actual_start) if actual_start else None,
            _utc_iso(actual_end) if actual_end else None,
            lifecycle_state or "unknown",
            projection_at,
            observed,
            observed,
            _utc_iso(last_checked_at) if last_checked_at else None,
            _bool_db(is_livestream),
            _bool_db(is_short),
            _bool_db(is_public),
            duration_seconds,
        )
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO streams (
                    video_id, channel_id, youtube_url, title,
                    scheduled_start, actual_start, actual_end, lifecycle_state,
                    projection_observed_at, first_seen_at, last_seen_at,
                    last_checked_at, is_livestream, is_short, is_public,
                    duration_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(excluded.channel_id, streams.channel_id)
                        ELSE streams.channel_id
                    END,
                    youtube_url = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                             AND excluded.youtube_url != ''
                            THEN excluded.youtube_url
                        ELSE streams.youtube_url
                    END,
                    title = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                             AND excluded.title != ''
                            THEN excluded.title
                        ELSE streams.title
                    END,
                    scheduled_start = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(
                                excluded.scheduled_start,
                                streams.scheduled_start
                            )
                        ELSE streams.scheduled_start
                    END,
                    actual_start = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(excluded.actual_start, streams.actual_start)
                        ELSE streams.actual_start
                    END,
                    actual_end = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(excluded.actual_end, streams.actual_end)
                        ELSE streams.actual_end
                    END,
                    lifecycle_state = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                             AND excluded.lifecycle_state != 'unknown'
                            THEN excluded.lifecycle_state
                        ELSE streams.lifecycle_state
                    END,
                    projection_observed_at = MAX(
                        streams.projection_observed_at,
                        excluded.projection_observed_at
                    ),
                    first_seen_at = MIN(streams.first_seen_at, excluded.first_seen_at),
                    last_seen_at = MAX(streams.last_seen_at, excluded.last_seen_at),
                    last_checked_at = CASE
                        WHEN streams.last_checked_at IS NULL
                            THEN excluded.last_checked_at
                        WHEN excluded.last_checked_at IS NULL
                            THEN streams.last_checked_at
                        ELSE MAX(streams.last_checked_at, excluded.last_checked_at)
                    END,
                    is_livestream = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(
                                excluded.is_livestream,
                                streams.is_livestream
                            )
                        ELSE streams.is_livestream
                    END,
                    is_short = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(excluded.is_short, streams.is_short)
                        ELSE streams.is_short
                    END,
                    is_public = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(excluded.is_public, streams.is_public)
                        ELSE streams.is_public
                    END,
                    duration_seconds = CASE
                        WHEN excluded.projection_observed_at >
                             streams.projection_observed_at
                            THEN COALESCE(
                                excluded.duration_seconds,
                                streams.duration_seconds
                            )
                        ELSE streams.duration_seconds
                    END
                """,
                values,
            )
            self.connection.execute(
                """
                INSERT INTO post_stream_state (video_id, updated_at)
                VALUES (?, ?)
                ON CONFLICT(video_id) DO NOTHING
                """,
                (video_id, observed),
            )

    def record_source(
        self,
        video_id: str,
        source_type: str,
        *,
        source_ref: str = "",
        evidence_key: str = "",
        seen_at: datetime | None = None,
    ) -> None:
        """Record source presence and an optional stable evidence/snapshot key.

        Raw WebSub/feed/PTT evidence is owned by DiscoveryEvidenceStore. This table
        is only a non-authoritative registry projection linking a stream to a source
        and, when available, to a stable evidence key.
        """

        if not video_id:
            raise ValueError("video_id is required")
        if not source_type:
            raise ValueError("source_type is required")
        observed = _utc_iso(seen_at)
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO stream_sources (
                    video_id, source_type, source_ref, evidence_key,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, source_type, source_ref) DO UPDATE SET
                    evidence_key = CASE
                        WHEN excluded.last_seen_at > stream_sources.last_seen_at
                             AND excluded.evidence_key != ''
                            THEN excluded.evidence_key
                        ELSE stream_sources.evidence_key
                    END,
                    first_seen_at = MIN(
                        stream_sources.first_seen_at,
                        excluded.first_seen_at
                    ),
                    last_seen_at = MAX(
                        stream_sources.last_seen_at,
                        excluded.last_seen_at
                    )
                """,
                (
                    video_id,
                    source_type,
                    source_ref,
                    evidence_key,
                    observed,
                    observed,
                ),
            )

    def get_stream(self, video_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM streams WHERE video_id = ?",
            (video_id,),
        ).fetchone()

    def get_channel(self, channel_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()

    def get_post_stream_state(self, video_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM post_stream_state WHERE video_id = ?",
            (video_id,),
        ).fetchone()

    def close(self) -> None:
        self.connection.close()
