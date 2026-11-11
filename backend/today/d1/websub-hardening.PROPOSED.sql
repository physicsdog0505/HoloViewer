-- NOT APPLIED. Owner-gated additive follow-up to existing PROPOSED queue/lease tables.
ALTER TABLE public_today_websub_events ADD COLUMN claim_token TEXT;
ALTER TABLE public_today_websub_events ADD COLUMN claim_until TEXT;
CREATE INDEX IF NOT EXISTS public_today_websub_claims ON public_today_websub_events(status,claim_until,received_at);
CREATE TABLE IF NOT EXISTS public_today_reconcile_cursor(
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 roster_version TEXT NOT NULL,
 next_index INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_today_channel_profiles(
 channel_id TEXT PRIMARY KEY,
 roster_version TEXT NOT NULL,
 channel_title TEXT NOT NULL,
 avatar_url TEXT,
 fetched_at TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='youtube_channels_list')
);
