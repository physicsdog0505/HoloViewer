-- Additive production schema for Today discovery parity only.
-- Existing Today/PTT/profile schemas are not rerun.
CREATE TABLE IF NOT EXISTS public_today_websub_events (
 event_hash TEXT PRIMARY KEY NOT NULL,
 channel_id TEXT NOT NULL,
 video_id TEXT,
 roster_version TEXT NOT NULL,
 received_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 processed_at TEXT,
 last_error TEXT,
 claim_token TEXT,
 claim_until TEXT
);
CREATE INDEX IF NOT EXISTS public_today_websub_pending
 ON public_today_websub_events(status,received_at,event_hash);
CREATE INDEX IF NOT EXISTS public_today_websub_claims
 ON public_today_websub_events(status,claim_until,received_at);

CREATE TABLE IF NOT EXISTS public_today_reconcile_cursor(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 roster_version TEXT NOT NULL,
 next_index INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
