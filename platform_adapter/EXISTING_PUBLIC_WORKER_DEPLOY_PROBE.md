# #68 — existing Public Worker deployment candidate (owner execution)

**Current state:** Source package and configuration only. No production deploy, no D1 write, no full-route or real PTT acceptance. This document does not authorize mutations.

## Build and verify (offline)

Run from the `dev/8788-full-4174` checkout that contains `tools/package_8788_production_candidate.py`:

```sh
python3 -B -m unittest -v test_package_8788_production_candidate
python3 tools/package_8788_production_candidate.py --output /tmp/holoviewer-public-candidate
cd /tmp/holoviewer-public-candidate
cat wrangler.jsonc
uvx --from workers-py pywrangler dev --local --ip 127.0.0.1 --port 8787
```

The generated configuration targets **existing** `holoviewer-public`, `entry.py`, `python_workers`, same-Worker `ASSETS` with `./public`, zero UI D1 bindings and the SHA-pinned accepted 4174 source. The builder never deploys or modifies the original vendor. It MUST NOT include `entry_fixture.py`. Verify all expected static asset bytes using `bundle-provenance.json`.

**Critical limitation:** `platform_adapter/cloudflare_entry.py` currently gates product routes to `/`, `/api/home`, and `/history`; other routes return 503. This artifact is a limited *runtime/packaging probe*, not 4174 full-feature production release. Real PTT Collector-backed UI acceptance and general route restoration are separate defects and must remain visible. Do not silently claim otherwise.

## Live deployment gate (NOT authorized by this document)

The owner-confirmed Cloudflare account and Worker are known from #45 issue comment 6193852809. The existing static Worker is replaceable per #68 issue comment 6194401811, but **capture full active version and rollback identity first**:

```sh
npx wrangler whoami
npx wrangler deployments list --name holoviewer-public
npx wrangler versions list --name holoviewer-public
```

Before proceeding, #45/owner must approve replacing the existing static shell and confirm rollback version. Do not create a second permanent Worker or D1 database. Keep canonical API as existing `holoviewer-public-api`; no UI D1 binding, secret, Cron or Publisher. Only after separate explicit approval, from the generated candidate directory:

```sh
uvx --from workers-py pywrangler deploy
```

`pywrangler deploy` is the official Python Workers deployment command. Actual run must be accompanied by verified deployed version, runtime logs, startup, CSS/JS/static asset GET, representative `/`, `/api/home`, `/history`, expected 503 for currently unbound routes, canonical API connectivity and CORS evidence; **do not mark all pages PASS**. If runtime fails, follow the version-specific rollback procedure confirmed by the owner in Wrangler Dashboard, then reassess the packaging/entrypoint.

**Further gates:** Current API Worker still needs #45 route/CORS validation; Today D1 migration is owned by #47; PTT raw Collector data and Publisher are separately owned by #48. A deploy probe is *not* authorization to erase any intended product feature.
