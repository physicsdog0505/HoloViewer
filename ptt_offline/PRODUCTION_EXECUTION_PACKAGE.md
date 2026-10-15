# #48 — Production execution package (PREPARED, NOT AUTHORIZED TO RUN)

## Locked architecture

Existing Hololive-PTT-Viewer Collector → canonical owner SQLite → reviewed
#48 Publisher/projection → existing Cloudflare D1 **holoviewer-public-v1**
(binding **DB**) → existing **holoviewer-public-api** → Public / 8788.

Never create another D1, Collector, Worker, snapshot backend or staging writer.
Old `holoviewer-ptt-relay` and `holoviewer-ptt-live-v2` are NOT targets.

## A. Freeze migration artifact and prove compatibility (offline only)

From an exact PR #55 checkout:

```sh
git rev-parse HEAD
python3 -B -m ptt_offline.migration_preflight
shasum -a 256 ptt_offline/d1_migrations/0001_canonical_ptt.sql
python3 -B -m unittest -v ptt_offline.test_public_today_contract ptt_offline.test_consumer_boundary ptt_offline.test_consumer_paging ptt_offline.test_public_consumer_envelope ptt_offline.test_d1_publisher ptt_offline.test_d1_provider
node --experimental-default-type=module --test ptt_offline/test_d1_worker_freshness.mjs
```

Record actual SHA256, byte length, exact git HEAD and test receipt. A checksum
computed at checkout is NOT an immutable freeze until compared against the
reviewed owner-approved value. No previous-HEAD test claim is transferable.

The schema is a **proposed** migration, not proof of coexistence with current
live D1. A preflight must verify names and columns, existing ledger/version,
indexes and D1 schema before attempting application.

Read-only remote inspection examples (DO NOT EXECUTE before owner runtime gate):
```sh
npx wrangler d1 execute holoviewer-public-v1 --remote --command "SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name;"
npx wrangler d1 execute holoviewer-public-v1 --remote --command "SELECT name,sql FROM sqlite_master WHERE type='index' ORDER BY name;"
npx wrangler d1 execute holoviewer-public-v1 --remote --command "SELECT version,description FROM public_ptt_schema_migrations ORDER BY version;"
```
The final ledger SELECT is valid only after table existence has been confirmed.

Owner-only migration command template (NOT EXECUTED):
```sh
npx wrangler d1 execute holoviewer-public-v1 --remote --file ptt_offline/d1_migrations/0001_canonical_ptt.sql
```

After authorization and execution, assert the six tables:
`ptt_threads`, `ptt_pushes`, `ptt_source_evidence`,
`ptt_provider_state`, `ptt_gap_repairs`,
`public_ptt_schema_migrations`. Check version=1 and required columns
including nullable floor, canonical push primary key, and gap closure marker.
For a previously applied version, use a new forward migration; do NOT
drop/recreate or silently rerun an incompatible historical schema.

## B. Canonical existing Worker route mount

Integration requires source of the **existing** live `holoviewer-public-api`
fetch/router. Current #48 branch provides the importable
`handlePttPublicRead(request,env)` in `ptt_offline/d1_worker_routes.js`.
Neighbor #47 exposes `handleTodayRead(request,env)` in
`backend/today/d1/worker-read.mjs`.

Minimal source-only dispatch template, to be inserted in the existing router
AFTER identifying its actual file (do not create a second Worker):

```js
// import {handlePttPublicRead} from '<resolved existing-bundle path>';
if (url.pathname === '/v1/ptt/today' ||
    url.pathname === '/v1/ptt/history') {
  return handlePttPublicRead(request, env); // existing env.DB
}
```

**BLOCKED: exact deployed router entrypoint and import path unverified.**
No guessed filename is an approved production mount. Do not edit live Worker
configuration or deploy based on this template.

## C. Publisher activation and bounded first batch

Source mapping must be verified against **existing** canonical
Hololive-PTT-Viewer SQLite schema, not inferred. Record the owner-approved
local DB path and table/column map separately; this runbook does not read it.
The code currently exposes `publish_batch` and `publish_provider_state`
functions but **no reviewed executable Collector→SQLite→D1 Publisher CLI**.
Do NOT invent a command or claim Publisher activation is executable.

Before authorizing an activation implement/review: one exclusive publisher
instance/lock, exact canonical read query, transform, batch send, checkpoint
receipt persisted atomically, replay/dedup, stop signal, no nested retry loops,
and bounded first synthetic/approved-data batch. A canonical row identity
conflict must abort rather than duplicate records. Persist genuine AID/day
state; never synthesize relay cursors.

Stop and rollback: disable writer/route, preserve committed D1 evidence,
capture final checkpoint and query counts. Default rollback is **stop +
forward repair**, not drop/reseed or mass DELETE.

## D. Mandatory first-window canary budgets (proposed caps)

These are local policy ceilings for **one opt-in canary**; the owner must
approve them before any account mutation. Measure categories separately.

| Quantity | Proposed hard cap |
|---|---:|
| Worker HTTP requests | 8 |
| D1 SQL statements/queries | 30 |
| Rows Read | 1,000 |
| Rows Written | 20 |
| Synthetic or approved canonical pushes | 5 |
| Writer process count | 1 |
| Automatic retries after 403/409/429/5xx | 0 |
| Additional automatic run after first canary | 0 |

Abort immediately on any exceeded ceiling, unverified D1 binding, noncanonical
push identity, 403/409/429/5xx, inconsistent write ACK/read-back, unexpected
duplicate, gap/freshness misreport, or accounting unavailable. Do not conflate
**Worker requests**, **D1 queries**, **Rows Read**, and **Rows Written**.
For D1, inspect returned query metadata and Cloudflare dashboard/account
metrics; do not treat SQL statement count as a substitute for rows read/written.

Prefer **read-only connectivity first**. An optional single bounded synthetic
write/read-back requires a separate explicit owner authorization and permanent
non-destructive evidence retention or reviewed cleanup plan.

## E. Receipt template

```json
{
  "status": "NOT_RUN",
  "git_head": null,
  "migration_sha256": null,
  "migration_version": 1,
  "worker_name": "holoviewer-public-api",
  "worker_version": null,
  "binding": "DB",
  "database_name": "holoviewer-public-v1",
  "database_id": null,
  "source_kind": "synthetic_or_explicitly_approved",
  "source_identity": null,
  "publisher_version": null,
  "write_ack": null,
  "http_get_status": null,
  "http_get_body_checksum": null,
  "remote_sql_identity_count": null,
  "worker_http_requests": null,
  "d1_query_count": null,
  "d1_rows_read": null,
  "d1_rows_written": null,
  "abort_reason": null
}
```

Mark **PASS** only when every intended layer has receipts matching the
exact same data identity and time window; otherwise FAIL/ABORT/NOT_RUN.

## Execution boundary

Do not apply remote migration, read private SQLite without permission, start
Publisher, deploy Worker, change secrets, merge or cut over.
This package records commands **without running** any cloud mutation.
