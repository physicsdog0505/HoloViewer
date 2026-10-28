# PTT Daily → Monthly Static Archive Integration

Status: **READY_FOR_PRODUCTION_ROLLOUT candidate only**. This change does not mutate Production by itself.

## Root cause

Public VOD History can read the legacy `ptt-r2-archive-v1` monthly manifests, while the 07:30 closeout runtime publishes immutable daily packages with `holoviewer-ptt-daily-static-package-v1`. There was no stable discoverable catalog joining those contracts, so recent dates could silently appear through `/v1/ptt/history` even when Static Archive had not advanced.

The fix is a stable, incremental, verified-complete-only monthly catalog:

`ptt/v1/manifests/monthly/YYYY-MM.json`

A date is Archive COMPLETE only when that catalog contains a COMPLETE entry backed by a verified legacy or daily immutable manifest.

## Source lineage forward-ported

The branch starts from the then-current `origin/main` and forward-ports the reviewed `ptt_offline` runtime subtree from:

- PR #161 / HEAD `88d1dc471caeda4764381aeed776579f377fe6e4`
- PR #162 / HEAD `c99b4318a22d2bcab579b03c1f9353f022c50656`
- PR #163 / HEAD `53ce8ade91078c4e63fa4570468388fad057f795`
- timestamp follow-up `aed78afe9c57dfca991b5f28799c951f8b65b058`

The timestamp follow-up is retained: the first push may share the article URL's minute despite second-level URL precision; later backwards-minute chronology remains fail-closed.

Old GitHub workflow files are **not** forward-ported. Owner-local deployment remains the contract.

## Monthly catalog contract

Schema: `holoviewer-ptt-monthly-catalog-v1`.

Each COMPLETE day stores:

- Taipei day;
- source kind (`legacy-archive-v1` or `daily-package-v1`);
- immutable manifest key and SHA-256;
- daily source hash when applicable;
- push count and partition range for daily packages.

Daily insertion validates:

1. `downstream_authorized=true`;
2. finalization `VERIFIED_COMPLETE` + `archive_ready=true`;
3. archive job/readback verified;
4. manifest SHA identity;
5. every object SHA;
6. push counts;
7. partition range;
8. unique `source_record_key`;
9. authoritative per-thread floor;
10. Asia/Taipei v1 or lifecycle-v2 boundary rules.

Same day + same identity is an idempotent no-op. Same day + conflicting verified identity fails closed.

No historical daily objects are rebuilt just to append a new date.

## Closeout integration and authorization

`daily_history_runtime.py` advances the monthly catalog only after the daily package's remote readback has produced a verified archive job.

The monthly step consumes, but does not produce, the Collector authorization receipt:

- configured `downstream_authorization_path`, or
- default `<state_root>/collector-health/<day>.json`.

Both `health_gate_passed=true` and `downstream_authorized=true` are required. Missing/false authorization returns `HOLD_DOWNSTREAM_NOT_AUTHORIZED` and leaves the monthly catalog unchanged.

This integration contains **no Collector restart, Publisher restart, checkpoint reset, D1 mutation, or repair/watchdog implementation**.

Catalog publication is a second Static Assets deployment after daily readback. The candidate is written atomically; failed or unverified catalog publication restores the prior local catalog and makes a best-effort Static Assets rollback deployment. The previous valid catalog remains the durable baseline.

## Legacy coexistence

Chosen model: **composite monthly catalog**.

For October, the catalog can reference the already-verified legacy monthly manifest for old COMPLETE days and daily manifests for new verified dates. Legacy bytes are not relabeled, migrated, overwritten, or re-uploaded.

`monthly_catalog_seed.py` is a production-inert owner-local seed builder. It requires a verified legacy readback receipt and matching legacy manifest digest. Only legacy days already marked `COMPLETE + finalized=true` are admitted. A PARTIAL/UNKNOWN date is omitted and therefore remains eligible for D1 fallback.

This lets 2026-10-01 through 2026-10-17 remain readable while 2026-10-24 and 2026-10-25 use immutable daily packages.

## Frontend compatibility

The shared browser reader `site/assets/ptt-archive-catalog-core.js` supports both:

- `ptt-r2-archive-v1`
- `holoviewer-ptt-daily-static-package-v1`

Viewer and Watchalong first query the stable monthly catalog. If a published catalog exists but the requested date has no COMPLETE entry, the existing coverage-driven D1 fallback remains active.

Before the stable catalog is rolled out (or when its endpoint is unavailable), the current `pttArchiveMonths` mapping remains as compatibility fallback. The change therefore does not merely repoint `config.js` to the daily Worker.

Integrity behavior remains fail-closed for manifest/object SHA, push count, partition range, and duplicate source identity. VOD window selection, cross-midnight slicing, Taipei day semantics, and existing D1 pagination behavior stay in the page runtime.

## Tests

`ptt_offline.test_monthly_catalog` covers:

- first verified day creates catalog;
- second verified day appends;
- same digest no-op;
- conflicting digest fail closed;
- failed/unverified delivery leaves prior catalog;
- incomplete day rejected;
- legacy + daily coexistence;
- unverified legacy rejection;
- bad SHA / count / range;
- duplicate `source_record_key`;
- Taipei midnight;
- lifecycle-v2 `partition_end`;
- downstream authorization false/true;
- acceptance counts 2026-10-24 = 2294 and 2026-10-25 = 2232.

`test_ptt_archive_catalog_frontend.py` locks the dual-schema reader, page integration, CSP origin, and preservation of D1 fallback.

## D1 and read-budget impact

Steady-state VOD behavior improves D1 usage: a date present as COMPLETE in the monthly catalog is read from Static Archive and does not require D1 history pagination.

Each archived date adds one small monthly-catalog fetch plus the immutable manifest/object reads required for the requested VOD window. The monthly writer updates one stable catalog object; it does not re-upload historical daily payloads.

Dates absent/incomplete in the catalog continue to use D1 exactly as before. D1 schema/data are not changed.

## Production rollout plan

Production mutation remains forbidden until explicit Owner approval.

1. Checkout the reviewed PR merge SHA in a clean Owner-local worktree.
2. Run the PTT/monthly unit tests and Public frontend smoke tests.
3. Obtain/read the accepted legacy October readback receipt and legacy manifest.
4. Build the October composite seed with `ptt_offline.monthly_catalog_seed`; verify it contains the accepted COMPLETE legacy dates and does not promote PARTIAL dates.
5. Stage the seed at `ptt/v1/manifests/monthly/2026-10.json` in the dedicated `holoviewer-ptt-static-assets` static root.
6. Ensure the external Collector-health/finalization gate emits `downstream_authorized=true`; do not add restart logic here.
7. Promote the reviewed daily closeout runtime pointer if required.
8. Owner-local deploy only `holoviewer-ptt-static-assets`; read back the catalog and verify SHA.
9. Deploy the reviewed frontend reader changes with the normal Owner-local frontend release contract.
10. Verify 10/01–10/17 resolve from legacy Static Archive, 10/24 = 2294 and 10/25 = 2232 resolve from daily Static Archive, and an unarchived date resolves through D1 fallback.

No GitHub Actions dispatch is part of rollout.

## Rollback

Frontend rollback: restore the previous frontend release only; archive bytes remain immutable.

Catalog rollback: restore the previously verified monthly catalog bytes and owner-local deploy the dedicated PTT Static Assets target. Daily immutable manifests/objects remain in place and need no deletion.

Runtime rollback: restore the prior reviewed LaunchAgent runtime pointer. Do not reset Publisher checkpoints and do not restart Collector/Publisher as part of this archive rollback.

## Remaining HOLDs before Production

- explicit Owner approval;
- current-main PR review/merge;
- owner-local test receipt on the final merge SHA;
- accepted October legacy readback receipt available to seed the composite catalog;
- external Collector gate receipt for rollout day with `downstream_authorized=true`;
- production catalog SHA/readback receipt generated only during approved rollout.

Until those are satisfied: `PRODUCTION_MUTATION=NO`.
