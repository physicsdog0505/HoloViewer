# HoloViewer Cloudflare production deployment

This deploys static assets to the **existing** Worker `holoviewer-public`.
It does not deploy `holoviewer-public-api`, alter D1, or touch PTT Workers.

## Initial setup (once)
1. In GitHub `physicsdog0505/HoloViewer` → Settings → Secrets and variables → Actions, add secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Never paste tokens into chat, issues, logs, or source files. Create a Cloudflare API token restricted to this account's Workers Scripts Edit/deployment permissions. Review the token's actual permissions in Cloudflare.
2. Create protected GitHub Environment `cloudflare-production` under Settings → Environments. Enable required reviewers where available and limit deployment to main. GitHub settings, not YAML alone, must enforce this; verify actual protection before any deploy.
3. The static site is checked into `site/`. This is a **partial** UI release and may have broken features; partial rollout is accepted by the owner, but security, public-domain data and licensing boundaries are mandatory.
4. **Before first deploy** capture screenshots/export of current `holoviewer-public` Worker settings, compatibility date, routes, bindings, assets and deployment version; confirm intended static-assets Wrangler config will not silently remove needed settings. Retain rollback deployment/version evidence. If baseline cannot be obtained or differs, STOP; do not dispatch.
5. Merge after security review and matching-head CI. For manual release use GitHub Actions on main: `confirm=DEPLOY`, `release_sha=<full reviewed main commit SHA>`, `baseline_confirmed=BASELINE-CHECKED`. Incomplete inputs or mismatched SHA fail closed. This is not a claim that the YAML can independently inspect Cloudflare's Worker configuration.
6. Open https://holoviewer-public.singlebagel.workers.dev/ and check sidebar, navigation, API request URLs, individual and multi-player behavior. Check Worker deployment logs and browser network errors.

## Important boundaries
- GitHub Actions on public standard hosted runners is ordinarily free; Cloudflare usage is separate.
- Existing Cloudflare Worker names: website `holoviewer-public` and API `holoviewer-public-api`. API D1 binding is `DB` → `holoviewer-public-v1`.
- No automatic production deploy on push, no implicit D1 writes or migration. Store no private SQLite dumps, third-party copyrighted video/transcript/chat bulk mirrors, internal-only member information, or credentials in public repo or static files. Only publish source-compliant, explicitly approved metadata; provide attribution / notices and respect content takedown requests.
- Public Worker API must remain read-only on unauthenticated routes; review CORS, abuse/rate limits, query bounds, error redaction and source/licensing policy separately before exposing new endpoints.
- Protection verification is a human gate; the Cloudflare API token must be scoped minimally and rotated if ever exposed.
- Current static 4174 shell is **not complete functional parity**; do not present deploy success as full product acceptance.
- Roll back via Cloudflare worker deployment history / prior known-good site commit, not by blindly running a new head.
