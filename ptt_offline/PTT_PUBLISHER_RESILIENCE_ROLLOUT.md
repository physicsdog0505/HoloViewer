# #48 Resilient Publisher — Owner-local Production rollout

This runbook is the deployment authority for PR #211. GitHub Actions / CI are
evidence only. They MUST NOT deploy, restart, rollback, or mutate Production.

## Immutable boundaries

This rollout changes only the owner-local Publisher runtime and its launchd
supervision.

Do not:
- run `activate_production_publisher.py --apply`;
- rotate HMAC/time-authority secrets;
- deploy/rebuild the Cloudflare Worker;
- migrate or reset D1;
- restart or replace the Collector;
- recreate Publisher checkpoints;
- run two Publisher writers concurrently.

Production runtime data remains in:

`~/Downloads/Hololive-PTT-Viewer`

and must continue using:
- `hololive_ptt.sqlite3`
- `.ptt-publisher-state/state`
- `.ptt-publisher-state/.publisher-secrets.json`
- `.ptt-publisher-state/minute-metrics.jsonl`

## Candidate

Use an isolated owner-local checkout of PR #211 and pin the exact reviewed HEAD.

Never import Publisher code from the legacy runtime checkout by accident.

## Gate A — source/regression evidence

Required before Owner cutover:
- PR #211 exact HEAD recorded;
- PTT workflow PASS at that exact HEAD;
- Owner-local focused regression PASS;
- Public smoke repository allowlist failure, if unchanged and unrelated, is not
  a PTT runtime deployment gate.

## Gate B — live preflight

Run the supervisor in plan-only mode first:

```bash
python3 -B -m ptt_offline.publisher_supervisor \
  --repo-root "$CANDIDATE" \
  --runtime-root "$HOME/Downloads/Hololive-PTT-Viewer" \
  --expected-head "$EXPECTED_HEAD"
```

Plan mode performs no mutation.

For a live manually-run Publisher:
- pidfile must identify that Publisher;
- writer lock must belong to the same PID;
- no unresolved REMOTE_UNCERTAIN / STOP_MANUAL state may be present at the
  stop-first cutover instant.

If the old Publisher is already dead:
- startup recovery may proceed;
- durable PR #211 pending envelopes are reconciled automatically;
- legacy/invalid uncertain state is quarantined to that source rather than
  crash-looping the whole service.

## Gate C — Owner-local stop-first cutover

Only after explicit Owner authorization:

```bash
python3 -B -m ptt_offline.publisher_supervisor \
  --repo-root "$CANDIDATE" \
  --runtime-root "$HOME/Downloads/Hololive-PTT-Viewer" \
  --expected-head "$EXPECTED_HEAD" \
  --apply
```

The helper:
1. verifies candidate HEAD and runtime paths;
2. verifies current manual PID / writer-lock ownership;
3. refuses to interrupt a live unresolved request;
4. SIGTERMs only the old manual Publisher;
5. waits until the old process is dead and writer lock is free;
6. removes only the stale Publisher pidfile;
7. writes `~/Library/LaunchAgents/com.holodocchi.ptt-publisher.plist`;
8. bootstraps the launchd service in the current GUI user domain;
9. verifies launchd reports running;
10. verifies exactly one writer owns `.single-publisher.lock`.

The service runs `ptt_offline.publisher_service` from the exact candidate
checkout and reuses existing Production state and secrets.

## Post-cutover acceptance

Required:
- `publisher.pid` identifies the launchd-managed process;
- exactly one `.single-publisher.lock` owner;
- new metrics continue;
- normal ACK / NO_NEW_ROWS cycles occur;
- backlog converges if present;
- no unexpected STOP_MANUAL except a deliberately quarantined source;
- durable rolling 6/60 admission file exists after sends;
- durable daily budget telemetry appears;
- Collector PID/runtime is unchanged;
- Worker version is unchanged;
- no secret rotation;
- no D1 schema change.

A transient `REMOTE_UNCERTAIN` is not independently terminal. PR #211 stores
the exact pending batch before dispatch and reconciles it automatically.

## Daily D1 safety semantics

`publisher-daily-budget.json` is a local conservative Publisher-attributable
soft guard. It is not Cloudflare account billing truth.

Defaults:
- modeled D1 writes/day: 25,000
- modeled D1 queries/day: 60,000

The ledger survives process restart and rolls over at Asia/Taipei midnight.

If the ledger is unreadable/corrupt:
- do not reset it;
- Publisher stays alive;
- remote writes are blocked;
- telemetry reports the invalid budget state.

Actual Cloudflare account Rows Read / Rows Written must still be monitored
separately.

## Rollback

Rollback is owner-local and stop-first.

1. `launchctl bootout gui/$(id -u)/com.holodocchi.ptt-publisher`
2. prove launchd service is unloaded;
3. prove no Publisher process remains;
4. prove writer lock is free;
5. preserve all state, secrets, admission, budget, metrics and logs;
6. restart the prior known-good Publisher code/profile against the same runtime
   root and same secrets/state.

Do not delete PR #211 pending envelopes or reset the daily/rolling ledgers merely
to make rollback start faster.

## Deployment authority

Production deploy / rollback is performed only by the Owner on the Owner Mac.
GitHub workflows are passive evidence and must never become deployment authority.
