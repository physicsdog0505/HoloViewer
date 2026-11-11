# Issue #47 — production-bound execution preparation (NO OPERATIONS AUTHORIZED)

## Locked identities
- Independent #45 reviewed source base: `149a80361654b06377dbae580e1d8da2e5010cf0`. Latest #47 offline PASS HEAD before this documentation update: `fdd6c885ea146dd47de8157b278f869d3d3d35b4` (workflow `38738844538`, Node 29/29 and Python 49/49). Any subsequent documentation commit needs its own exact-head confirmation; this is not permission to deploy.
- Migration source: `backend/today/d1/0002_today_canonical.sql`
- Pinned migration Git blob SHA-1: `943e3d49f665060a2f0b71c7ffef44185d754244`
- Migration ID: `0002_today_canonical`
- SHA-256 MUST be computed from exact committed migration file bytes, not a pasted or reformatted SQL copy: `shasum -a 256 backend/today/d1/0002_today_canonical.sql`.
- Worker: existing `holoviewer-public-api` with D1 binding `DB -> holoviewer-public-v1`. Do **not** use `cloudflare/wrangler.json`: that deploys **static** Worker `holoviewer-public`, not this API Worker.
- No new staging DB, no separate snapshot service, no second Worker.

## A. Exact-head offline verification
1. `git checkout <reviewed PR HEAD>`; `git rev-parse HEAD` must match reviewed commit.
2. `node --version`: must support `node:sqlite` and WebCrypto; otherwise use a compatible isolated Node environment without modifying production.
3. `node --test backend/today/d1/migrate.test.mjs backend/today/d1/store.test.mjs backend/today/d1/worker-read.test.mjs`
4. `python -B -m unittest -v backend.today.test_today_offline backend.today.test_provider_ingest backend.today.test_today_contract`
5. Fail means fix source on PR #53 and re-run; do not continue to runtime migration.

## B. Read-only production preflight (owner/runtime permission required even for account access)
Do not run until authorized, authenticated and exact worker binding is independently confirmed.
- Inspect the real `holoviewer-public-api` route/entrypoint/bindings; export existing API Worker version, compatibility date, route list, CORS/rate limits, D1 database ID, and a rollback version reference.
- Confirm binding name is exactly `DB`, and database name exactly `holoviewer-public-v1`; reject any other database ID. Inspect current schema and migration ledger before any schema write.
- Wrangler CLI read-only template (requires actual owner-verified account config; not the static Worker config):
  `npx wrangler d1 execute holoviewer-public-v1 --remote --command "SELECT name,type FROM sqlite_master WHERE type IN ('table','index') AND name LIKE 'public_today_%' ORDER BY name;"`
  `npx wrangler d1 execute holoviewer-public-v1 --remote --command "SELECT migration_id,checksum,applied_at FROM public_today_schema_migrations WHERE migration_id='0002_today_canonical';"`
  Note: if ledger table is absent, first inspect `sqlite_master`, do not blindly query it.
- Read-only source-only preflight:
  `git hash-object backend/today/d1/0002_today_canonical.sql` equals pinned blob above;
  `shasum -a 256 backend/today/d1/0002_today_canonical.sql` is recorded in receipt.
- **Important:** running `wrangler d1 execute --remote --file ...` by itself bypasses `migrate.mjs` ledger protocol and MUST NOT be used. Real migration must go via a reviewed runner that executes schema and ledger claim transactionally against the intended `env.DB`, after separate Owner approval.

## C. Approved migration (NOT executed here)
- Owner provides explicit permission for exact reviewed HEAD, migration digest, D1 database ID, account, and rollback plan.
- Recheck no conflicting existing migration ID/checksum.
- Route through reviewed `applyTodayMigration(env.DB,{sql})` adapter with the exact source bytes and transactional D1 batch.
- Postflight: `public_today_schema_migrations` contains exactly one `0002_today_canonical` row matching the SHA-256; canonical/evidence/approved-channels/catalog-meta tables and indexes exist; existing unrelated tables and rows remain unchanged.
- Re-run identical migration through the runner, expect `applied:false`; never re-apply changed migration bytes under same ID. Drift or schema mismatch = ABORT, no cleanup via drop/reseed.

## D. Existing Worker API source mount
The reviewed #47 `api-shell.mjs` reconstructs the owner-supplied legacy API shell and has a #48 PTT injection seam; #68 confirmed combined local router behavior. This is **not evidence of byte identity with the currently deployed Worker**. The actual deployed API entrypoint/revision must still be owner-verified before the production-target diff. **Do not substitute** `cloudflare/wrangler.json` or create another Worker.
- Minimal mount in the **existing** API Worker router:
  `import { handleTodayRead } from '<reviewed #47 module location>';`
  `if (new URL(request.url).pathname === '/v1/catalog/today') return handleTodayRead(request,env);`
- Preserve other routes, existing `DB` binding, rate limits, authentication boundaries, telemetry, and CORS policy. Unauthenticated Today API must be GET-only.
- Version and route diff must receive separate review and Owner runtime authorization before deploy.

## E. Unified hosted read-only canary — #45 authority, NOT authorized

**#45 canonical freeze supersedes the older #47 Today-only three-GET proposal.**
Do not run this in production without explicit owner authorization, confirmed real Worker source/version,
correct `DB -> holoviewer-public-v1` identity and reviewed #47 + #48 artifacts.
Use exactly one quiet observation window, baseline Cloudflare metrics before/after, **no retries**.

1. `GET /health` (0 data queries expected).
2. `GET /v1/catalog/today?day=<Taipei-day>&limit=1` (2 D1 queries expected).
3. `GET /v1/ptt/today?day=<same>&limit=1` (3 D1 queries expected).
4. `GET /v1/ptt/history?day=<same>&limit=1` (3 D1 queries expected).
5. **Only if** step 4 has `has_more=true`, one continuation using exactly the returned opaque token:
   `GET /v1/ptt/history?day=<same>&limit=1&after=<returned-push-id>` (4 D1 queries expected).

**Hard caps (entire unified window, not per path):** HTTP requests <= 5; automatic retries 0;
D1 queries <= 12; attributable Rows Read delta <= 1,000; Rows Written exactly 0;
unexpected route or write SQL 0. A missing migration/schema before approved application is
a *pre-canary blocker*, not permission to write or synthesize rows. Queries/Rows Read must
be measured, not inferred from response size.

Capture exact deployed Worker revision and #47/#48 source SHAs, binding/database identity,
request status/content-type/cache/CORS, public schema/day/freshness/completeness, continuation
equality and advancement, request/query/read/write/retry metric deltas and timestamps.

**Abort:** wrong Worker/D1 identity, unreviewed route, unintended SQL write, nonexpected 5xx,
contract/CORS/OPTIONS/health divergence, duplicated or reordered continuation, >5 requests,
>12 queries, >1,000 Rows Read, any Rows Written, or any retry. Leave both ingestion/Cron and
Publisher disabled; roll back Worker revision before any producer activation. Preserve additive
D1 migrations and evidence; do not DROP/reseed.

The #47 Today reader should still consume no more than the reviewed two queries per
bounded request. This paragraph is offline deployment preparation, **not** a hosted receipt.

## F. Later ingestion activation (NOT authorized)
1. Approve and version authoritative publisher roster manifest, including explicit group and valid channels.
2. Verify writer quota, D1 concurrency ownership, idempotent evidence batch, and replay policy; pre-activate authorized channel membership.
3. Run **one** bounded manual discovery/metadata pass only after separate live YouTube authorization, validate counts/evidence/day scope, then only consider scheduled Cron activation after review.
4. Rollback: disable future writer/Cron first; preserve durable evidence, mark consumer freshness stale/unknown, revert Worker revision via existing deployment history. Never drop/reseed D1 to roll back a source bug.

## G. Unified evidence receipt
```text
PR exact HEAD:
Migration Git blob SHA-1: 943e3d49f665060a2f0b71c7ffef44185d754244
Migration SHA-256:
Migration ID: 0002_today_canonical
API Worker name/version:
D1 binding / database ID / name:
Existing route/entrypoint:
Migration ledger before/after:
Schema objects before/after:
Exact-head Node test / Python test:
Unified canary requests (max 5, conditional fifth):
HTTP statuses / sanitized response:
D1 queries (max 12) / Rows Read (max 1000) / Rows Written (=0) / retries (=0):
Source manifest version and approval:
Decision: PASS | FAIL | ABORT
Owner approval reference:
Rollback version:
```

**No actions above have been performed against production.** This is a source handoff for separate approval.
