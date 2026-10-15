-- Issue #48, durable production-compatible Cloudflare D1 schema v1.
-- Forward-only and idempotent; never drop canonical identity or replay evidence.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS ptt_threads (
    day TEXT NOT NULL,
    aid TEXT NOT NULL,
    source_url TEXT,
    verified_at TEXT,
    PRIMARY KEY (day, aid)
);
CREATE TABLE IF NOT EXISTS ptt_pushes (
    push_id TEXT PRIMARY KEY,
    aid TEXT NOT NULL,
    day TEXT NOT NULL,
    source_line INTEGER NOT NULL CHECK(source_line > 0),
    kind TEXT CHECK(kind IN ('推','噓','→') OR kind IS NULL),
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    floor INTEGER CHECK(floor > 0 OR floor IS NULL),
    source_url TEXT,
    source_priority INTEGER NOT NULL DEFAULT 0,
    source_record_key TEXT,
    ingested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_ptt_pushes_day_order
ON ptt_pushes(day, occurred_at, aid, source_line, push_id);
CREATE INDEX IF NOT EXISTS idx_ptt_pushes_aid_line
ON ptt_pushes(aid, source_line);
CREATE TABLE IF NOT EXISTS ptt_provider_state (
    day TEXT NOT NULL,
    aid TEXT NOT NULL,
    relay_cursor INTEGER NOT NULL DEFAULT 0,
    purged_through_cursor INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    has_gap INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(day, aid)
);
CREATE TABLE IF NOT EXISTS ptt_source_evidence (
    day TEXT NOT NULL,
    aid TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    push_id TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    PRIMARY KEY(day, aid, source_record_key)
);
INSERT OR IGNORE INTO schema_migrations(version,description)
VALUES(1,'canonical push, thread scope, replay and forward repair state');
