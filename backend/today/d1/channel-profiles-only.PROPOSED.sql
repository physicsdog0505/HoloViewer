-- #47 profile-only additive schema for owner-approved avatar release.
-- Independent of WebSub queue/lease/cursor tables; never rerun existing Today/PTT migrations.
CREATE TABLE IF NOT EXISTS public_today_channel_profiles (
 channel_id TEXT PRIMARY KEY,
 roster_version TEXT NOT NULL,
 channel_title TEXT NOT NULL,
 avatar_url TEXT,
 fetched_at TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='youtube_channels_list')
);
