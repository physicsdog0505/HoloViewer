# #68 — accepted 4174 Python Worker host production diff proposal (NO DEPLOY)

**Owner:** #68 Public host / accepted 4174 Consumer. **Backend API shell owner:** #47. **PTT mount owner:** #48. Canonical coordination: #45 comment 6190442416; #68 comment 6190448478.

This is a **review-only proposed host diff** derived from the *executed*, same-Worker local Pyodide configuration. It is not a new backend, a second API Worker, a second frontend or an authorized Cloudflare deployment. The existing production host Worker identity and account identifiers must be confirmed by #45 before producing an applied Wrangler configuration.

## Known verified local configuration

The pinned source manifest specifies SHA `a144bb378a8bdd772faa867d608c1e7491253883`. The disposable Worker build uses:

```json
{
  "main": "entry.py",
  "compatibility_date": "2026-10-15",
  "compatibility_flags": ["python_workers"]
}
```

The **same** local Worker serves the accepted external files using this additional configuration:

```json
{
  "assets": {
    "directory": "./public",
    "binding": "ASSETS",
    "run_worker_first": false
  }
}
```

The actual local workerd/Playwright evidence is Actions `38722971689`: four assets 4/4 exact SHA/content matches, accepted HTTP 4/4, and Home/History browser geometry 6/6. No separate Pages shell, JS reimplementation or product rewrite.

## Proposed code/config boundary

- Preserve `platform_adapter/cloudflare_entry.Default.fetch` as the **original accepted product renderer** transport. Keep `ClientRequestHandler.do_GET` as the product router, request-local async canonical `pyfetch` preload and explicit unbound-route 503.
- Package only manifest-verified original 4174 source blobs and the separate `platform_adapter`. Build-local `tzdata>=2025.2` is required for `Asia/Taipei`. The original `requirements.txt` is moved to build metadata after blob verification, not edited in vendor.
- Serve external original `public/ptt_player_adapter.js`, `public/ptt_timeline.js`, `public/ptt_worker_adapter.js` via the **same Python Worker assets binding**, before calling product dispatch. An owner-confirmed mapping is required for original root-level `hololive_channels.prototype.json`, currently copied to `public/` only within the disposable proof bundle.
- Keep `holoviewer-public-api` a distinct **existing canonical API service**, independently owned by #47/#48. Do not move `DB` to the UI Worker: `env.DB -> holoviewer-public-v1` is owned by the existing API shell. The frontend performs only bounded GET reads to the reviewed API endpoint.
- Keep `/v1/history` clearly **legacy-compatible**, not canonical #47/#48 History evidence; keep PTT unbound until #48's reviewed mount is available. Preserve existing accepted player, Custom View, Watchalong and PTT product semantics; no pretend feature completion.

## Pre-deploy owner validation required

1. Existing Public host Worker **exact name**, routes/domains, Wrangler configuration and deployment revision (not guessed).
2. Correct existing public API Worker `holoviewer-public-api`, exact existing `DB` binding target `holoviewer-public-v1`, access/CORS and request budgets (review authority #45/#47).
3. Reviewed combined #47 Today + #48 PTT router source with local/mock D1-compatible integration receipt. #68 must consume, not edit, that router.
4. Owner-confirmed asset URL map, CSP/security headers, production timezone/package compatibility, and actual retained 4174 product routes.
5. Explicit authorization just before live Worker deployment/config mutation, D1 migration/write, Publisher/Cron activation, secrets, merge or cutover. **None is authorized by this document.**

## Consumer-side executable readiness probe

Once the owner-supplied canonical Router is runnable on loopback, execute:

```sh
python3 tools/check_8788_local_router_contract.py \
  --api-base http://127.0.0.1:8789 \
  --output /tmp/8788-owner-router-consumer-receipt.json
```

It uses only `GET /v1/catalog/today`, validates `public-consumer-v1`, runs the real accepted `HomeStream` mapping and produces a bounded receipt. Add `--ptt-day YYYY-MM-DD` only after #48's two routes have been mounted and reviewed. The probe *forbids production origins and cross-host redirects*, cannot perform writes, and does not emulate the backend Router. It is not yet an executed owner-Router end-to-end receipt.

## #68 PTT Consumer readiness gate (review 6191562731)

The platform adapter now provides `PttPublicReader` for exactly the owner-reviewed #48 `/v1/ptt/today` and `/v1/ptt/history` public envelopes. **Default disabled**; any attempt to read before explicit local reviewed mount availability raises `PublicAPIUnavailable` *before* invoking an HTTP transport. It has no Writer, D1/SQLite read, custom PTT business semantics, or product HTML renderer. The #68 Python Worker continues to return 503 for unmounted PTT paths.

Only after the exact #47 base shell + #48 mount receives owner review and is executed in disposable local/mock-D1 mode may #68 instantiate the reader with `enabled=True` **in a test/integration environment**. The local-only consumer canary `tools/check_8788_local_router_contract.py --api-base http://127.0.0.1:8789 --ptt-day YYYY-MM-DD` verifies the target envelope using the reviewed #48 model without touching a production endpoint.

The PTT adapter unit suite validates fresh/stale/unknown, completeness gap true/false, opaque continuation, cross-day envelopes, malformed/missing responses, and rejects private `cursor`/`origin` fields. **Unit success is not an end-to-end DB/router receipt**. This production proposal remains nondeployable until #45 confirms host identity, exact combined API source and live owner gating.

## Exact local combined-API evidence (2026-10-15; NO DEPLOY)

Source HEADs pinned in the executed offline workflow:
- existing #47 API shell and canonical Today: `149a80361654b06377dbae580e1d8da2e5010cf0`;
- #48 PTT injection module: `b96d0902a504bc26019efd693a1b3586cfb3d3d2`;
- #68 Consumer test HEAD: `589a0a69e0ea7af9f4d03eb19fa15bee9b43ecf0`;
- executed workflow: [38736532548](https://github.com/physicsdog0505/HoloViewer/actions/runs/38736532548), SUCCESS.

The test imports the **actual #47 + #48 owner-authored modules** (no copied API/router) and runs the single combined shell via local Node HTTP with deterministic, read-only D1-compatible `prepare/bind/all/first` fixtures. #68's actual Python consumer mapping then calls the loopback API to consume canonical Today and PTT Today, reads PTT History page one with `limit=1`, carries its opaque `next_checkpoint` through `PttPublicReader.read_history`, maps the query to `after`, and verifies the second distinct push appears. Actual `history_continuation_checked=true`, `history_second_count=1`, `db_reads=7` in the successful combined receipt. A separate unmounted Today-only router check has `db_reads=2`.

The **same CI run** also records 42/42 offline tests, local Pyodide Python Worker startup, four exact original asset bytes and six Playwright Home/History geometry comparisons. The combined API/router runs through the accepted **Python consumer contract**; the local Pyodide rendering fixture is a separate CI step. This is *not yet* a single HTTP trace from Pyodide `fetch()` through the combined router. Do not claim production deployed D1, live PTT publication, or PTT UI cutover.

**Source-only/mocked milestone:** the 4174 Consumer can consume the actual combined owner-authored Router using a D1-compatible mock. Remaining production gates: independent acceptance of the #48 mount against the precise #47 base, real existing Worker account/binding identity, end-to-end Pyodide fetch against owner Router where required, D1 read-only canary, and owner-authorized deployment/merge. PTT product routes remain explicit 503 until those gates are cleared.


## 8788 production host wiring — offline configuration validation

A non-Wrangler, inert machine-readable proposal now lives at `platform_adapter/production_host_wiring_spec.json`. It deliberately leaves the Public host Worker name as `null` with `owner_confirmation_required=true`; it cannot be mistaken for an applied Cloudflare configuration. Offline regression `test_production_host_wiring.py` enforces all of the following:

- the Public/UI Python Worker has **no D1 binding**;
- the existing API Worker remains `holoviewer-public-api`, canonical origin `https://holoviewer-public-api.singlebagel.workers.dev`;
- `DB -> holoviewer-public-v1` belongs to the canonical API Worker, not the UI Worker;
- the reviewed #47 source is pinned to `149a80361654b06377dbae580e1d8da2e5010cf0`;
- the reviewed #48 mount source is pinned to `b96d0902a504bc26019efd693a1b3586cfb3d3d2`;
- the Python Worker remains `python_workers` + same-Worker `ASSETS`, with `run_worker_first=false`;
- normal product PTT remains `enabled=false` and fail-closed;
- deploy, route/domain mutation, D1 migration/write, Publisher/Cron, secrets and merge/cutover remain explicit owner gates.

This validates the **shape and ownership boundary** of production wiring without inventing the unknown production host Worker identity, account route, domain or existing deployment revision.

## Single Pyodide fetch -> combined Router -> mock D1 proof

#68 now includes a local-only test harness for the previously missing single trace:

`tools/serve_8788_owner_api_mock.mjs`
- imports the exact #47 and #48 owner-authored modules from pinned checkouts;
- mounts #48 using its reviewed `createPttMountedApiRouter` over the exact #47 existing shell;
- exposes only a loopback HTTP server with deterministic read-only mock-D1 `prepare/bind/all/first` behavior;
- rejects unknown mock-D1 query shapes and contains no write path.

`tools/probe_pyodide_combined_router.py`
- mutates only a **disposable** manifest-pinned Worker bundle;
- replaces the test bundle's outbound canonical-API transport with a loopback-only `pyodide.http.pyfetch` bridge;
- requests the accepted Python Worker `/api/home` route;
- therefore exercises one actual chain: **Pyodide fetch -> exact combined #47+#48 Router -> mock D1 -> accepted 4174 Home renderer**;
- separately verifies that the same combined Router has the reviewed #48 PTT mount active while leaving normal product PTT disabled;
- records `production_deployment=false`, `production_d1=false`, and `ptt_product_enabled=false`.

The exact-head workflow now executes this proof in addition to the existing combined-router Consumer test, 42-test regression set, Pyodide runtime proof, same-Worker static asset hashes, and Playwright geometry checks. Until exact-head CI for this new proof is green, classify this paragraph as **IMPLEMENTED / CI-PENDING**, not PASS.

## Remaining production gates after offline host validation

1. **#48 independent acceptance:** required before normal product PTT can be enabled. Local canaries may use `PttPublicReader(enabled=True)` only as test evidence.
2. **Existing Public host identity/config:** exact Worker name, account/zone, routes/custom domain, deployed revision, CSP/security headers and owner-managed configuration are still UNKNOWN and must be confirmed by #45/Owner.
3. **Real D1 read canary:** current proof is D1-compatible mock only. Real `holoviewer-public-v1` access is a production/staging mutation boundary and is not attempted here.
4. **Cloudflare API Worker production wiring:** exact combined #47+#48 production source, API Worker deployment/config and D1 binding must be reviewed independently; #68 only consumes it.
5. **Mutation authorization:** no deployment, D1 migration/write, Publisher/Cron activation, secret change, merge or cutover without explicit Owner authorization.


## Explicit production routing / environment ownership

The inert wiring spec now records the actual ownership boundary rather than leaving environment behavior implicit:

| Hop | Runtime owner | Required binding / variable | Offline disposition |
|---|---|---|---|
| Browser -> accepted product/static | Public Python Worker | `ASSETS`, `run_worker_first=false` | verified local shape; production Worker name/route still owner-confirmed |
| Accepted Python Worker -> canonical data API | Public Python Worker | hard-pinned `platform_adapter.public_api.DEFAULT_API`; no runtime API-base override | prevents deployment-time origin drift |
| Canonical API -> data store | `holoviewer-public-api` | D1 binding `DB -> holoviewer-public-v1` | belongs only to API Worker; UI Worker has zero D1 bindings |
| Browser-origin CORS at canonical API | `holoviewer-public-api` | `ALLOWED_ORIGIN` | exact production value remains owner-confirmed; do not guess it |
| Accepted product PTT | Public Python Worker | none yet | disabled/fail-closed until #48 independent acceptance + owner cutover |

No secret is required by the accepted Python Worker for read-only canonical API access. Any future credential/service-binding proposal is a new review item, not implied by this host diff.


## Repository-confirmed current Public host baseline

Read-only inspection of current `main` resolves the repository-configured host identity that was previously marked unknown:

- `cloudflare/wrangler.json`: Worker name **`holoviewer-public`**, compatibility date `2026-10-14`, static assets only from `../site`; no Worker script, D1, KV or routes in that repo config.
- `.github/workflows/deploy-cloudflare-production.yml`: manual `workflow_dispatch` only; exact reviewed main SHA + `BASELINE-CHECKED` are required before Wrangler deploy; existing deployment uses owner-managed Cloudflare token/account secrets.
- `site/assets/config.js`: existing public client points at the same canonical API origin `https://holoviewer-public-api.singlebagel.workers.dev`.

Therefore the proposed 8788 host diff is now concrete at repository level: retain the existing **`holoviewer-public`** identity, replace the static-only host configuration with the reviewed Python Worker `entry.py` + `python_workers`, keep same-Worker static assets through `ASSETS`, and add **no D1/KV binding** to the Public host. The canonical API remains separate.

This does **not** prove the currently deployed Cloudflare revision, account/zone route state, custom-domain mapping, or runtime headers. Those remain read-only production preflight evidence required by #45 immediately before any owner-authorized config/deploy mutation.
