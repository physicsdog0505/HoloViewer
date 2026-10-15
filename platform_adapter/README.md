# 8788 minimal Public API binding (Phase E)

Checkpoint 3 was independently accepted at `0e1d2918d27b190312109b2f9d9e2fdb7cf59cb8` in HoloViewer Issue #68. The accepted product code under `vendor/4174-a144bb3/` remains byte-identical and immutable.

Canonical data source: existing `holoviewer-public-api` with Worker binding `DB` to `holoviewer-public-v1`, as frozen by Issue #45 comment 6188242451. No local DB replication, new D1, staging service, or additional API Worker is created here.

The existing `scripts/start_8788_full_4174.sh` remains offline/isolated by default. To opt into canonical read-only provider mode for integration, set `HOLOVIEWER_PUBLIC_API_BASE=https://holoviewer-public-api.singlebagel.workers.dev` before launching that same script. The runner injects only accepted data-entry functions, not a second HTML/frontend implementation.

Current read-only bindings:
- `client_app.load_home_streams` and `client_home.load_home_streams` obtain Today catalog via GET `/v1/catalog/today`.
- `client_app.load_history_day` obtains GET `/v1/history?day=...&limit=50&offset=...`.
- `PublicAPI.read_video` is available through GET `/v1/catalog/videos/:id` but is **not yet wired** to the accepted PTT/video player resolver; do not misrepresent it as complete.
- PTT Today/History, Watchalong, Collab, player lifecycle and CSS are **untouched** while their verified consumer transport is finalized by #47/#48/#45.

Safety: HTTPS, bounded GET response, no credentials/secrets, refused redirects, external data errors yield explicit 503 rather than fake empty/COMPLETE; LIVE is suppressed without fresh authoritative feed evidence. The UI uses accepted 4174 renderers and their existing data classes.

No production Worker bindings, Cloudflare D1 migrations, writers, Cron, secrets or deployments were modified. This is a source-level integration slice; **live API availability and populated-data rendering have not yet been executed/verified**.

Production platform caveat: the accepted product includes Python server-rendering and local SQLite dependencies. This integration mode proves the provider-neutral data entry seam, **not** that the Python server itself runs inside Cloudflare Workers. A faithful host/static delivery strategy for the original accepted renderer remains a real platform integration decision; no competing reimplementation is authorized.
