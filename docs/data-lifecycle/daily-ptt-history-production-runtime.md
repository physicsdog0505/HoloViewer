# Daily PTT History Production Runtime

This branch is the integration seam for the Owner-approved daily closeout:

`07:30 Asia/Taipei -> previous day -> expected AIDs -> Collector coverage -> bounded repair hook -> reverify -> immutable Static Assets package -> assets-only deploy -> full HTTP readback -> Admin evidence`.

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
- `static-public/` — persistent union of immutable historical assets
- `wrangler.daily-history.json`
- `last-static-assets-deploy.log`

Do not delete `static-public/` between deployments. Workers Static Assets
versions are deployed from that complete local asset root.

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

## Production deployment gate

Only after Owner-local build-only acceptance, enable the two mutation gates explicitly:

`"repair_enabled": true` (permits bounded Collector repair queue requests)

`"deploy": true` (permits Workers Static Assets deploy)

The runtime then executes only:

`npx wrangler deploy --config <state-root>/wrangler.daily-history.json`

That config contains only an assets directory. It does not bind D1, R2,
secrets, routes, or Worker source.

After deploy, the runtime performs full-partition HTTP readback of the exact
content-addressed manifest and every object SHA/byte length. A deploy with
failed readback is not accepted.

An already verified identical manifest is a cheap no-op and does not redeploy.

## 07:30 macOS schedule

Generate the LaunchAgent after the manual Production run is accepted:

```bash
python3 -B -m ptt_offline.daily_history_runtime install-launchd \
  --config ~/Documents/HoloViewer-Historical/daily-ptt-history.config.json \
  --repo-root ~/Downloads/HoloViewer \
  --python "$(command -v python3)"
```

Then the Owner may activate the generated plist with macOS `launchctl` after
review. The generated schedule is exactly 07:30 local machine time.

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
