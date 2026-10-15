# #68 — Owner-verifiable production identity preflight (READ ONLY)

**Status:** OFFLINE HOST WIRING ACCEPTED; LIVE CLOUDFLARE IDENTITY UNKNOWN. This is a checklist/receipt schema, *not* deployment instructions or authorization.

## Frozen evidence and review references

- Accepted 4174 product: `a144bb378a8bdd772faa867d608c1e7491253883`
- #68 accepted offline host candidate: `c1b12c398e9237f16b4848cadf98837f99a61b92`, Actions `38741312102` SUCCESS, #45 matrix comment `6193046530`
- #47 canonical source shell pin consumed by #68: `149a80361654b06377dbae580e1d8da2e5010cf0`. Latest reviewed #47 preflight candidate: `6469d2d6ad377adbe4fc057dea06a11923ddf9f4`, Actions `38741895778` SUCCESS. Updating that preflight tool does *not* silently change the combined Router source pin.
- #48 combined Router mount pin consumed by #68: `b96d0902a504bc26019efd693a1b3586cfb3d3d2`. #45 matrix reviewed Publisher candidate `a689cb6670a8aa4014455600d98754729f50d921`, PASS WITH CONDITIONS; positive Publisher source authority not yet accepted.
- #68 local single Pyodide fetch to combined Router to Mock D1: PASS. **This is not a real-D1 or deployed Cloudflare trace.**

## Repository-confirmed baseline (not live Cloudflare evidence)

| Property | Repository state | Owner read-only verification required |
|---|---|---|
| Public host Worker | `holoviewer-public` in main `cloudflare/wrangler.json` | Actual deployed script/service ID, account+zone, active routes/custom domains, deployment SHA |
| Public host mode | existing repo config static `../site` | Whether current deployed service corresponds to repo-configured baseline |
| Proposed #68 host | `entry.py`, `python_workers`, `ASSETS` -> `./public`, `run_worker_first=false` | Confirm asset URL map and CSP headers before applying any config |
| UI host D1/KV | none proposed | Confirm no unintended bindings in deployed UI service |
| Canonical API | `holoviewer-public-api.singlebagel.workers.dev` | Deployed Worker identity, revision, routes, allowed browser origin |
| API D1 binding | `DB -> holoviewer-public-v1` (contract) | Read-only binding metadata: actual D1 database UUID, account identity; do **not** copy credentials into receipt |
| API CORS | `ALLOWED_ORIGIN` | Actual configured allowed-origin value, header behavior without exposing secrets |
| Product PTT | disabled/fail-closed | Verify zero production reads/writes are authorized by this checklist |

## Owner preflight receipt fields

Owner or #45 independently records these **without making a production mutation**. For sensitive identifiers use a confirmation Boolean and safe hash/short fingerprint rather than full tokens, D1 contents or secrets.

```json
{
  "schema": "holoviewer-production-identity-readonly-v1",
  "observed_at_utc": null,
  "reviewer": null,
  "repository_main_sha": null,
  "repo_host_worker_name": "holoviewer-public",
  "live_host_worker_exists": null,
  "live_host_deployed_revision": null,
  "live_host_account_zone_confirmed": false,
  "live_host_routes_and_custom_domains_confirmed": false,
  "live_host_asset_url_map_and_headers_confirmed": false,
  "live_host_has_no_unintended_d1_or_kv": null,
  "api_worker_name": "holoviewer-public-api",
  "live_api_deployed_revision": null,
  "api_binding_DB_to_holoviewer_public_v1_confirmed": false,
  "api_allowed_origin_matches_public_host": null,
  "ptt_product_fail_closed_confirmed": null,
  "source_fingerprint_preflight_pass": null,
  "canary_budget_http_max": 5,
  "canary_budget_d1_queries_max": 12,
  "canary_budget_rows_read_max": 1000,
  "canary_budget_rows_written": 0,
  "canary_retries": 0,
  "rollback_previous_host_revision_confirmed": false,
  "rollback_previous_api_revision_confirmed": false,
  "production_mutation_authorized": false
}
```

Null means NOT VERIFIED, **not** PASS. Obtain only read-only deployment/version/binding metadata when owner-controlled access is authorized; do not query actual D1 or change existing routes for this identity inventory. The canary budget defines a future separately owner-approved read-only operation, not permission to run it now.

## No-action / freeze gates

- No merge, Wrangler deploy, route/domain change, secret mutation, migration, D1 query/write, Publisher/Cron enablement or cutover.
- No replacing previously PASS UI, player, Router, backend source or accepted 4174 vendor files.
- No positive PTT publisher assertion until #48 proves trusted identity+timestamp chronology and observed-gap versus unverified completeness.
- Any mismatch between repo baseline and live Worker identity/revision is **HOLD**, reported to #45; never auto-reconcile deployed config.
- Proposed Cloudflare packaging is *inert*: exact approved Worker bundle only; no credentials or live binding values embedded.

## Handoff gate

#45 should compare its frozen integration matrix with this field-by-field receipt, confirm owner decisions on domain/CORS and rollback, then separately authorize any actual cloud read-only canary. A green local/mock test does not unlock a cloud action.
