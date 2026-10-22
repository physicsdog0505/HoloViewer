# Owner-local 07:30 PTT archive rollout packet

Status: **READY FOR REVIEW ONLY — DO NOT INSTALL/LOAD YET**

Reviewed source:
- #163 orchestration/runtime HEAD: `483aacf52b0796178dd95b4473e1a6ed92a905ee`
- accepted #48 gate source: `248455cc3fdf1ce75dcd5b9125b7f0ad7251c406`
- current loaded scheduler label: `com.holoviewer.ptt-history-closeout`
- current loaded WorkingDirectory: `~/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-gate-248455c`
- production config: `~/Documents/HoloViewer-Historical/daily-ptt-history.config.json`
- interpreter: `/opt/homebrew/bin/python3`
- schedule: daily 07:30 local time
- rollout mode: `production`

## 1. Immutable rollout snapshot

Proposed snapshot path:

```text
~/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-0730-483aacf
```

Build it from the reviewed #163 HEAD. The gate entrypoint and health classifier compatibility seam are now part of the #163 branch. Overlay only the two accepted #48 runtime modules that are still external to this branch:

```bash
set -euo pipefail

REPO="$HOME/Downloads/HoloViewer"
RUNTIME="$HOME/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-0730-483aacf"
ARCHIVE_SHA="483aacf52b0796178dd95b4473e1a6ed92a905ee"
GATE_SHA="248455cc3fdf1ce75dcd5b9125b7f0ad7251c406"

rm -rf "$RUNTIME"
mkdir -p "$RUNTIME"

git -C "$REPO" archive "$ARCHIVE_SHA" | tar -x -C "$RUNTIME"

for path in   ptt_offline/daily_ptt_scheduler_gate.py   ptt_offline/collector_controlled_recovery.py   ptt_offline/collector_runtime_health.py
do
  git -C "$REPO" show "$GATE_SHA:$path" > "$RUNTIME/$path"
done
```

Do **not** overlay the older #48 `daily_ptt_finalization.py`. The reviewed #163 HEAD contains the accepted newer finalization/runtime implementation.

The 07:30 gate no longer imports `classify_collector_health` from finalization. It imports the additive compatibility seam:
`ptt_offline.collector_health_contract.classify_collector_health`.

That module contains only the previously reviewed #48 health normalization contract and no completeness/finalization logic.

Snapshot provenance to verify before rollout:

```bash
test "$(git -C "$REPO" rev-parse "$ARCHIVE_SHA")" = "$ARCHIVE_SHA"
test "$(git -C "$REPO" rev-parse "$GATE_SHA")" = "$GATE_SHA"

cd "$RUNTIME"
/opt/homebrew/bin/python3 -B -m unittest -v   ptt_offline.test_daily_ptt_orchestrator   ptt_offline.test_daily_history_runtime   ptt_offline.test_daily_static_assets_archive
```

## 2. Exact LaunchAgent wiring

Proposed `ProgramArguments`:

```text
/opt/homebrew/bin/python3
-B
-m
ptt_offline.daily_ptt_orchestrator
--mode
production
--gate-command-json
["/opt/homebrew/bin/python3","-B","-m","ptt_offline.daily_ptt_scheduler_gate","--daily-config","/Users/hsuhsunshun/Documents/HoloViewer-Historical/daily-ptt-history.config.json"]
--downstream-command-json
["/opt/homebrew/bin/python3","-B","-m","ptt_offline.daily_history_runtime","run","--config","/Users/hsuhsunshun/Documents/HoloViewer-Historical/daily-ptt-history.config.json"]
```

Proposed WorkingDirectory:

```text
/Users/hsuhsunshun/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-0730-483aacf
```

Schedule:

```text
StartCalendarInterval = Hour 7 / Minute 30
RunAtLoad = false
```

The explicit `--mode production` is mandatory. In this mode, orchestration success accepts only:
- `VERIFIED_COMPLETE_PUBLISHED`
- `ALREADY_VERIFIED`

`READY_TO_DEPLOY` is fail-closed in Production mode.

## 3. Production config gate

Config path:

```text
/Users/hsuhsunshun/Documents/HoloViewer-Historical/daily-ptt-history.config.json
```

Before rollout, verify:

```bash
python3 - <<'PY'
import json, pathlib
p=pathlib.Path.home()/"Documents/HoloViewer-Historical/daily-ptt-history.config.json"
x=json.load(open(p))
print("CONFIG=",p)
print("deploy=",x.get("deploy"))
print("repair_enabled=",x.get("repair_enabled"))
print("collector_source=",x.get("collector_source"))
print("state_root=",x.get("state_root"))
assert x.get("deploy") is True
assert x.get("repair_enabled") is True
PY
```

Accepted steady-state Production values:
- `deploy=true`
- `repair_enabled=true`

## 4. Current scheduler backup and rollback target

Current loaded identity:
- label: `com.holoviewer.ptt-history-closeout`
- current WorkingDirectory: `~/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-gate-248455c`
- current module: `ptt_offline.daily_ptt_scheduler_gate`

Exact backup path to create before replacement:

```text
~/Documents/HoloViewer-Historical/launchagent-backups/com.holoviewer.ptt-history-closeout.pre-483aacf.plist
```

Backup command:

```bash
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.holoviewer.ptt-history-closeout.plist"
BACKUP="$HOME/Documents/HoloViewer-Historical/launchagent-backups/com.holoviewer.ptt-history-closeout.pre-483aacf.plist"
mkdir -p "$(dirname "$BACKUP")"
cp -p "$PLIST" "$BACKUP"
cmp "$PLIST" "$BACKUP"
```

## 5. One-time Owner rollout commands

These commands are **Owner-only** and are not to be executed by source review.

Prepare a replacement plist at a temporary path first, validate it, then replace only this scheduler.

```bash
set -euo pipefail

LABEL="com.holoviewer.ptt-history-closeout"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BACKUP="$HOME/Documents/HoloViewer-Historical/launchagent-backups/$LABEL.pre-483aacf.plist"
RUNTIME="$HOME/Documents/HoloViewer-Historical/runtime/HoloViewer-ptt-0730-483aacf"
CFG="$HOME/Documents/HoloViewer-Historical/daily-ptt-history.config.json"
PY="/opt/homebrew/bin/python3"
TMP="/tmp/$LABEL.plist"

"$PY" - "$TMP" "$RUNTIME" "$CFG" <<'PY'
import plistlib,sys
out,runtime,cfg=sys.argv[1:4]
body={
  "Label":"com.holoviewer.ptt-history-closeout",
  "ProgramArguments":[
    "/opt/homebrew/bin/python3","-B","-m","ptt_offline.daily_ptt_orchestrator",
    "--mode","production",
    "--gate-command-json",
    '["/opt/homebrew/bin/python3","-B","-m","ptt_offline.daily_ptt_scheduler_gate","--daily-config","%s"]' % cfg,
    "--downstream-command-json",
    '["/opt/homebrew/bin/python3","-B","-m","ptt_offline.daily_history_runtime","run","--config","%s"]' % cfg,
  ],
  "WorkingDirectory":runtime,
  "StartCalendarInterval":{"Hour":7,"Minute":30},
  "RunAtLoad":False,
  "StandardOutPath":str(__import__("pathlib").Path.home()/"Library/Logs/com.holoviewer.ptt-history-closeout.out.log"),
  "StandardErrorPath":str(__import__("pathlib").Path.home()/"Library/Logs/com.holoviewer.ptt-history-closeout.err.log"),
}
open(out,"wb").write(plistlib.dumps(body,fmt=plistlib.FMT_XML,sort_keys=True))
PY

plutil -lint "$TMP"
plutil -p "$TMP"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
cp "$TMP" "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl print "gui/$(id -u)/$LABEL"
```

This replaces only the daily archive scheduler. It must not restart Collector or touch Publisher.

## 6. Post-rollout acceptance

Do not wait for the next morning to prove wiring. Trigger the loaded scheduler once manually:

```bash
launchctl kickstart -k "gui/$(id -u)/com.holoviewer.ptt-history-closeout"
```

Then inspect:

```bash
tail -n 200 "$HOME/Library/Logs/com.holoviewer.ptt-history-closeout.out.log"
tail -n 200 "$HOME/Library/Logs/com.holoviewer.ptt-history-closeout.err.log"
launchctl print "gui/$(id -u)/com.holoviewer.ptt-history-closeout"
```

Acceptance requires the orchestrator receipt to prove:
- `mode=production`
- `health_gate_passed=true`
- gate day is canonical
- downstream day equals gate day
- `downstream_invoked=true`
- terminal downstream status is exactly:
  - `VERIFIED_COMPLETE_PUBLISHED`, or
  - `ALREADY_VERIFIED`
- overall `status=SUCCEEDED`

A `READY_TO_DEPLOY` result is a Production failure and must trigger rollback investigation.

## 7. Rollback

If rollout acceptance fails:

```bash
set -euo pipefail
LABEL="com.holoviewer.ptt-history-closeout"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BACKUP="$HOME/Documents/HoloViewer-Historical/launchagent-backups/$LABEL.pre-483aacf.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
cp "$BACKUP" "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl print "gui/$(id -u)/$LABEL"
```

Rollback restores only the prior scheduler plist. It does not roll back or mutate archived Static Assets data.

## 8. #430 compatibility invariant

Current #48 gate resolution is:

```text
daily-history config
→ collector_source
→ collector_root = parent(collector_source)
→ read_collector_health(collector_root)
→ managed health/state evidence
```

Therefore the orchestrator itself does not hard-code a development checkout path. The current Collector authority location is resolved indirectly through the production daily-history config.

When #430 moves Collector runtime/state to the canonical managed location, #430 cutover must include a bounded revalidation before Runtime is declared complete:

1. update/verify `collector_source` in the Production daily-history config points at the post-cutover canonical Collector DB/state root;
2. run the #48 health gate from the reviewed 07:30 runtime;
3. verify it resolves the managed Collector identity, current live AID/frontier, heartbeat/refresh health and startup/recovery state from the new canonical location;
4. verify the gate day is still correct;
5. run the orchestrator in Production mode;
6. require same-day downstream receipt and `VERIFIED_COMPLETE_PUBLISHED` or `ALREADY_VERIFIED`;
7. verify no second Collector process/lifecycle owner was created.

No additional completeness classifier is authorized; #48 remains the integrity authority.

## 9. Explicit exclusions

This rollout packet does not authorize:
- Collector restart as part of scheduler replacement;
- Publisher mutation/restart/checkpoint reset;
- D1 schema/data mutation;
- new completeness logic;
- GitHub Actions/CI as Production authority;
- replacing any scheduler other than `com.holoviewer.ptt-history-closeout`.
