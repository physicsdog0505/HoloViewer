# #68 — Production read-only preflight checklist (OWNER EXECUTION ONLY)

This checklist prepares evidence for the first live Cloudflare preflight. It does **not**
authorize a deployment, configuration change, D1 migration/write, Publisher/Cron,
secret change, merge, or cutover. #68 does not execute these live checks without the
owner-controlled production context.

## Frozen offline references

- #68 candidate source: `fcdac4bc905756a75343efdd1c7f91e0f5824cb4` or a later documentation-only exact-head PASS.
- Accepted 4174 product: `a144bb378a8bdd772faa867d608c1e7491253883`.
- #47 existing API shell: `149a80361654b06377dbae580e1d8da2e5010cf0`.
- #48 reviewed PTT mount source: `b96d0902a504bc26019efd693a1b3586cfb3d3d2`.
- Repository Public Worker identity: `holoviewer-public`.
- Canonical API Worker: `holoviewer-public-api`.
- Canonical D1 database: `holoviewer-public-v1`.
- Final pre-check offline workflow before this document: `38741312102` — SUCCESS.

## Phase A — read-only identity capture

Owner captures, without changing anything:

1. Current deployed revision/version of `holoviewer-public`.
2. Current deployed revision/version of `holoviewer-public-api`.
3. Current route/custom-domain/zone mapping for both Workers.
4. Current Public-host bindings and variables.
   - Expected invariant: no D1/KV binding on `holoviewer-public`.
5. Current API-Worker bindings and variables.
   - Expected invariant: binding `DB` targets `holoviewer-public-v1`.
   - Record the current `ALLOWED_ORIGIN` value without committing it if it is treated as sensitive.
6. Current Worker compatibility dates/flags and security/CSP response headers.
7. Current production deployment rollback target/revision before any later mutation.

Do not paste API tokens, account secrets, or secret values into GitHub evidence.

## Phase B — compare live identity against reviewed proposal

PASS only if all are true:

- live Public Worker is the expected existing `holoviewer-public`;
- live canonical API Worker is the expected existing `holoviewer-public-api`;
- Public host has no unexpected D1/KV/write binding;
- API `DB` resolves to `holoviewer-public-v1`;
- no unexpected route points at an unreviewed Worker/backend;
- canonical public API origin remains
  `https://holoviewer-public-api.singlebagel.workers.dev`;
- rollback revision is recorded before mutation;
- any difference from repository config is explicitly reviewed rather than silently normalized.

A mismatch is a **STOP / review** condition, not permission to repair production in place.

## Phase C — owner-gated hosted read-only canary

Do not execute until #45 and the owner explicitly authorize the live canary.

Frozen first window:

1. `GET /health`
2. `GET /v1/catalog/today?day=<Taipei-day>&limit=1`
3. `GET /v1/ptt/today?day=<Taipei-day>&limit=1`
4. `GET /v1/ptt/history?day=<Taipei-day>&limit=1`
5. Only when step 4 returns `has_more=true`: one
   `GET /v1/ptt/history?day=<same>&limit=1&after=<opaque returned push_id>`

Hard ceilings:

- HTTP requests: <= 5
- automatic retries: 0
- D1 queries: <= 12
- Rows Read attributable delta: <= 1,000
- Rows Written: exactly 0
- unexpected route/write SQL: 0

Normal product PTT remains disabled/fail-closed before the independent #48 production
gate and owner-authorized cutover.

## Evidence receipt fields

Record one immutable review receipt containing:

- UTC/Taipei observation window;
- repository #68/#47/#48/accepted-4174 SHAs;
- live Public Worker name + deployed revision;
- live API Worker name + deployed revision;
- route/domain/zone identifiers needed for rollback review;
- Public-host binding names/types (never secret values);
- API binding `DB` target identity;
- whether `ALLOWED_ORIGIN` matches the intended Public origin (value may be redacted if necessary);
- compatibility dates/flags;
- rollback revision;
- each canary request path/status/content-type/cache/CORS;
- response schema/day/freshness/completeness;
- PTT continuation equality + advancement, when applicable;
- request/query/Rows Read/Rows Written/retry deltas;
- explicit `production_mutation=false` for Phase A/B;
- explicit owner authorization reference before Phase C.

## Hard stop boundaries

Stop before any of these:

- Worker configuration or deployment change;
- route/custom-domain mutation;
- D1 migration or any write;
- Publisher/Cron activation;
- secret/API-token/account-setting change;
- merge/cutover;
- enabling normal product PTT.

These are owner-gated production actions, not #68 offline work.
