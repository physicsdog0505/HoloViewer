# #45 Production API deployment runbook (2026-10-21)

## Do not confuse the Workers
- Production API: `holoviewer-public-api`, endpoint `https://holoviewer-public-api.singlebagel.workers.dev`.
- API source entry: `ptt_offline/worker_host/index.mjs` (composes Today, PTT, WebSub, recovery and other routes).
- Production D1 binding: `DB` -> `holoviewer-public-v1`, ID `64e1a0ee-1455-4377-9640-3922e8f4d061`.
- `cloudflare/wrangler.json` is **STATIC SITE ONLY** for `holoviewer-public`; NEVER use it for API deployment.
- Existing API production cron has historically been `* * * * *`; Today lifecycle runs on its 5-minute gate.

## Prior proven deployment commands
Prior #45 successful operations used a separate temporary API Wrangler config, not the static-site config, with the API entrypoint:
```sh
npx wrangler deployments list --name holoviewer-public-api
npx wrangler deploy "$RELEASE/ptt_offline/worker_host/index.mjs" \
  --name holoviewer-public-api --config "$CONFIG" --keep-vars --dry-run
npx wrangler deploy "$RELEASE/ptt_offline/worker_host/index.mjs" \
  --name holoviewer-public-api --config "$CONFIG" --keep-vars
```
`RELEASE` must contain the reviewed immutable source snapshot, and `CONFIG` must be a **verified API** Wrangler file preserving the full existing bindings, vars, compatibility, triggers and secret names. Historical configs lived in temporary locations such as `/tmp/hv45-release-ATttP0/wrangler.json`; do not assume those files still exist. Do not paste secret values anywhere.

Previously successful 2026-10-16 API deployment version: `536cb053-cd4e-4cb8-b185-52c6b9827719` (historical, not guaranteed current).

## Controlled #47 PR #156 rollout
- Source accepted: `62ff48af3a01a00f69ce124a0f44fc32f2995c50`; owner-local `node --test ptt_offline/test_today_cadence.mjs` = **15 PASS, 0 FAIL**.
- Owner explicitly authorized a Production rollout on 2026-10-21. **Not yet deployed.**
- #156 is a Draft stacked onto `issue47/video-metadata-fallback`, NOT `main`. Build a minimal release delta against CURRENT production source; do not merge or deploy the entire Draft branch automatically.
- Patch only `ptt_offline/worker_host/today/cadence-refresh.mjs`, `store.mjs`, plus source-compatible tests. Ensure `checked_at` is freshness/rotation timestamp, `lifecycle_observed_at + source_checksum` retains evidence provenance.
- Before deploy: freeze current deployed version, compare source/entrypoint, record Worker D1 binding `DB`, cron, vars/secrets and rollback target. Preserve all existing routes, vars and secrets (historically Today cadence/collector enabled, discovery/reconcile disabled, plus WebSub and support-color bindings). A stale minimal config can delete bindings/triggers: FAIL CLOSED on mismatch.
- Then execute exactly **one** reviewed Wrangler dry-run, followed by exactly **one** authorized deploy; no DB migration, Publisher restarts, R2, PTT writes or frontend deploy.
- After deploy: check HTTP status and contract for `/health`, `/v1/catalog/today`, `/v1/collab/live`, `/v1/ptt/today`; verify cron/cadence, current Worker Version ID and 5/15-minute Cloudflare D1 read/write trend. Compare fresh vs stale semantics. Rollback via known-good Worker deployment version if regressions occur.
- CI is passive evidence only. Owner Mac local tests are authoritative. Never claim production deployment without an actual Wrangler deployment receipt.

## Ongoing handoff rule
Keep this runbook and each PR's exact SHA, acceptance receipt, Cloudflare deployed Version ID, binding/schedule diff, smoke outcomes and rollback version updated in GitHub. #45 owns integrated review/deployment, #47 owns Today lifecycle source, #48 owns Publisher. Do not ask the owner to rediscover this deployment architecture.
