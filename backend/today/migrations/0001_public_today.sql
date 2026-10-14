-- PROPOSED, NOT APPLIED. Independent Public Today namespace; no existing tables touched.
-- D1 execute only after dedicated owner-reviewed migration approval.
CREATE TABLE IF NOT EXISTS public_today_streams (
  video_id TEXT PRIMARY KEY NOT NULL,
  publisher_channel_id TEXT NOT NULL,
  title TEXT NOT NULL,
  channel_name TEXT NOT NULL DEFAULT '',
  lifecycle_state TEXT NOT NULL DEFAULT 'unknown'
    CHECK (lifecycle_state IN ('unknown','upcoming','live','ended')),
  observed_at TEXT NOT NULL,
  scheduled_start TEXT,
  actual_start TEXT,
  actual_end TEXT,
  source_label TEXT NOT NULL DEFAULT '',
  source_roster_version TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_today_stream_observed
  ON public_today_streams(observed_at);
CREATE TABLE IF NOT EXISTS public_today_sources (
  video_id TEXT NOT NULL,
  source_channel_id TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ownership_review TEXT NOT NULL DEFAULT 'unverified'
    CHECK (ownership_review IN ('unverified','matched','needs_review','reviewed_valid_cross_channel')),
  PRIMARY KEY(video_id,source_channel_id)
);
CREATE TABLE IF NOT EXISTS public_today_channel_watermarks (
  channel_id TEXT PRIMARY KEY,
  roster_version TEXT NOT NULL,
  last_attempt_at TEXT,
  last_success_at TEXT,
  gap INTEGER NOT NULL DEFAULT 1 CHECK (gap IN (0,1))
);
CREATE TABLE IF NOT EXISTS public_today_runs (
  run_id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  outcome TEXT NOT NULL,
  quota_units INTEGER NOT NULL DEFAULT 0 CHECK (quota_units>=0),
  error_code TEXT
);
