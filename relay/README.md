# Public PTT live relay adapter

This directory contains a **not-deployed** Cloudflare Worker + D1 adapter for the
provider-neutral PTT live-delta contract used by HoloViewer.

It exists because GitHub Pages is read-only: the browser can poll a public GET
endpoint, but the local Collector needs a separate authenticated HTTPS write
endpoint.

## Endpoints

- `POST /v1/ptt/publish`
  - requires `Authorization: Bearer <PUBLISH_TOKEN>`
  - accepts contract-v1 batches (max 200 pushes / 256 KiB)
  - `push_id` is idempotent
  - publisher token is never sent to the browser
- `GET /healthz`
  - public-safe deployment check
  - verifies the D1 binding responds without exposing data
- `GET /v1/ptt?aid=...&after_cursor=...&limit=...`
  - public read-only cursor API
  - max 500 pushes per page
  - matches `assets/cloud-client.js` relay reader
  - emits explicit `checked_at` freshness timestamp

D1 owns the monotonic `cursor`. Rows are retained with a bounded cursor window
(default 100,000 rows; configurable with `RETENTION_ROWS`).

## Human gates

This commit does **not** create a Cloudflare account/resource, configure
`PUBLISH_TOKEN`, bind D1, deploy a Worker, expose the Mac mini, upload real PTT
data, or change production DNS/config.

Before launch:

1. copy `wrangler.example.toml` to a local deployment config and replace the D1 id;
2. create an isolated D1 database and apply `schema.sql`;
3. set a strong Worker secret `PUBLISH_TOKEN` (never in repo/browser);
4. set `PUBLIC_ORIGIN` to the approved HoloViewer Pages origin;
5. deploy the Worker and verify `GET /healthz`;
6. point public `config.json:sources.live_relay` at the GET endpoint;
7. run the approved bounded publisher against the real Collector projection;
8. only after the human deployment gate, leave the local Collector outbound publisher running.

The Mac mini remains outbound-only; no public inbound connection is required.

## Retention-gap contract (review required before live deployment)

The D1 schema now includes `ptt_retention_watermark`, recording the highest purged cursor for each article AID. The Worker records watermarks and purges rows in the same D1 batch transaction, and the public GET adds `history_gap` (boolean) and `purged_through_cursor` (integer). The Pages reader displays an explicit incomplete-data warning if a requested cursor is older than the purge watermark. This **detects** lost relay history but does not automatically recover it; recovery requires a separately refreshed historical projection/snapshot. The v1 response has been extended in lockstep with its Pages validator; upgrade Worker and browser together. Run `relay/schema.sql` migration before starting this Worker version. Retention, concurrent publishing and actual Cloudflare D1 migration must still be integration-tested before enabling real relay traffic.
