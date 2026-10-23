# YouTube Static Assets Gate-3 Version URL pilot

Issue: physicsdog0505/Hololive-PTT-Viewer#448

## Purpose

Validate the accepted local `youtube/v1` serving tree through the same
`holoviewer-public` Cloudflare Workers Static Assets packaging path without
switching Production traffic.

This is an Owner-local release test. It does not use R2 and it does not use
GitHub Actions.

## Publication mechanism

The pilot uses:

```text
wrangler versions upload
```

not:

```text
wrangler deploy
wrangler versions deploy
```

A version upload creates a new Worker Version and Version URL but does not make
that version an active deployment. The runner records the active Production
deployment before upload and requires the same active version after HTTP
readback.

The static assets themselves are staged by copying the checked-in `site/`
tree and adding the already accepted Owner-local `youtube/v1` tree. A
temporary Wrangler configuration is derived from the authoritative
`cloudflare/wrangler.json`; only the assets directory is redirected to that
temporary staged site.

## Readback contract

The exact Version URL returned by Wrangler is used to fetch:

- `youtube/v1/manifest.json`;
- every month object declared by the manifest;
- every channel index declared by the manifest.

The verifier requires:

- byte length and SHA-256 to equal the accepted local manifest;
- JSON schema version 1;
- month video counts to match manifest counts;
- channel index `channel_id` to match the manifest;
- channel index `video_count` to equal the total IDs in its month map.

Cache-busting query parameters are used for every HTTP request.

## Production-safety proof

Acceptance requires the same active deployment version before and after the
Version upload.

The uploaded pilot version remains inert unless a separate explicit command is
later run to deploy it. The Gate-3 runner never calls either
`wrangler deploy` or `wrangler versions deploy`.

An uploaded test version does not need a production rollback because it never
receives Production traffic. A later `versions upload --preview-alias ...`
may replace the test alias with a newer inert version. Production rollback
remains the existing deployment-history mechanism and is not exercised by this
Gate-3 pilot.

## Forbidden in this pilot

- R2 enablement or R2 object writes;
- Production traffic switch;
- Production API Worker deployment;
- D1 mutation;
- frontend code cutover to the YouTube catalog;
- scheduler activation;
- GitHub Actions deployment.
