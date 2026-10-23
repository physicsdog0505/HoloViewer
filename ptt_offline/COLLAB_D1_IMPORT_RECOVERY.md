# PR #197 — D1 import recovery, review-only (2026-10-23)

## Actual Production state
The Owner-local remote attempt applied **only the additive schema**. The SHA-pinned original artifact SQL failed at `BEGIN TRANSACTION` with the D1 transaction API error. A subsequent remote READ-ONLY check confirms:
- `public_collab_events` and `public_collab_projection_meta` exist; all three expected indexes exist.
- event rows = 0; target = 0; legacy = 0; projection metadata rows = 0.
- Worker #62 `df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96` remains at 100%.
- rolling 24h counters at readback: Rows Read 1,050,590; Rows Written 63,203. These are **not** isolated per-operation metrics.

**Do not replay schema or the original 5-statement SQL. Do not deploy a Worker.**

## Root cause
`collab_projection_import.render_sql()` always produces `BEGIN TRANSACTION;`, one membership update, one event UPSERT, one projection-meta UPSERT, `COMMIT;`. The prior disposable `sqlite3.executescript` rehearsal proves SQLite behavior, **not** remote Wrangler D1 import compatibility. Remote `wrangler d1 execute --remote --file` rejected the transaction control statement before adding event/meta rows.

## Candidate and unchanged semantics
The new offline-only `ptt_offline/collab_import_recovery_candidate.py`:
1. requires the unchanged exact artifact SHA and original authorized SQL SHA;
2. validates source revision, unique target event, live projection and live_scope=false;
3. proves byte-for-byte equality with the current canonical renderer;
4. removes only the exact leading `BEGIN TRANSACTION;` and trailing `COMMIT;`;
5. emits only the original **three DML statements**, maintaining their order and bytes;
6. prints the new candidate SHA for reviewer comparison.

**This generated SQL is not yet approved to run remotely.** The script makes no Cloudflare calls and performs no Production mutation.

## Critical atomicity gate
The candidate DML-only `wrangler d1 execute --remote --file` upload cannot be assumed all-or-nothing. The first statement can clear old live membership before event/meta UPSERT if a later statement fails. An existing SQLite rehearsal in a local explicit transaction does not prove remote atomicity.

Before any write, #45 must choose and explicitly authorize an execution mode:
- **Preferred**: validated D1 `batch()` in a separately reviewed Owner-local execution path, proven against a disposable D1 target and with the exact three prepared statements in a single batch, **without deploying or modifying the active shared Worker**. Verify the path can actually bind the intended D1 and its atomicity.
- **Alternative, higher risk**: explicit #45 acceptance of the DML-only Wrangler importer with partial-failure/readback/repair plan. Do not infer this permission from the earlier SHA authorization.

In either case: approve a new exact SQL hash + its execution method; assert Production target empty/readback and #62 at 100% immediately before any new mutation; require immediate remote readback and +5-minute counters. The prior permission for `94d106...` **does not** cover the transformed DML.

## Local test requirements
Use the actual Owner-local frozen artifact + SQL to run the converter in offline mode; verify output SHA, 3 statements, identical event payload, idempotent replay and cross-day replacement on disposable SQLite. Separately validate the **chosen remote executor** on disposable Cloudflare D1 before new Production approval. Do not claim remote compatibility/atomicity solely from Python sqlite3 testing.

## Current gate
`SCHEMA=APPLIED | EVENT=0 | META=0 | WORKER=#62/100% | IMPORT=HOLD | DEPLOY=HOLD`
