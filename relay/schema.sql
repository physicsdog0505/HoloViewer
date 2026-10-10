CREATE TABLE IF NOT EXISTS ptt_pushes (
  cursor INTEGER PRIMARY KEY AUTOINCREMENT,
  push_id TEXT NOT NULL UNIQUE,
  aid TEXT NOT NULL,
  article_url TEXT NOT NULL,
  source_line INTEGER NOT NULL,
  floor INTEGER,
  kind TEXT NOT NULL,
  author TEXT NOT NULL,
  content TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  producer_id TEXT NOT NULL,
  published_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ptt_pushes_aid_cursor
ON ptt_pushes(aid, cursor);

-- Highest purged global cursor per article (AID). Persistent across subsequent trims.
CREATE TABLE IF NOT EXISTS ptt_retention_watermark (
  aid TEXT PRIMARY KEY,
  purged_through_cursor INTEGER NOT NULL
);

-- Purged source-line high-water. Old IDs absent from the retained table are
-- rejected (HTTP 409), not silently reinserted or falsely acknowledged.
-- Per-article entries are capped; reaching the cap fails closed at purge.
CREATE TABLE IF NOT EXISTS ptt_purged_source_floor (
  aid TEXT PRIMARY KEY,
  source_line INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS ptt_floor_capacity_guard
BEFORE INSERT ON ptt_purged_source_floor
WHEN (SELECT COUNT(*) FROM ptt_purged_source_floor) >= 100000
BEGIN
  SELECT RAISE(ABORT, 'purged source floor capacity reached');
END;

-- Two bounded UTC rate windows; AFTER INSERT only, so INSERT OR IGNORE
-- conflicts cannot consume a mutation allowance. Both write and budget
-- mutations roll back with the D1 batch on limit exceed.
CREATE TABLE IF NOT EXISTS ptt_write_rate (
  window_kind TEXT NOT NULL CHECK (window_kind IN ('minute', 'hour')),
  window_key TEXT NOT NULL,
  inserted_pushes INTEGER NOT NULL,
  PRIMARY KEY (window_kind, window_key)
);
CREATE TRIGGER IF NOT EXISTS ptt_insert_rate_guard
AFTER INSERT ON ptt_pushes
BEGIN
  INSERT INTO ptt_write_rate(window_kind, window_key, inserted_pushes)
  VALUES('minute', strftime('%Y-%m-%dT%H:%M', 'now'), 1)
  ON CONFLICT(window_kind, window_key) DO UPDATE SET inserted_pushes=inserted_pushes+1;
  SELECT CASE WHEN (SELECT inserted_pushes FROM ptt_write_rate
    WHERE window_kind='minute' AND window_key=strftime('%Y-%m-%dT%H:%M', 'now')) > 240
    THEN RAISE(ABORT, 'minute insert budget exceeded') END;

  INSERT INTO ptt_write_rate(window_kind, window_key, inserted_pushes)
  VALUES('hour', strftime('%Y-%m-%dT%H', 'now'), 1)
  ON CONFLICT(window_kind, window_key) DO UPDATE SET inserted_pushes=inserted_pushes+1;
  SELECT CASE WHEN (SELECT inserted_pushes FROM ptt_write_rate
    WHERE window_kind='hour' AND window_key=strftime('%Y-%m-%dT%H', 'now')) > 2000
    THEN RAISE(ABORT, 'hour insert budget exceeded') END;
END;
