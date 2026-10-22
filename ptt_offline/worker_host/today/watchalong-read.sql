-- Additive Public Watchalong derived read model.
-- Source is existing stored PTT article bodies parsed offline; never stores full article bodies.
CREATE TABLE IF NOT EXISTS public_watchalong_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  aid TEXT NOT NULL,
  article_title TEXT NOT NULL,
  source_url TEXT NOT NULL,
  article_datetime TEXT NOT NULL,
  day TEXT NOT NULL,
  scheduled_time TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL,
  member_only INTEGER NOT NULL DEFAULT 0 CHECK(member_only IN (0,1)),
  imported_at TEXT NOT NULL,
  source TEXT NOT NULL CHECK(source='ptt_watchalong_parser')
);
CREATE INDEX IF NOT EXISTS public_watchalong_events_day
  ON public_watchalong_events(day, article_datetime DESC, scheduled_time DESC);

CREATE TABLE IF NOT EXISTS public_watchalong_streams (
  event_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL CHECK(ordinal>=0),
  label TEXT NOT NULL,
  video_id TEXT NOT NULL,
  PRIMARY KEY(event_id, ordinal),
  UNIQUE(event_id, video_id),
  FOREIGN KEY(event_id) REFERENCES public_watchalong_events(event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS public_watchalong_streams_video
  ON public_watchalong_streams(video_id, event_id);
