# Public data client v1

This branch is a read-only GitHub Pages candidate. It does not publish production data or replace any private owner.

`public-data/config.json` is the only browser entry point. Every source is either same-origin or HTTPS, has no credentials, and is fetched with an eight-second timeout, a two-MiB ceiling (32 KiB for config), fatal UTF-8 decoding, and `credentials: omit`. Missing, stale, partial, corrupt, or incompatible data is shown explicitly and does not block unrelated playback.

The checked-in `public-data/demo/` files are synthetic fixtures. Their timestamps and identities are not operational evidence. A real-data publication requires a separately reviewed exporter, rights audit, immutable artifact publication, browser acceptance, and human approval.

## Data planes

- Homepage is a bounded slow JSON artifact. `completeness=partial` means absence is indeterminate.
- PTT uses a slow article/push baseline and may optionally poll a cursor-based relay. Relay entries deduplicate by stable `push_id`; its failure preserves the baseline and last valid relay state.
- Watchalong uses lightweight session/readiness references only. Transcript and translation bodies remain owned by their source stores. Automatic follower playback is disabled by default.
- Live Sync accepts one public YouTube URL/ID. Video initialization is independent of PTT availability. Multi-stream layout remains deferred.

No browser code discovers local databases, reads environment variables, stores credentials, mutates source artifacts, or calls the private Mac. The Pages workflow includes these files in its bounded artifact, but this branch is not configured to deploy automatically; deployment remains a human gate.
