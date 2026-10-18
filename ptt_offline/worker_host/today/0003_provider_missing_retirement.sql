-- Issue #47: bounded provider-missing retirement state.
-- Additive only. Never infer ended or synthesize lifecycle timestamps from omission.
CREATE TABLE IF NOT EXISTS public_today_provider_misses (
  video_id TEXT PRIMARY KEY NOT NULL,
  first_missing_at TEXT NOT NULL,
  last_missing_at TEXT NOT NULL,
  miss_count INTEGER NOT NULL CHECK(miss_count>=1)
);
CREATE INDEX IF NOT EXISTS public_today_provider_misses_last
  ON public_today_provider_misses(last_missing_at);
