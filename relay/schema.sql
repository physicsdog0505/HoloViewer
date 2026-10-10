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
