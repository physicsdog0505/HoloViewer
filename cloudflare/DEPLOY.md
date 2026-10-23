# HoloViewer Cloudflare production deployment

Production frontend deployment is **Owner-local only**.

This document governs the existing static-assets Worker `holoviewer-public`.
It does not deploy `holoviewer-public-api`, alter D1, or touch PTT Collector/Publisher state.

## Authoritative rule

Production must never be ahead of repository truth.

- Never deploy an unmerged PR head.
- Deploy only an exact, reviewed, already-merged `origin/main` SHA.
- GitHub Actions / CI may provide passive evidence only. They must not mutate Production.
- The Owner runs Wrangler locally from the exact merged checkout.
- Capture the active version before every deploy and retain an immutable rollback target.

## Standard Owner-local entrypoint

For a new additive Watchalong event:

```sh
./scripts/deploy_frontend_owner_local.sh \
  data-watchalong \
  <event-id> \
  <exact-merged-origin-main-sha>
```

The tool is intentionally fail-closed. It:

1. fetches `origin/main` and requires both local HEAD and `origin/main` to equal the requested SHA;
2. rejects a dirty checkout;
3. runs the Watchalong exporter in `--check` mode and regression tests;
4. computes candidate hashes locally;
5. identifies the target event introduction commit and enforces the data-only `site/` allowlist;
6. reads the current Production manifest;
7. requires every existing Production Watchalong event/hash to remain unchanged;
8. requires the target to be absent from Production and present in the candidate;
9. captures the active `holoviewer-public` version and Production manifest hash;
10. deploys with Owner-local Wrangler;
11. performs bounded read-only retries against both:
    - `https://holodocchi.com`
    - `https://holoviewer-public.singlebagel.workers.dev`
12. never automatically redeploys or rolls back after a transient mismatch;
13. writes before/after receipts and prints the exact rollback command.

The default canonical/private Watchalong source root is:

```text
/Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer
```

Override it when needed with:

```sh
HOLOVIEWER_SOURCE_ROOT=/path/to/source \
  ./scripts/deploy_frontend_owner_local.sh data-watchalong <event-id> <main-sha>
```

## Release classes

### Full frontend release

For UI/code/general static-site changes, require:

- exact merged main SHA;
- reviewed site diff;
- applicable regression tests;
- captured active Production version;
- Owner-local Wrangler deploy;
- post-deploy smoke;
- immutable rollback version.

Do not use the Watchalong data-only mode to smuggle unrelated frontend changes.

### Data-only frontend release

For browser-facing derived datasets, require additive preservation against current Production truth.

For the current Watchalong v1 new-event mode:

```text
EXISTING_EVENT_CHANGED=NO
OLD_EVENT_COUNT_PRESERVED=YES
NEW_EVENT_COUNT=1
```

Allowed `site/` delta is exactly:

```text
site/data/watchalong/manifest.json
site/data/watchalong/events/<new-id>.json
```

Any other `site/` change fails closed.

Updating an existing event is a different release class and must explicitly declare which existing IDs are allowed to change. Do not use the new-event path for refreshes.

## Edge/cache handling

A newly activated Worker version may briefly coexist with older cached static bytes at an edge.

Therefore:

- read both custom-domain and workers.dev origins;
- use bounded read-only retry;
- do not issue a second deploy because the first read is stale;
- do not automatically rollback on a transient mismatch;
- investigate or manually rollback only after persistent inconsistency is proven.

## GitHub Actions policy

`.github/workflows/deploy-cloudflare-production.yml` is retained only as **passive release evidence**.

It must not contain:

- Cloudflare API-token usage;
- `cloudflare/wrangler-action`;
- `wrangler deploy`;
- `wrangler rollback`;
- any Production mutation step.

A green workflow is not deployment authorization and is not evidence that Production changed.

## Wrangler local state

`.wrangler/` is local generated state and is ignored by Git. It must not be committed or treated as a release artifact.

## Rollback

Rollback is a deliberate Owner-local action against the captured baseline version:

```sh
npx --yes wrangler rollback <baseline-version> \
  --config cloudflare/wrangler.json \
  --name holoviewer-public
```

Never "rollback" by blindly redeploying an older Git checkout.

## Boundaries

The frontend release path must not mutate:

- `holoviewer-public-api`;
- D1;
- Collector;
- Publisher;
- PTT databases;
- translation/provider policy;
- Watchalong timing behavior.
