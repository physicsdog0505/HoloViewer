# HoloViewer Cloudflare production deployment

This deploys static assets to the **existing** Worker `holoviewer-public`.
It does not deploy `holoviewer-public-api`, alter D1, or touch PTT Workers.

## Initial setup (once)
1. In GitHub `physicsdog0505/HoloViewer` → Settings → Secrets and variables → Actions, add secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Never paste tokens into chat, issues, logs, or source files. Create a Cloudflare API token restricted to this account's Workers Scripts Edit/deployment permissions. Review the token's actual permissions in Cloudflare.
2. If using protected GitHub Environment `cloudflare-production`, create it under Settings → Environments. Configure reviewers for production approval if available. The workflow refers to this environment.
3. The actual approved static site must be checked into `site/` with index.html and assets. Until this folder is committed **and validated**, the deploy workflow is intentionally blocked by file checks.
4. Merge this workflow only after review; workflow_dispatch runs from the repository default branch. Open Actions → Deploy HoloViewer Cloudflare production → Run workflow (branch main), input **DEPLOY**.
5. Open https://holoviewer-public.singlebagel.workers.dev/ and check sidebar, navigation, API request URLs, individual and multi-player behavior. Check Worker deployment logs and browser network errors.

## Important boundaries
- GitHub Actions on public standard hosted runners is ordinarily free; Cloudflare usage is separate.
- Existing Cloudflare Worker names: website `holoviewer-public` and API `holoviewer-public-api`. API D1 binding is `DB` → `holoviewer-public-v1`.
- No automatic production deploy on push, no implicit D1 writes or migration.
- Current static 4174 shell is **not complete functional parity**; do not present deploy success as full product acceptance.
- Roll back via Cloudflare worker deployment history / prior known-good site commit, not by blindly running a new head.
