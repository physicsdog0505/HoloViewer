# Issue #176 — Owner-local Production custom-domain rollout

**State: REVIEW / DO NOT EXECUTE BEFORE OWNER APPROVAL.** This runbook is for the existing frontend `holoviewer-public`, not a new Worker. API and PTT archive hosts remain on workers.dev. Do not use GitHub Actions/CI to deploy.

## Source of truth

The branch updates `cloudflare/wrangler.json` to explicitly include `workers_dev: true` and `routes: [{pattern: "holodocchi.com",custom_domain:true}]`. All prior name, compatibility date, assets directory, and SPA handling stay unchanged. Once merged and Owner-deployed, **Wrangler is the routing source of truth**. Do **not** separately add a Dashboard-only binding or normal Worker Route.

## Gate 0 — readback / receipts (no mutation)

Owner must collect:
- authenticated account and `holodocchi.com` zone match; DNSSEC still Active;
- no existing apex conflicting DNS record, Worker custom domain, or route;
- currently deployed version ID of `holoviewer-public` and `holoviewer-public-api`, plus previously known-good rollback version IDs;
- **actual deployed API `ALLOWED_ORIGIN` value** read in Cloudflare Dashboard > Workers & Pages > `holoviewer-public-api` > Settings > Variables and Secrets. If value is hidden because it is a secret, do not claim readback from code; ask Owner for a safe verification of semantics without exposing credentials;
- verify active API uses comma-separated origin allowlist, origin deny 403, permitted origin echo and OPTIONS 204;
- check existing frontend works on its original workers.dev host.

If API CORS implementation or value cannot be established, HOLD. Do not assume source configuration equals deployment.

Suggested read-only metadata commands (run in Owner's authenticated local project checkout):

```sh
cd "$HOME/Downloads/HoloViewer"
npx wrangler whoami
npx wrangler deployments list --name holoviewer-public
npx wrangler deployments list --name holoviewer-public-api
cat cloudflare/wrangler.json
git status --short
```

## Gate 1 — update existing API allowed origins (Owner only)

Preserve **every** existing allowed origin, appending `https://holodocchi.com` exactly once. Minimum both entries:

```text
https://holoviewer-public.singlebagel.workers.dev,https://holodocchi.com
```

**This is an example, not a verified Production readback.** Do not overwrite other existing origins. Confirm whether `ALLOWED_ORIGIN` is a plain var or a secret, and use the Owner-approved method that preserves all existing API bindings/secrets. Wrangler deployments can overwrite Dashboard-managed plain vars unless explicitly retained/configured. No new backend deploy pipeline is permitted.

After applying, test one endpoint with **three** origins. `/health` is preferred to avoid D1 reads:

```sh
API=https://holoviewer-public-api.singlebagel.workers.dev
for ORIGIN in https://holoviewer-public.singlebagel.workers.dev https://holodocchi.com https://unrelated-origin.invalid; do
  echo "Origin=$ORIGIN"
  curl -sS -D - -o /dev/null -H "Origin: $ORIGIN" "$API/health"
done
curl -sS -D - -o /dev/null -X OPTIONS -H 'Origin: https://holodocchi.com' -H 'Access-Control-Request-Method: GET' "$API/health"
```

Expected: legacy/new origins allowed with matching `Access-Control-Allow-Origin`; unauthorized origin denied 403, not granted wildcard CORS; authorized OPTIONS 204. Abort on mismatch. Recheck legacy frontend browser functionality before continuing.

## Gate 2 — deploy existing frontend Worker with codified domain (Owner only)

After source review and merge to Owner's intended deploy branch, verify `cloudflare/wrangler.json` matches the approved diff. Existing Owner frontend workflow stays unchanged:

```sh
cd "$HOME/Downloads/HoloViewer"
git status --short
git rev-parse HEAD
cat cloudflare/wrangler.json
cd cloudflare
npx wrangler deploy
```

**This deploy changes live routing/config.** Execute only after explicit Owner signoff and a clean-worktree / approved-HEAD check. Do not paste these commands into GitHub Actions. Do not separately create a DNS A, AAAA or CNAME; Custom Domain automatically provisions the appropriate DNS record and TLS. Do not change DNSSEC/nameservers.

Before using an already-installed Dashboard custom domain, inspect for conflict; if such a binding is present, pause to reconcile rather than duplicating it.

## Gate 3 — verification

```sh
dig +short holodocchi.com A
dig +short holodocchi.com AAAA
dig +short holodocchi.com DS
curl -sSI https://holodocchi.com/
curl -sSI https://holoviewer-public.singlebagel.workers.dev/
curl -sSI http://holodocchi.com/
openssl s_client -connect holodocchi.com:443 -servername holodocchi.com </dev/null 2>/dev/null | openssl x509 -noout -subject -dates -ext subjectAltName
```

Caveats: apex DS query is not sufficient to prove DNSSEC; confirm authoritative Cloudflare DNSSEC Active and parent DS / external validated resolution. HTTP->HTTPS behavior is an observed acceptance, not assumed.

Browser smoke on **both** hosts, with DevTools Network/Console:
- homepage Today;
- `/history`, `/watchalong`, `/watchalong/session`, `/custom-view`, `/collab`, `/ptt-today/`;
- standalone `/viewer/?...` and `/watchalong-viewer/?...`;
- direct deep link and hard refresh;
- PTT Today + historical manifest/static objects;
- Watchalong data and YouTube iframe/player;
- share links use `holodocchi.com` on new host;
- no CORS/CSP/mixed-content errors;
- API URL and PTT archive origins remain their workers.dev URLs;
- TLS certificate covers apex and browser trusts certificate;
- DNSSEC remains active;
- legacy workers.dev stays accessible and functional;
- no D1/Collector/Publisher/Static Worker changes.

Defer `www` entirely. No legacy frontend redirect.

## Rollback — two different failures

**Domain-only/DNS/TLS trouble:** keep original workers.dev frontend active. If necessary, remove the new Custom Domain binding from `holoviewer-public` using the Cloudflare Dashboard, under explicit Owner control; do not change the API or D1. Reconcile the Wrangler routes config afterwards before the *next* frontend deploy, so the domain is not silently rebound.

**Frontend code/config deployment regression:** rollback the *frontend Worker only* to the captured previous version:

```sh
cd "$HOME/Downloads/HoloViewer/cloudflare"
npx wrangler rollback PREVIOUS_FRONTEND_VERSION_ID --name holoviewer-public
```

This is a **live deployment action**; use only with explicit Owner approval. Version rollback may affect active code and its routing: verify both hostnames after rollback; do not assume it removes a custom-domain binding. If CORS change itself is the issue, Owner separately restores the prior API variable/config via the approved API deploy method. Keep legacy allowed until the new host is stable.

## Subsequent normal deploy invariants

Frontend: existing `holoviewer-public` deploy process and `cloudflare/wrangler.json` continue to own the domain + `workers_dev: true`. No second pipeline.

Backend: existing `holoviewer-public-api` deploy process continues unchanged. **Persist the new origin in the actual long-lived API variable/config source of truth**, or configure proven keep-vars semantics; a future API deploy must not overwrite it. Check legacy and apex CORS after each future backend deploy.

## Release hold

Do not execute Gate 1/2 until Owner has supplied actual API variable readback, confirmed its persistence across backend deploys, recorded rollback versions, and approved source. Current issue #176 source alone is insufficient proof of live API configuration.
