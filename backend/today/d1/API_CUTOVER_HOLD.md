# Existing API Worker canonical Today cutover — HOLD before independent approval

Candidate: `backend/today/d1/api-worker-entry.mjs`, configuration: `backend/today/d1/wrangler.api-candidate.json`.
Target is **existing** `holoviewer-public-api` only; DB binding `DB` pins existing `holoviewer-public-v1` UUID `64e1a0ee-1455-4377-9640-3922e8f4d061`. No migrations, new services, PTT ingestion, cron, or database reset.
**Never rerun #47 Today migration**: production schema and checksum ledger already verified.

### Before deploying (read-only)
1. Export the *actual currently deployed* Dashboard Worker JavaScript and active full version ID, deployments, variables/bindings/route/environment from Cloudflare dashboard. Current revision prefix `ba249e94` alone is not a rollback identifier. Audit the export against candidate for health, videos, history, Today, error envelope, CORS, cache and other routes. If any unaccounted route or live variable exists, HOLD, do not replace Worker.
2. Decide whether Public's `PUBLIC_API` service binding invokes with an Origin header. Production `ALLOWED_ORIGIN` was absent; this candidate denies browser requests carrying Origin unless the exact public frontend origin is supplied. Changing variables is independently approval-gated; config deliberately does not overwrite it. A same-origin Public service binding request without Origin passes.
3. Confirm canonical Today reader schema `public-consumer-v1` is accepted by the *deployed* frontend, not simply tests against fixtures.
4. Capture current Worker full rollback version and same D1 binding identity. Ensure real YouTube ingestion/approved roster is separately reviewed: **an empty D1 returns empty streams even after this API deploy**.

### Candidate build-only probe (no production write)
```sh
npx wrangler deploy --dry-run --outdir /tmp/holoviewer-public-api-candidate --config backend/today/d1/wrangler.api-candidate.json
```
Inspect emitted module and config; compare exact source export and confirm there are no extra Worker routes, vars, migrations, write handlers, or hidden secret changes.

### Explicitly Owner-gated deploy (DO NOT execute yet)
Only after independent #45 review of exact generated artifact and separate Owner approval for **existing API Worker deployment and any CORS configuration change**, run:
```sh
npx wrangler deploy --config backend/today/d1/wrangler.api-candidate.json
```
This is a future command, **not an authorization**. Wrangler deploy may modify Worker bindings/config or omit existing dashboard settings. If actual Dashboard config is not reproduced and approved exactly, block the deploy. Use version rollback on failure, not schema rollback/D1 DROP.

### After approved deployment, read-only acceptance
```sh
curl -i https://holoviewer-public-api.singlebagel.workers.dev/health
curl -i 'https://holoviewer-public-api.singlebagel.workers.dev/v1/history?day=2026-10-15&limit=1&offset=0'
curl -i 'https://holoviewer-public-api.singlebagel.workers.dev/v1/catalog/today?day=2026-10-15'
```
Require status 200, unchanged health/history contracts, Today `schema_version: public-consumer-v1`, stable Public service binding and cross-origin behavior. Do not interpret zero Today streams as genuine no-live-stream evidence: a controlled, genuine ingestion producer + approved roster + real D1 read receipt are needed.
