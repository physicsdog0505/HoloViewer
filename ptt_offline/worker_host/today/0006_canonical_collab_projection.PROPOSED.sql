-- Issue #190: additive canonical Collab projection for the existing Public API.
-- SOURCE/OFFLINE ONLY. Do not apply to Production without #45 review + Owner authorization.
--
-- Public must consume the owner-reviewed 8501 Collab Event Store projection rather
-- than re-running an independent detector in the Worker.

CREATE TABLE IF NOT EXISTS public_collab_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  event_key TEXT NOT NULL,
  label TEXT NOT NULL,
  confidence TEXT NOT NULL,
  event_date TEXT NOT NULL,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  review_status TEXT NOT NULL
    CHECK (review_status IN ('candidate','approved','needs_review','rejected')),
  payload_json TEXT NOT NULL,
  live_scope INTEGER NOT NULL DEFAULT 0 CHECK (live_scope IN (0,1)),
  is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0,1)),
  source_revision TEXT NOT NULL,
  published_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS public_collab_events_live
  ON public_collab_events(is_current,live_scope,start_at DESC);

CREATE INDEX IF NOT EXISTS public_collab_events_history
  ON public_collab_events(event_date,is_current,start_at DESC);

CREATE TABLE IF NOT EXISTS public_collab_projection_meta (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  source_revision TEXT NOT NULL,
  published_at TEXT NOT NULL,
  source_event_count INTEGER NOT NULL,
  effective_event_count INTEGER NOT NULL
);
