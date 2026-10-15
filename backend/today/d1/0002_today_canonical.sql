-- Issue #47: forward-only additive canonical Today migration. NEVER apply without Owner runtime approval.
-- 0001 remains the historical baseline. Do not drop, rename or reseed any table.
CREATE TABLE IF NOT EXISTS public_today_schema_migrations (
  migration_id TEXT PRIMARY KEY NOT NULL,
  checksum TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_today_canonical (
  video_id TEXT PRIMARY KEY NOT NULL,
  publisher_channel_id TEXT NOT NULL,
  roster_version TEXT NOT NULL,
  channel_group TEXT NOT NULL CHECK(channel_group IN ('hololive','holostars','mekpark','other')),
  title TEXT NOT NULL,
  channel_name TEXT NOT NULL DEFAULT '',
  lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN ('unknown','upcoming','live','ended')),
  lifecycle_observed_at TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  scheduled_start TEXT,
  actual_start TEXT,
  actual_end TEXT,
  source_label TEXT NOT NULL,
  source_checksum TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_today_canonical_state
  ON public_today_canonical(lifecycle_state, lifecycle_observed_at DESC);
CREATE TABLE IF NOT EXISTS public_today_evidence (
  video_id TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  source_label TEXT NOT NULL,
  checksum TEXT NOT NULL,
  publisher_channel_id TEXT NOT NULL,
  roster_version TEXT NOT NULL,
  channel_group TEXT NOT NULL,
  lifecycle_state TEXT NOT NULL,
  scheduled_start TEXT,
  actual_start TEXT,
  actual_end TEXT,
  title TEXT NOT NULL,
  channel_name TEXT NOT NULL,
  PRIMARY KEY (video_id, observed_at, source_label)
);
CREATE INDEX IF NOT EXISTS public_today_evidence_by_video
  ON public_today_evidence(video_id, observed_at DESC);
CREATE TABLE IF NOT EXISTS public_today_catalog_meta (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  roster_version TEXT NOT NULL,
  last_success_at TEXT,
  expected_channels INTEGER NOT NULL CHECK(expected_channels>=0),
  scanned_channels INTEGER NOT NULL CHECK(scanned_channels>=0),
  gap INTEGER NOT NULL DEFAULT 1 CHECK(gap IN (0,1)),
  checkpoint TEXT
);

-- Current-authority channel allowlist; membership is separate from video observation roster_version.
CREATE TABLE IF NOT EXISTS public_today_approved_channels (
  channel_id TEXT PRIMARY KEY NOT NULL,
  roster_version TEXT NOT NULL,
  activated_at TEXT NOT NULL,
  channel_group TEXT NOT NULL CHECK(channel_group IN ('hololive','holostars','mekpark','other'))
);
CREATE INDEX IF NOT EXISTS public_today_approved_version ON public_today_approved_channels(roster_version);
