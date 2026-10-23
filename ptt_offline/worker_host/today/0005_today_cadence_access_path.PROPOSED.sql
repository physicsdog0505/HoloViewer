-- PROPOSAL ONLY: Issue #47 Today lifecycle cadence access-path indexes.
-- Additive only. Do NOT apply to Production without Owner approval and independent review.
--
-- Purpose:
-- 1) support oldest-first cadence rotation for non-ended rows;
-- 2) support bounded re-verification of recent/incomplete ended rows;
-- 3) make processed WebSub existence probes index-backed by video_id.
CREATE INDEX IF NOT EXISTS public_today_canonical_cadence_active
  ON public_today_canonical(checked_at, video_id)
  WHERE lifecycle_state!='ended';

CREATE INDEX IF NOT EXISTS public_today_canonical_cadence_ended_reverify
  ON public_today_canonical(lifecycle_state, actual_end, checked_at, video_id);

CREATE INDEX IF NOT EXISTS public_today_websub_processed_video
  ON public_today_websub_events(video_id)
  WHERE status='processed';
