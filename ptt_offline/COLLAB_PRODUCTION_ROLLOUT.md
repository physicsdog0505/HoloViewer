# PR #197 Production rollout packet

Status: REVIEWED SOURCE COMPOSITION / PRODUCTION MUTATION HOLD

Release candidate:
- PR #197
- execution must pin the exact HEAD explicitly approved by #45
- do not reuse an earlier review receipt after the PR HEAD moves
- verify with `git rev-parse HEAD` immediately before any Owner-local mutation

Production baseline / rollback:
- Worker: `holoviewer-public-api`
- known-good version: `df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96`
- D1 binding: `DB -> holoviewer-public-v1`
- D1 database id: `64e1a0ee-1455-4377-9640-3922e8f4d061`
- cron: `* * * * *`
- deploy policy: Owner-local only, preserve vars/secrets with `--keep-vars`

This packet does not authorize Production mutation.

## Gate A — exact source pin

The Owner worktree must resolve exactly to the PR #197 HEAD named in the latest
#45 Production mutation approval. Any mismatch, later branch movement, or dirty
worktree is STOP. Source-composition review receipts for older HEADs are not
deployment authorization for a newer HEAD.

## Gate B — active config preservation

Do not invent a Wrangler config.

Owner read-only capture commands:

```sh
set -euo pipefail

WORKER="holoviewer-public-api"
BASELINE_VERSION="df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
OUT="/tmp/hv197-readonly"
rm -rf "$OUT"
mkdir -p "$OUT"

npx wrangler --version | tee "$OUT/wrangler-version.txt"
npx wrangler whoami --json > "$OUT/whoami.json"
npx wrangler deployments status --name "$WORKER" --json > "$OUT/deployments-status.json"
npx wrangler deployments list --name "$WORKER" --json > "$OUT/deployments-list.json"
npx wrangler versions view "$BASELINE_VERSION" --name "$WORKER" --json > "$OUT/baseline-version.json"
npx wrangler d1 info "$DB_ID" --json > "$OUT/d1-info-before.json"

echo "READ_ONLY_CAPTURE=$OUT"
echo "PRODUCTION_MUTATION=NO"
```

These commands inspect Worker/D1 metadata only. They do not upload a version,
change traffic, mutate D1, or alter triggers.

The capture must prove the active deployment still includes #62 at 100% before
any mutation. If it does not, STOP and return to #45.

Use the current Owner-confirmed full API Worker config or reconstruct it from the
active Cloudflare Worker settings before mutation.

Required preserved properties:
- name = `holoviewer-public-api`
- entrypoint = reviewed `ptt_offline/worker_host/index.mjs`
- D1 binding `DB` points to `holoviewer-public-v1`
- D1 id is `64e1a0ee-1455-4377-9640-3922e8f4d061`
- cron remains `* * * * *`
- compatibility date/settings match active #62
- Dashboard-managed vars/secrets, including `ALLOWED_ORIGIN`, remain preserved
- PTT publisher flags must not be silently enabled
- Watchalong/WebSub/Today settings must not be removed

The checked-in static `cloudflare/wrangler.json` is NOT the API Worker config.

Run `ptt_offline/worker_host/build_owner.mjs` against the confirmed API config
and require a dry-run receipt before any deploy.

## Gate C — disposable/local D1-compatible exercise

Use a local/disposable SQLite/D1-compatible target only.

1. apply
   `ptt_offline/worker_host/today/0006_canonical_collab_projection.PROPOSED.sql`
2. validate one `public-collab-projection-v1` artifact
3. render import SQL
4. apply the SQL twice
5. require:
   - target canonical event exists exactly once
   - projection meta exists exactly once
   - replay is idempotent
   - prior-day live event exits `live_scope` on next live projection
   - canonical history row stays current
   - history backfill cannot clear live membership
   - live/history/detail reads return canonical event id
   - no legacy replacement `shared-topic:7Aq266GeNx8`

## Gate D — projected Production mutation size

Schema migration is additive:
- 2 tables
- 3 indexes
- no destructive DDL
- no existing Today/PTT/Watchalong table mutation

For an initial live artifact with N events, generated data SQL contains:
- 1 BEGIN
- 1 indexed current-live membership UPDATE
- N event UPSERT statements
- 1 projection-meta UPSERT
- 1 COMMIT

Logical SQL statements = N + 4 including transaction markers, or N + 2 DML
statements excluding BEGIN/COMMIT.

Expected event-row writes are bounded by:
- at most current live rows changed by the live-scope clear
- plus at most N event upserts
- plus 1 meta upsert

Actual Cloudflare D1 Rows Written is not inferred from statement count and must
be observed from Cloudflare after the Owner-controlled mutation.

For history artifact with N events:
- 1 bounded indexed non-live retirement UPDATE
- N event UPSERTs
- 1 projection-meta UPSERT
- same transaction markers

## Gate E — D1 observation windows / STOP conditions

Capture Cloudflare D1 dashboard values immediately before mutation:
- Rows Read
- Rows Written
- total queries if shown
- timestamp

After schema/import and again after Worker deploy, capture at:
- +5 minutes
- +15 minutes
- +30 minutes

STOP / rollback Worker to #62 immediately if any occurs:
- unexpected 5xx or route regression
- Today / PTT / WebSub / Watchalong regression
- Collab endpoint no longer returns canonical projection contract
- legacy Worker-local shared-topic replacement reappears
- D1 Rows Written shows an unexplained sustained slope attributable to this release
- D1 Rows Read shows an unexplained sustained step-change outside request-volume change
- cron/bindings/vars differ from preflight
- Publisher/Collector process state changes unexpectedly

Conservative rollout alarm thresholds for this feature:
- Collab live/history GET path must not create D1 writes
- one initial projection publication must remain bounded to the inspected artifact
- if observed Rows Written increase materially exceeds the inspected mutation's
  bounded event count plus index amplification, STOP and investigate before retry
- if Rows Read slope after deploy is >2x the immediately preceding comparable
  request window without >2x request traffic, STOP and rollback Worker
- any repeated automatic publication loop is forbidden in this release

These are operational STOP rules, not claims about Cloudflare billing counters.

## Gate F — pre-deploy shared Worker regression

Immediately before Owner mutation, exact reviewed HEAD must pass:
- PTT workflow / equivalent local suite
- Today cadence
- WebSub callback + scheduled processing/renewal
- Watchalong mount
- CORS allow/deny
- canonical Collab live/history/detail
- cross-day live replacement
- #48 private writer 1/10/25 constant-three verification reads
- Public smoke

If HEAD changes, prior receipts are stale.

## Gate G — mutation order

Only after #45 approves this packet:

1. capture active #62 config/version/D1 metrics
2. run full config dry-run with existing confirmed config
3. apply additive Collab schema to `holoviewer-public-v1`
4. generate + inspect one bounded live projection artifact
5. render SQL and record exact N / statement count
6. Owner applies that import SQL
7. read back D1 rows/meta
8. capture immediate D1 metrics
9. Owner deploys exact #197 Worker with the accepted full config and `--keep-vars`
10. verify /health, Today, History, PTT, WebSub, Watchalong, Collab
11. observe +5/+15/+30 minute D1 windows
12. only then close the Production parity gate

No GitHub Actions deployment.

## Rollback

Immutable Worker rollback target:
`df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96`

Owner-local immutable rollback command:

```sh
npx wrangler rollback df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96 \
  --name holoviewer-public-api \
  --message "rollback PR197 canonical-collab release to known-good #62"
```

This command is **not** part of preflight and must not be run unless rollback is
actually required/authorized.

Rollback the Worker only; additive Collab tables may remain unused.
Do not drop tables during incident rollback.

Do not restart Collector or Publisher.
Do not rotate secrets.
Do not alter frontend.

If imported Collab data itself is bad, restore only the previously captured
Collab projection rows/meta for the affected projection key/range. Do not touch
unrelated D1 tables.
