# Alias Static Assets forward-only release

This runbook extends the project-wide #201 production-preservation contract for
the Owner-managed Alias dataset.

## Purpose

Deploy only:

- `site/data/search/aliases/v1/latest.json`
- one new immutable `site/data/search/aliases/v1/versions/<sha256>.json`

while preserving:

- accepted repo-owned Production frontend bytes;
- independently published Production `youtube/v1/**` Static Assets;
- the previous published Alias immutable asset for rollback;
- Worker routes/config/triggers.

This is an Owner-local Cloudflare Workers Static Assets release. It does not
write D1, API, Collector, Publisher or R2.

## Required release shape

The reviewed release commit must differ from the accepted Production site
source only by the two Alias paths above. If unrelated `site/**` files differ,
the gate stops. Make a bounded forward-port release commit rather than
smuggling unrelated frontend changes into an Alias publication.

The Alias pointer must reference a new immutable payload whose exact bytes hash
to the filename SHA-256.

## PREPARE mode — no Production mutation

From an exact reviewed commit already contained in `origin/main`:

```sh
./scripts/run_alias_static_assets_release.sh \
  <exact-reviewed-release-sha> \
  <accepted-production-site-source-sha>
```

PREPARE mode:

1. verifies exact checkout and clean tree;
2. verifies the release is already contained in current `origin/main`;
3. verifies Wrangler config is unchanged versus accepted Production source;
4. reconciles every repo-owned Production site file (excluding runtime-owned
   `youtube/v1/**` and Alias paths) against `https://holodocchi.com`;
5. materializes the accepted Production `site/` source tree;
6. overlays only the reviewed Alias pointer + immutable object;
7. downloads and hash-validates every object declared by current Production
   `/youtube/v1/manifest.json` into the staged candidate;
8. preserves the current Production Alias immutable object when present;
9. creates a temporary Wrangler config pointing at the complete staged site;
10. validates the public-safe Alias schema, unique channel IDs and SHA contract;
11. captures the active Worker version read-only;
12. writes a preflight evidence receipt;
13. exits with `PRODUCTION_MUTATION=NO`.

PREPARE is the required engineering/test gate before any deployment approval.

## EXECUTE mode — separate Owner approval

Only after the Owner approves the exact PREPARE receipt and active Worker
version:

```sh
./scripts/run_alias_static_assets_release.sh \
  <exact-reviewed-release-sha> \
  <accepted-production-site-source-sha> \
  --expected-active-version <approved-worker-version> \
  --execute
```

EXECUTE repeats the full preflight, requires the active version to still equal
the approved version, and only then performs Owner-local `wrangler deploy`
using the staged complete site.

Post-deploy it performs bounded readback against both:

- `https://holodocchi.com`
- `https://holoviewer-public.singlebagel.workers.dev`

It verifies:

- Alias pointer SHA;
- immutable Alias bytes;
- all Production YouTube manifest-declared objects;
- a new active Worker version exists.

It writes a final receipt with the captured rollback target and command.

There is no automatic redeploy and no automatic rollback.

## Why Production baseline source is explicit

Production can contain runtime-owned Static Assets that are not represented by
an arbitrary moving repo checkout. The release therefore begins from the
accepted Production source SHA, then composes:

```text
accepted Production repo-owned site
+ current Production runtime YouTube assets
+ current previous Alias immutable
+ reviewed Alias delta
= complete deployment candidate
```

This avoids a plain `wrangler deploy` from accidentally rolling back unrelated
Production frontend bytes or deleting independently published YouTube assets.

## Boundaries

- GitHub Actions / CI: passive evidence only.
- No Production deploy from a PR head.
- Release SHA must already be contained in `origin/main`.
- No D1/API/Collector/Publisher mutation.
- No R2.
- No History Search or Collab behavior change.
- No automatic merge.
- Production deployment remains an explicit Owner decision.
