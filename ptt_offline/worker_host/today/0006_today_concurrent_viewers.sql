-- Issue #515: additive ephemeral live concurrent-viewer projection.
-- Owner-local migration only. No historical backfill and no lifecycle authority change.
ALTER TABLE public_today_canonical ADD COLUMN concurrent_viewers INTEGER
  CHECK (concurrent_viewers IS NULL OR concurrent_viewers > 0);
