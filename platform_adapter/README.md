# 8788 minimal Public API binding (Phase E)

Checkpoint 3 was independently accepted at `0e1d2918d27b190312109b2f9d9e2fdb7cf59cb8` in HoloViewer Issue #68. The accepted product code under `vendor/4174-a144bb3/` remains byte-identical and immutable.

Canonical data source: existing `holoviewer-public-api` with Worker binding `DB` to `holoviewer-public-v1`, as frozen by Issue #45 comment 6188242451. No local DB replication, new D1, staging service, or additional API Worker is created here.

The adapter permits only the exact canonical Public API origin for production. An alternate URL is denied by default; explicit `_test_only_allow_alternate_origin=True` exists solely for direct mock transport tests and is not exposed by production startup. The existing `scripts/start_8788_full_4174.sh` remains offline/isolated by default. To opt into canonical read-only provider mode for integration, set `HOLOVIEWER_PUBLIC_API_BASE=https://holoviewer-public-api.singlebagel.workers.dev` before launching that same script. The runner injects only accepted data-entry functions, not a second HTML/frontend implementation.

Current read-only bindings:
- `client_app.load_home_streams` and `client_home.load_home_streams` obtain Today catalog via GET `/v1/catalog/today`.
- `client_app.load_history_day` obtains GET `/v1/history?day=...&limit=50&offset=...`.
- `PublicAPI.read_video` is available through GET `/v1/catalog/videos/:id` but is **not yet wired** to the accepted PTT/video player resolver; do not misrepresent it as complete.
- PTT Today/History, Watchalong, Collab, player lifecycle and CSS are **untouched** while their verified consumer transport is finalized by #47/#48/#45.

Today freshness is consumed from canonical `freshness.status` (`fresh` / `stale` / `unknown`), not `freshness.state` or a scalar string. `waiting` and `stale` remain distinct on accepted `HomeStream.state` and are bucketed separately. Unknown/malformed freshness never permits a LIVE assertion.

Safety: HTTPS, bounded GET response, no credentials/secrets, refused redirects, external data errors yield explicit 503 rather than fake empty/COMPLETE; LIVE is suppressed without fresh authoritative feed evidence. The UI uses accepted 4174 renderers and their existing data classes.

No production Worker bindings, Cloudflare D1 migrations, writers, Cron, secrets or deployments were modified. This is a source-level integration slice; **live API availability and populated-data rendering have not yet been executed/verified**.

Production platform caveat: the accepted product includes Python server-rendering and local SQLite dependencies. This integration mode proves the provider-neutral data entry seam, **not** that the Python server itself runs inside Cloudflare Workers. A faithful host/static delivery strategy for the original accepted renderer remains a real platform integration decision; no competing reimplementation is authorized.

## Cloudflare Python Worker transport feasibility (source-only)

Issue #68 comments `6189311810` and `6189323248` authorize a **transport shim** over the accepted 4174 handler, not another product.

- `worker_transport.py` constructs an in-memory, socketless request for the original `ClientRequestHandler.do_GET` and extracts status, response headers and body. It duplicates **no route dispatch or HTML renderer**.
- `cloudflare_entry.py` shows the official `WorkerEntrypoint.fetch` integration with the Cloudflare Python `Response` API. It is **not wired into Wrangler or deployed**; the accepted vendor module must be bundled and its runtime imports verified.
- `test_worker_transport.py` exercises ordinary HTML, JSON, invalid-history and method/target rejection with a transport fixture.
- `tools/check_worker_transport_parity.py` offers an owner-local comparison against a running accepted 4174 HTTP handler for `/`, `/api/home`, and `/history?date=invalid`. Its output is a candidate receipt, **not already executed**.

**Unproven concrete compatibility points**: direct Python Worker import of the vendored `client_app` dependency closure (including `sqlite3`, `threading`, filesystem and other modules), non-blocking Worker fetch compatibility with synchronous `urllib` in `PublicAPI`, and packaging static PTT assets without local writable storage. The accepted HTTP dispatcher still handles route semantics; no Worker-local DB or thread may be started. The source adapter should not be represented as production-runnable until tested inside the Python Workers runtime and reconciled with the existing `holoviewer-public-api` service.

No Cloudflare account operation, D1 migration, new runtime backend, Wrangler deploy, or product rewrite has been performed.

### Proof-slice route fail-closed rule

The experimental Python Worker entry currently permits only `/`, `/api/home`, and `/history` to reach the accepted handler. All other paths return 503 before product dispatch because their canonical Worker data providers have **not** been bound; this avoids rendering misleading local-SQLite emptiness. The restriction is a temporary data-readiness gate, not a copy of accepted route/navigation logic. Expand it only after the corresponding canonical provider route exists and has accepted behavior parity.

`test_cloudflare_entry_binding.py` checks that the original handler is called only after `bind_public_today(client_app, api_base=DEFAULT_API)`, exactly once, and that unbound PTT returns 503 without local data dispatch. **Tests are committed, not yet executed.**

## Async provider transport and disposable Worker bundle

Cloudflare Python Workers execute in Pyodide. The official Python Worker handler is async, and its supported outbound HTTP primitive is asynchronous. The approved 4174 product loaders remain synchronous; production Worker requests now `await` the canonical API read **before** entering the original handler. `preloaded_public_reads()` stores the result in a request-local ContextVar; any unprefetched read fails closed instead of calling blocking `urllib` inside the Worker.

- `platform_adapter/worker_preload.py`: prefetches canonical Today and History using `pyodide.http.pyfetch` and accepted 4174 History date parsing/bounds.
- `test_worker_preload.py`: validates request scoping, nested cleanup, history day/key matching and no synchronous fallback.
- `tools/build_python_worker_bundle.py`: copies only manifest-listed, Git-blob-verified pinned 4174 files into a **new disposable build folder**, includes the platform adapter and local Python Worker `entry.py`/configuration. This does not deploy a Worker or create a new backend/D1.
- `test_python_worker_bundle.py`: verifies manifest packaging and fail-on-overwrite.

Offline source regression commands (run from the HoloViewer checkout):

```sh
python3 -B -m unittest -v \
  test_public_api_binding \
  test_worker_preload \
  test_worker_transport \
  test_worker_transport_accepted \
  test_cloudflare_entry_binding \
  test_python_worker_bundle
python3 tools/build_python_worker_bundle.py --output /tmp/hv-worker-feasibility-NEW
```

For real Python Worker runtime compatibility, start the resulting folder with the Cloudflare Python Workers toolchain in **local dev mode only** (not deploy). Verify `WorkerEntrypoint.fetch` import, async canonical API transport and immutable vendored asset reads; preserve actual error evidence in the Issue. The build presence and CPython tests do **not** claim Pyodide/Worker or browser/DOM PASS.

Only `/`, `/api/home`, and `/history` are in the first proof scope. The canonical backend remains the **existing** `holoviewer-public-api -> DB -> holoviewer-public-v1`. Other accepted product features and PTT routes are not fabricated in the Worker shell.
