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
