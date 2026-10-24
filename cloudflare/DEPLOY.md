# HoloViewer Cloudflare production deployment

This deploys Static Assets to the existing frontend Worker `holoviewer-public`.

Authoritative ownership:

```text
holoviewer-public
  -> frontend-owned site assets
  -> explicitly owned frontend data such as data/watchalong/** and data/search/aliases/v1/**

holoviewer-youtube-static-assets
  -> youtube/v1/**

holoviewer-ptt-static-assets
  -> ptt/v1/**
```

The frontend release must never stage or preserve `youtube/v1/**` or `ptt/v1/**`.

## Deployment authority

Production deploy and rollback are Owner-local only.

- GitHub Actions / CI: passive evidence only.
- No automatic deploy on push or merge.
- No CI-triggered Wrangler mutation.
- No D1/API/Collector/Publisher/R2 mutation from this frontend release path.

## Required entrypoint

From an exact reviewed release SHA already contained in `origin/main`:

```sh
./scripts/run_public_frontend_owner_release.sh <exact-reviewed-release-sha>
```

Default behavior is PREPARE_ONLY. It verifies:

- exact clean checkout;
- release SHA contained in current `origin/main`;
- no `site/youtube/v1/**`;
- no `site/ptt/v1/**`;
- frontend-owned Watchalong manifest is present;
- Alias pointer is present when the Alias dataset directory exists;
- Wrangler still targets `holoviewer-public` with `../site`;
- current active Worker version can be read.

PREPARE exits with:

```text
PUBLIC_FRONTEND_RELEASE_PREPARE=PASS
PRODUCTION_MUTATION=NO
DEPLOY=NO
```

## Explicit EXECUTE

Only after the Owner reviews the exact PREPARE output and approves the captured active Worker version:

```sh
./scripts/run_public_frontend_owner_release.sh \
  <exact-reviewed-release-sha> \
  --execute \
  --expected-active-version <approved-active-version>
```

EXECUTE repeats all gates and refuses deployment if the active Worker version changed since approval.

After a successful deploy it prints the prior active version as the rollback target. It never auto-rolls back.

## Incident rule from #201

Do not build a frontend staging directory by copying dedicated YouTube/PTT assets into `site/` or into a temporary complete-site bundle.

The source tree itself is the ownership boundary. A frontend release containing foreign-owner paths must fail closed.

## Production acceptance

After deployment, verify at minimum:

- custom domain and workers.dev serve the same accepted frontend;
- the intended frontend delta is present;
- Watchalong frontend-owned data remains readable;
- dedicated YouTube and PTT targets remain independently healthy;
- no D1/API Worker mutation occurred.

The absence of foreign-owner paths in the frontend release candidate is the source-of-truth contract; dedicated data targets are not copied back into `holoviewer-public`.
