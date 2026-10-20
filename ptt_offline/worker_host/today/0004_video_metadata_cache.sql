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

-- Durable recovery controls: replay suppression and provider-call budget.
CREATE TABLE IF NOT EXISTS public_video_metadata_recovery_replay (
  replay_key TEXT PRIMARY KEY NOT NULL,
  accepted_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_video_metadata_recovery_replay_expiry
  ON public_video_metadata_recovery_replay(expires_at);

CREATE TABLE IF NOT EXISTS public_video_metadata_recovery_budget (
  window_start TEXT PRIMARY KEY NOT NULL,
  calls INTEGER NOT NULL CHECK(calls >= 0),
  updated_at TEXT NOT NULL
);


-- Durable public recovery demand queue. Public reads may register/reuse demand,
-- but provider access is performed only by the bounded server-owned consumer.
CREATE TABLE IF NOT EXISTS public_video_metadata_recovery_demand (
  video_id TEXT PRIMARY KEY NOT NULL,
  priority INTEGER NOT NULL CHECK(priority IN (1,2,3)),
  status TEXT NOT NULL CHECK(status IN ('pending','processing','resolved','not_found')),
  ptt_day TEXT,
  requested_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  next_attempt_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  last_error TEXT
);
CREATE INDEX IF NOT EXISTS public_video_metadata_recovery_demand_ready
  ON public_video_metadata_recovery_demand(status,priority,next_attempt_at,requested_at);


-- Durable admission bound for unauthenticated public recovery demand creation.
-- Provider quota remains separately bounded by public_video_metadata_recovery_budget.
CREATE TABLE IF NOT EXISTS public_video_metadata_recovery_admission_budget (
  window_start TEXT PRIMARY KEY NOT NULL,
  admissions INTEGER NOT NULL CHECK(admissions >= 0),
  updated_at TEXT NOT NULL
);
