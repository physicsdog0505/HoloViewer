# Daily PTT History Production Runtime

This branch is the integration seam for the Owner-approved daily closeout:

`07:30 Asia/Taipei -> previous day -> expected AIDs -> Collector coverage -> bounded repair hook -> reverify -> one canonical Taipei-day Static Assets payload -> assets-only deploy -> full HTTP readback -> Admin evidence`.

## Inputs

The runtime requires:

- Collector SQLite path;
- authoritative `holoviewer-ptt-expected-aids-v1` producer;
- optional bounded repair command;
- durable state root;
- one dedicated Workers Static Assets target + public HTTPS base URL.

The expected-AID producer is intentionally external. The reviewed companion is
Hololive-PTT-Viewer PR #422, `daily_expected_aid_export.py`, which uses the
existing public PTT date-search path and performs no PTT login.

The repair command is optional and separately gated by `repair_enabled`. The
checked-in example keeps `repair_enabled=false`, so build-only acceptance stays
read-only even though a repair command path is configured. If repair is disabled
or absent, a proven source gap remains `REPAIR_NEEDED` and Archive is not
attempted. When explicitly enabled, it receives only the exact request JSON
produced by #48:

```json
{
  "day": "YYYY-MM-DD",
  "aid": "...",
  "missing_source_lines": [123,124],
  "repair_ranges": [[123,124]],
  "mode": "bounded-missing-ranges-only"
}
```

The runtime never trusts repair command output as completeness evidence. It
re-reads the Collector SQLite and runs the same #48 classifier again.

## Durable state

Recommended owner path:

`~/Documents/HoloViewer-Historical/daily-ptt-history`

The runtime keeps:

- `finalization/YYYY-MM-DD.json`
- `latest-finalization.json`
- `archive/YYYY-MM-DD/package.json`
- `archive/YYYY-MM-DD/delivery-plan.json`
- `archive/YYYY-MM-DD/archive-job.json`
- `latest-archive-job.json`
- `static-public/` — persistent union of immutable historical assets; newly finalized days are packaged as one `day.json` payload per Taipei day
- `wrangler.daily-history.json`
- `last-static-assets-deploy.log`

Do not delete `static-public/` between deployments. Workers Static Assets
versions are deployed from that complete local asset root. Existing hourly
historical assets are preserved; the daily packaging change applies only to
newly built finalized-day generations unless an explicit offline repack is run.

## Build-only acceptance

Use the example config first with `"deploy": false`.

```bash
cd ~/Downloads/HoloViewer
git fetch origin integration/ptt-daily-history-production-20261021
git switch integration/ptt-daily-history-production-20261021
git reset --hard origin/integration/ptt-daily-history-production-20261021

python3 -B -m unittest -v \
  ptt_offline.test_daily_ptt_finalization \
  ptt_offline.test_archive_job_evidence \
  ptt_offline.test_daily_static_assets_archive \
  ptt_offline.test_daily_history_runtime

cp ptt_offline/fixtures/daily_history_runtime.config.example.json \
  ~/Documents/HoloViewer-Historical/daily-ptt-history.config.json

python3 -B -m ptt_offline.daily_history_runtime run \
  --config ~/Documents/HoloViewer-Historical/daily-ptt-history.config.json
```

Expected build-only result for a fully complete previous day:
`READY_TO_DEPLOY`.

If the expected set is not authoritative, Collector coverage is incomplete, or
repair is still pending, the runtime exits fail-closed with
`NOT_ARCHIVE_READY` and does not invoke Wrangler.

## Production rollout gate

`deploy=false / READY_TO_DEPLOY` is the implementation acceptance gate only. After the Owner performs the one-time reviewed code/config/runtime rollout, routine daily data publication is automatic; it does not require a fresh manual Owner deploy action each day.

For the one-time rollout, enable the required production gates explicitly:

`"repair_enabled": true` (permits bounded Collector repair queue requests)

`"deploy": true` (permits Workers Static Assets deploy)

The runtime then executes only:

`npx wrangler deploy --config <state-root>/wrangler.daily-history.json`

That config contains only an assets directory. It does not bind D1, R2,
secrets, routes, or Worker source.

After rollout, each routine daily run follows:
`fresh VERIFIED_COMPLETE -> day.json package -> package validation -> Static Assets publication -> full HTTP readback -> publish receipt`.

Any UNKNOWN/CONFLICT/finalization mismatch/package validation failure fails closed before publication. The runtime performs full-partition HTTP readback of the exact content-addressed manifest and every object SHA/byte length. A publication with failed readback is not accepted.

An already verified identical manifest is a cheap no-op and does not redeploy.

## 07:30 macOS schedule

Generate the LaunchAgent after the manual Production run is accepted:

```bash
python3 -B -m ptt_offline.daily_history_runtime install-launchd \
  --config ~/Documents/HoloViewer-Historical/daily-ptt-history.config.json \
  --repo-root ~/Downloads/HoloViewer \
  --python "$(command -v python3)"
```

Then the Owner may activate the generated plist with macOS `launchctl` after the one-time rollout review. The generated schedule is exactly 07:30 local machine time. Once activated, routine daily successful `VERIFIED_COMPLETE` data publication is automatic; Owner approval remains required for future code/config/runtime deployment changes, not for each day's data publish.

## Safety boundaries

This integration does not:

- deploy `holoviewer-public-api`;
- write D1;
- enable or write R2;
- reset/restart Collector or Publisher;
- reset Publisher checkpoints;
- infer expected AIDs from Collector absence/presence;
- promote UNKNOWN/PARTIAL source evidence to COMPLETE;
- trust a repair command's success text as completeness;
- silently overwrite immutable historical object identity.

The reviewed private-side companion is Hololive-PTT-Viewer PR #422. It supplies
both the public date-search expected-AID producer and the bounded repair bridge.
Until that exact private-side HEAD is owner-tested and `repair_enabled=true`,
gap days still stop safely at `REPAIR_NEEDED`.

## Canonical one-Taipei-day membership

`day.json` is an **event-day partition**, not a raw exporter bucket dump and not an
`expected_aids` filter.

For a finalized Taipei day, membership is:

1. every included row must occur inside that exact Taipei calendar-day interval;
2. rows from that day's authoritative expected AIDs belong;
3. rows from exactly one **direct predecessor thread** may belong anywhere
   inside the target Taipei day. The direct predecessor is the unexpected
   candidate with the latest authoritative PTT article-post epoch before the
   first expected thread's article-post epoch;
4. this preserves all legal target-day pushes from the previous evening thread,
   including late replies that arrive after the first expected thread starts;
5. older predecessor candidates are outside scope because the direct predecessor
   has superseded them; unexpected threads at/after the first expected-thread
   start are outside the authoritative expected-thread set;
6. an unexpected AID without enough article-post epoch evidence is not silently
   dropped: packaging fails closed.

The resulting payload records a sanitized `membership` audit with expected AIDs,
direct predecessor AID, first expected thread start, cross-midnight carry-in
count, and every excluded AID/count/reason. `silent_drop=false` is explicit.

All included rows still require unique `source_record_key`, authoritative
`floor_quality=per-thread-ordinal`, and stable chronological ordering.


## Fresh-finalization packaging-only acceptance

After #48 has already produced a trusted post-authority finalization, Archive
acceptance must **not** re-run Collector completeness, bounded repair, or
`finalize_day()`.

Use the dedicated packaging-only command:

```bash
python3 -B -m ptt_offline.daily_history_runtime accept-package \
  --config ~/Documents/HoloViewer-Historical/daily-ptt-history.config.json \
  --day 2026-10-21 \
  --expected-contract ~/Documents/HoloViewer-Historical/daily-ptt-history/expected-aids/2026-10-21.json \
  --finalization ~/Documents/HoloViewer-Historical/daily-ptt-history/daily-finalization/2026-10-21.post-authority.json
```

Safety requirements are enforced by code:
- `deploy=false`;
- `repair_enabled=false`;
- finalization schema/digest validated;
- finalization state must be `VERIFIED_COMPLETE`;
- `archive_ready=true`;
- expected contract must be COMPLETE and digest-valid;
- finalization expected-set digest must exactly match the supplied expected contract;
- exact expected AID sets must match;
- no coverage reclassification, no authoritative-tail recalculation, no repair executor;
- Collector SQLite is opened only read-only by the archive exporter;
- output must be exactly one canonical `day.json` package object.

Successful output is `READY_TO_DEPLOY` and includes:
`finalization_digest`, `expected_set_digest`, `expected_aids`,
`packaged_aids`, `direct_predecessor_aid`, `excluded_aids`,
`unexpected_aids`, package/day.json paths, manifest/source hashes, and
`deploy=false`.

For the 2026-10-21 acceptance, the only accepted #48 handoff is:
- expected AIDs: `#1gr_AonI`, `#1gs9Smav`;
- expected-set digest: `437a499a62ea69770c153e235a32b91758376972bc13f2fd6658afa9f6e432d7`;
- fresh finalization digest: `010e9905207555cd5ebac2e66890c404b6386c5bddf0f4b7827752c56d64451e`.

The 2026-10-22 live thread `#1gsKFqhv` is not an expected AID for this
partition and must not survive canonical `day.json` selection.
