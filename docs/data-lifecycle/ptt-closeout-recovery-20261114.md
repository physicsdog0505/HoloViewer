# PTT daily closeout recovery — 2026-11-14

## Before / after acceptance scenario

Before: a failed previous-day closeout is skipped permanently, its downstream
traceback is reduced to `DailyPttOrchestrationError`, and verified daily assets
do not advance the production monthly manifest.

After: the 07:30 job selects the oldest day without a verified archive receipt,
processes a bounded backlog, records the exact failing stage, and after all
selected days succeed updates the dedicated monthly Static Assets target with
full readback and rollback verification.

## Root cause verified on 2026-11-14

- Target days 2026-11-07, 2026-11-08, 2026-11-11 and 2026-11-12 reached
  `VERIFIED_COMPLETE` finalization but failed before `archive-job.json`.
- Read-only dry runs reproduced the rejection in `r2_archive_export`.
- Bounded repair had re-read an exact five-row page-tail overlap in AIDs
  `1gxm2SDK` and `1gz4WBy0`. The repeated block was collected many hours after
  the original block and then appeared to move source time backwards.
- The archive projection now removes only exact multi-row overlap at a later
  capture-batch boundary. A single repeated comment and same-batch repeated
  sequence are preserved. Genuine later backwards-minute chronology remains a
  hard failure.

## Runtime behavior

- `daily_ptt_scheduler_gate --day YYYY-MM-DD` health-gates an explicit closed
  Taipei day without changing Collector data.
- `daily_ptt_orchestrator` backlog mode scans verified archive receipts from an
  explicit start day through yesterday, oldest first, with a default maximum of
  three days per invocation. It stops on the first failed day.
- Gate and downstream commands use `{day}`. The optional monthly post command
  runs once after all selected days and supports `{day}` and `{month}`.
- Child command failures retain stage and a bounded stderr tail in the JSON
  receipt. `daily_history_runtime` also emits structured JSON for known runtime
  and archive-contract errors.

## Monthly publication boundary

`monthly_archive_pipeline` converts only immutable, readback-verified daily
lifecycle objects into the existing production-reader-compatible
`ptt-r2-archive-v1` object contract.

`monthly_archive_release`:

1. locks the currently published manifest SHA;
2. mirrors and verifies all referenced immutable objects, reusing a local
   verified cache on later runs;
3. builds exact candidate and rollback trees;
4. deploys the candidate only on the explicit `update`/`deploy` command;
5. verifies the candidate manifest and every newly added object remotely;
6. redeploys the locked prior tree if readback is uncertain and reports whether
   rollback readback succeeded.

The production frontend, API Worker, D1, Collector SQLite and Publisher
checkpoints are outside this code path.

## Intended LaunchAgent command shape (not installed by this change)

The existing LaunchAgent must be repointed to a reviewed runtime and use:

```text
python -B -m ptt_offline.daily_ptt_orchestrator
  --mode production
  --state-root <daily-state-root>
  --catchup-start-day 2026-11-01
  --max-days 3
  --gate-command-json '["python","-B","-m","ptt_offline.daily_ptt_scheduler_gate","--daily-config","<config>","--day","{day}"]'
  --downstream-command-json '["python","-B","-m","ptt_offline.daily_history_runtime","run","--config","<config>","--day","{day}"]'
  --post-command-json '["python","-B","-m","ptt_offline.monthly_archive_release","update","--month","{month}","--base-url","https://holoviewer-ptt-static-assets-{month}.singlebagel.workers.dev","--manifest-key","ptt/v1/manifests/static-assets-full-{month}.json","--target","holoviewer-ptt-static-assets-{month}","--state-root","<daily-state-root>","--release-root","<monthly-release-root>"]'
```

This shape preserves the current dedicated November target. A new month still
requires a separately provisioned dedicated target and frontend month mapping;
automatic stable-origin month discovery is a separate public-frontend rollout.

## Production stop conditions

- Do not install this runtime or modify the LaunchAgent until the exact commit
  is reviewed and the existing runtime path is retained as rollback.
- Do not run 2026-11-13 production repair without explicit approval; dry-run
  evidence currently reports two bounded missing ranges.
- Do not deploy the monthly candidate until all intended days have verified
  archive jobs and the active monthly manifest SHA/version is locked.
- No D1 write, Publisher restart, Collector restart, checkpoint reset or
  production SQLite mutation is part of this repair.
