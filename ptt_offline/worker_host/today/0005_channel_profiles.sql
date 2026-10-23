-- Issue #47: canonical channel/member profile authority.
-- Additive only. Apply before deploying source that relies on this projection.
CREATE TABLE IF NOT EXISTS public_channel_profiles (
  channel_id TEXT PRIMARY KEY NOT NULL,
  channel_name TEXT,
  display_name TEXT,
  avatar_url TEXT,
  channel_group TEXT CHECK(channel_group IN ('hololive','holostars','mekpark','other')),
  member_accent TEXT,
  member_accent_dual TEXT,
  support_mode TEXT NOT NULL DEFAULT 'neutral' CHECK(support_mode IN ('neutral','solid','dual_color')),
  support_color_source TEXT,
  profile_revision TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS public_channel_profiles_group
  ON public_channel_profiles(channel_group, updated_at DESC);
CREATE INDEX IF NOT EXISTS public_channel_profiles_updated
  ON public_channel_profiles(updated_at DESC);
