# 8788 Phase E — isolated Cloudflare migration slice

Status: **development-only; not deployed; not yet a UI or functional parity claim.**

## Ground truth / boundaries

- Accepted 4174 is private `physicsdog0505/Hololive-PTT-Viewer@a144bb378a8bdd772faa867d608c1e7491253883`. It remains immutable in this stream.
- 8788 Phase C vendored snapshot is only an acceptance/reference implementation, **not Cloudflare-executable Python**.
- Phase C integrity check deliberately forbids repository-root `site/` and `cloudflare/`. We leave that gate intact; Phase E is developed under `migration/phase_e/` until integration review permits a phase transition.
- Public production `main` owns `site/**`; no modification or overwrite in this slice.
- Backend Today is independently owned by Issue #47; PTT by Issue #48; read-only consumer inventory belongs to Issue #45. Do not implement competing writers or fabricate local source data.

## First implemented slice

`public_readonly_api.mjs` is an isolated browser/edge-compatible boundary for **confirmed** Public read routes:
- `GET /v1/catalog/today`
- `GET /v1/history?day=YYYY-MM-DD&limit=50&offset=0`
- `GET /v1/catalog/videos/:video_id`

It requires an HTTPS origin, rejects unsupported routes, bounds input, uses GET with omitted credentials and no redirect, and refuses non-object API payloads. It **does not** interpret empty responses as complete data or infer YouTube lifecycle.

`node --test migration/phase_e/public_readonly_api.test.mjs` is a small optional local correctness check, not a new required CI gate.

## Integration prerequisites (not blocking isolated development)

1. Freeze actual JSON shapes, freshness/completeness and cursor behavior from #45/#47/#48, preserving 4174 semantics.
2. Extract accepted 4174 layout/interaction into a Cloudflare-compatible static shell (not a screenshot, iframe proxy, or Python server at request time); verify custom-view playback, session routing and responsive behavior manually at integration.
3. Implement adapters for Today, History, PTT, Collab and Watchalong only as their respective read contracts are certified. Fail visibly on unknown/unavailable data.
4. Introduce an explicit Phase E promotion gate, only when the static shell and API are ready. Do **not** remove or weaken Phase C snapshot protection.
5. Independent reviewer checks source parity and security boundary before a production merge/deploy.

## Unresolved / must not assume

- PTT Today endpoint shape, pagination, article AID provenance and verified timing.
- Collab event identity and master/POV relationships.
- Watchalong cached transcript/translation availability and licensing.
- API availability, Cloudflare bindings, D1 migrations and publish authorization.

No production services, credentials, local 4174 checkout, database or Cloudflare resources have been touched.
