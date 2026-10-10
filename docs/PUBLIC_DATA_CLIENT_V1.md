# Public data client v1

This branch is a read-only GitHub Pages candidate. It does not publish production data or replace any private owner.

`public-data/config.json` is the only browser entry point. Every source is either same-origin or HTTPS, has no credentials, and is fetched with an eight-second timeout, a two-MiB ceiling (32 KiB for config), fatal UTF-8 decoding, and `credentials: omit`. Missing, stale, partial, corrupt, or incompatible data is shown explicitly and does not block unrelated playback.

The checked-in `public-data/demo/` files are synthetic fixtures. Their timestamps and identities are not operational evidence. A real-data publication requires a separately reviewed exporter, rights audit, immutable artifact publication, browser acceptance, and human approval.

## Data planes

- Homepage is a bounded slow JSON artifact. `completeness=partial` means absence is indeterminate.
- PTT uses a slow article/push baseline and may optionally poll the Issue #296 relay v1 shape (`pushes`, `next_cursor`, `has_more`, `checked_at`). Relay entries deduplicate by stable `push_id`; bounded pagination and cursor validation fail closed, while transport failure preserves the baseline and last valid relay state.
- Watchalong uses lightweight session references and separately published, rights-approved completed transcript/translation artifacts. Writable bodies remain owned by their source stores. Automatic follower playback is disabled by default.
- Live Sync accepts one public YouTube URL/ID. Video initialization is independent of PTT availability. Multi-stream layout remains deferred.

No browser code discovers local databases, reads environment variables, stores credentials, mutates source artifacts, or calls the private Mac. The Pages workflow includes these files in its bounded artifact, but this branch is not configured to deploy automatically; deployment remains a human gate.

## Deployed live relay preview

The preview config points `sources.live_relay` at the deployed read-only Cloudflare Worker endpoint.

Live Sync acceptance can bind a specific canonical public PTT AID independently of the slow snapshot by adding `aid=<public-aid>` to the session URL together with `stream=<youtube-id-or-url>`. This path is read-only and is intended for validating real relay motion beside video before the historical public snapshot is cut over.

Example shape:

`custom-view/session/?stream=<youtube-id>&aid=1gntGd6b`

The AID query value is restricted to the public relay contract shape. Invalid values are ignored and the client falls back to the configured historical snapshot article.
