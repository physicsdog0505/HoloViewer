# Issue #47 — production-bound execution preparation (NO OPERATIONS AUTHORIZED)

## Locked identities
- Reviewed PR #53 code HEAD before this document: `5d03c34b43992fb33681b25c679c472106cf369a`
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
No existing `holoviewer-public-api` source/router is present in this repository's documented `cloudflare/` static site deployment surface. The actual API entrypoint must be located and owner-verified before making a target-file diff. **Do not substitute** `cloudflare/wrangler.json` or create another Worker.
- Minimal mount in the **existing** API Worker router:
  `import { handleTodayRead } from '<reviewed #47 module location>';`
  `if (new URL(request.url).pathname === '/v1/catalog/today') return handleTodayRead(request,env);`
- Preserve other routes, existing `DB` binding, rate limits, authentication boundaries, telemetry, and CORS policy. Unauthenticated Today API must be GET-only.
- Version and route diff must receive separate review and Owner runtime authorization before deploy.

## E. Hosted canary proposal (owner/runtime authorized only)
- First verify Worker health and DB binding **read-only**; never enable ingestion just to test the route.
- Max **3** GET requests total to `/v1/catalog/today?day=<Taipei canonical day>&limit=1`, no automatic retries, no concurrent loops. Inspect `schema_version`, `freshness`, `completeness.gap`, and array form of `streams`; empty but gap=true is acceptable before source ingestion.
- Expected D1 queries per GET: up to 2 reads (catalog_meta + bounded canonical join query); expected rows returned from canonical <= 1 plus <= 1 catalog_meta. Verify actual Cloudflare Rows Read metrics separately because query scans and returned rows are not the same.
- Abort on 5xx, wrong DB binding, contract mismatch, non-GET writes, missing rate-limit controls, unexpected D1 usage, any evidence of wrong account/database, or unexpected exposure of internal cursor/run IDs.

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
Canary requests (max 3):
HTTP statuses / sanitized response:
D1 queries / Rows Read / Rows Written:
Source manifest version and approval:
Decision: PASS | FAIL | ABORT
Owner approval reference:
Rollback version:
```

**No actions above have been performed against production.** This is a source handoff for separate approval.
