-- PROPOSAL ONLY: Cloudflare D1 durable Today WebSub event queue.
-- Forward-only additive migration; Owner approval required before application.
CREATE TABLE IF NOT EXISTS public_today_websub_events (
 event_hash TEXT PRIMARY KEY NOT NULL,
 channel_id TEXT NOT NULL,
 video_id TEXT,
 roster_version TEXT NOT NULL,
 received_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5),
 processed_at TEXT,
 last_error TEXT
);
CREATE INDEX IF NOT EXISTS public_today_websub_pending
 ON public_today_websub_events(status,received_at,event_hash);
