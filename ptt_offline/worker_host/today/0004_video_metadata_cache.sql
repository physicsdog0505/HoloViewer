-- Issue #47: additive cache for server-owned YouTube metadata recovery.
CREATE TABLE IF NOT EXISTS public_video_metadata_cache (
  video_id TEXT PRIMARY KEY NOT NULL,
  channel_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  channel_name TEXT NOT NULL DEFAULT '',
  lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('unknown','upcoming','waiting','live','ended')),
  scheduled_start TEXT,
  actual_start TEXT,
  actual_end TEXT,
  managed_channel INTEGER NOT NULL CHECK(managed_channel IN (0,1)),
  source TEXT NOT NULL CHECK(source='youtube-fallback'),
  observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_video_metadata_cache_observed
  ON public_video_metadata_cache(observed_at DESC);
