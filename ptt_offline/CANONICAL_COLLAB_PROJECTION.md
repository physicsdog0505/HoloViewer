# Canonical Collab projection — Public handoff

Issue: #190  
Producer: physicsdog0505/Hololive-PTT-Viewer#432  
Consumer: physicsdog0505/HoloViewer#192

## Architecture

```
8501 collab_event_store
  -> effective_event() owner review / POV exclusions
  -> collab_public_projection_export.py
  -> public-collab-projection-v1 JSON
  -> collab_projection_import.py
  -> reviewed SQL
  -> public_collab_events + public_collab_projection_meta
  -> /v1/collab/live | /history | /events/:id
```

The Public Worker no longer owns Collab truth. It must not recompute a replacement
event with `detectCollabCandidates()` when canonical projection is unavailable.

## Projection keys

- `live`: current live/Today-facing publication metadata and freshness.
- `history:YYYY-MM-DD:YYYY-MM-DD`: bounded historical publication metadata.

History imports must never overwrite the `live` freshness receipt.

## Artifact integrity

The producer emits:
- schema_version `public-collab-projection-v1`
- projection_key
- source_revision `sha256:<64 hex>`
- generated_at
- bounded source range
- detection version / materialization receipt
- source/effective event counts
- owner-effective events

The importer recomputes the content digest from:
- projection_key
- source range
- detection version
- complete event rows

Any payload mutation, identity mismatch, duplicate/invalid video id, rejected event,
count mismatch, invalid timestamp, or range over 31 days fails closed before SQL is emitted.

## Public API compatibility

The D1 payload stores canonical event JSON. The Worker adapter preserves the
existing Public consumer shape:
- event_id / event_key / label / confidence
- candidate
- streams[].video_id
- streams[].channel_id / channel_name
- lifecycle_state / start_at / actual_start / actual_end
- avatar_url
- sync.available / basis / master_video_id / master_start
- streams[].sync_offset_ms

Additive fields include review_status, source_revision, published_at,
event_date, event_start_at/end_at, participant_count and pov_count.

## Freshness

`/v1/collab/live` reads only metadata key `live`.

Optional runtime variable:
`COLLAB_PROJECTION_MAX_AGE_SECONDS`

- valid positive value: stale is computed and returned.
- unset/invalid: freshness is UNKNOWN and response is marked degraded.
- missing projection metadata/table: fail closed with 503.
- no fallback to Worker-local detector.

History/detail are durable canonical reads and do not depend on the live receipt.

## Owner-local offline acceptance

No cloud mutation:

```bash
set -euo pipefail

PTT="$HOME/Downloads/Hololive-PTT-Viewer"
PUBLIC="$HOME/Downloads/HoloViewer"
STORE="/tmp/holoviewer-428-acceptance/collab-events-2026-10-22.sqlite3"
ART="/tmp/public-collab-projection.json"
SQL="/tmp/public-collab-projection.sql"

cd "$PTT"
git fetch origin issue428/public-collab-projection-export
git worktree remove --force /tmp/hv432 2>/dev/null || true
git worktree add --detach /tmp/hv432 origin/issue428/public-collab-projection-export

cd /tmp/hv432
python3 -B -m unittest -v   test_collab_event_data   test_collab_event_store   test_collab_public_projection_export

python3 -B collab_public_projection_export.py   --store "$STORE"   --projection-key live   --start 2026-10-22   --end 2026-10-23   --output "$ART"

cd "$PUBLIC"
git fetch origin issue190/canonical-collab-projection
git worktree remove --force /tmp/hv192 2>/dev/null || true
git worktree add --detach /tmp/hv192 origin/issue190/canonical-collab-projection

cd /tmp/hv192
python3 -B -m unittest -v ptt_offline.test_collab_projection_import
node --test ptt_offline/worker_host/today/experience-read.test.mjs   ptt_offline/worker_host/today/api-shell.test.mjs

python3 -B ptt_offline/collab_projection_import.py   --input "$ART"   --output "$SQL"

grep -q 'holoserver-hide-and-seek:5680e7ec7c29074a' "$SQL"
! grep -q 'shared-topic:7Aq266GeNx8' "$SQL"
```

This gate writes only /tmp artifacts and detached worktrees.

## Production gate — HOLD until #45 review + Owner approval

Required sequence:
1. accept exact #432 and #192 HEADs;
2. apply only `0006_canonical_collab_projection.PROPOSED.sql` to the intended D1;
3. generate a fresh bounded artifact from the accepted 8501 store;
4. validate artifact and review generated SQL;
5. Owner executes the SQL against `holoviewer-public-v1`;
6. read back projection row/meta and counts;
7. deploy the reviewed API Worker source using the existing Owner-only procedure and `--keep-vars`;
8. verify /health and Collab routes;
9. verify canonical event identity/membership and absence of replacement shared-topic event.

Do not use GitHub Actions/CI for deploy.

## Rollback

API rollback:
- restore the previously accepted Worker version.

Data rollback:
- canonical projection tables are additive and isolated.
- reverting the Worker makes them unused; do not delete them during incident rollback.
- if a bad bounded publication was imported, restore the previously captured rows/meta
  for that same projection range/key only.

No Today/PTT/Watchalong tables are part of this projection.
