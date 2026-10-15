-- One-time idempotent cleanup for #96 feed-discovery pollution.
-- Remove only canonical rows created after discovery rollout that:
-- 1) came from a processed discovery event,
-- 2) have no livestream timing evidence at all,
-- 3) remain lifecycle unknown.
DELETE FROM public_today_canonical
WHERE video_id IN (
  SELECT e.video_id
  FROM public_today_websub_events e
  WHERE e.status='processed' AND e.video_id IS NOT NULL
)
AND lifecycle_state='unknown'
AND scheduled_start IS NULL
AND actual_start IS NULL
AND actual_end IS NULL
AND lifecycle_observed_at>='2026-10-15T22:22:00Z';
