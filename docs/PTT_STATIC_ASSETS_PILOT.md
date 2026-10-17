# PTT Historical Static Assets Pilot — Offline Review

Date: 2026-10-18 Asia/Taipei
Issue: #137
PR: #135 (`feature/ptt-r2-archive-pilot`)
Baseline: `b5130201c29cb330e59f8a2f08eb22c35d274eed`

## Decision

**Static Assets architecture: conditional GO. Deployment of the original
floor-less artifact: NO-GO. The independently audited floor-enriched artifact
is a deployment candidate only after PR review and explicit owner approval.**

The asset-only path, headers, browser decoding, absolute-time resolver and real
VOD mapping pass offline. The durable 2026-10-01..17 archive does not contain a
`floor` field, so it cannot meet the owner requirement to reproduce correct PTT
floor numbers. A floor-only derived rebuild passes locally while preserving the
exact 54,886 source identities and has passed an independent source/database
audit. It has not replaced the original artifact or been deployed.

## Evidence classification

- **VERIFIED:** current archive files, local SQLite inventory, code/tests,
  local HTTP responses and headless Chrome behavior.
- **VERIFIED OFFLINE ONLY:** Static Assets-compatible package and resolver.
- **NOT VERIFIED:** Cloudflare upload/deploy behavior on this account, remote
  headers/cache/CORS, production browser integration, 8501/4174 presentation,
  owner acceptance, and transcript byte sizes.
- **NOT DEPLOYED:** no Cloudflare, R2, Worker, D1, frontend or production change.

## Existing archive audit

Source:
`~/Documents/HoloViewer-Historical/r2-archive-pilot/2026-10-01_2026-10-17`

| Check | Result |
| --- | --- |
| Schema / precision | `ptt-r2-archive-v1`, UTC minute, seconds `:00` |
| Pushes / hourly objects | 54,886 / 371 |
| Hourly gzip bytes | 2,073,302 |
| Time range | 2026-09-30T16:00:00Z..2026-10-17T10:46:00Z |
| AID / source identity | Preserved |
| `source_line` / `source_page` | Preserved |
| Original per-thread `floor` | **Missing on all 54,886 rows** |
| Duplicate `source_record_key` | 0 |
| Invalid timestamps | 0 |
| Rejected articles / rows | 0 / 0 |
| Local gzip/JSON/manifest audit | PASS |
| Coverage | 14 COMPLETE days, 2 UNKNOWN, 1 PARTIAL |

UNKNOWN is retained for 2026-10-10 and 2026-10-13 because night-thread tail
completeness is unproven. 2026-10-17 remains PARTIAL because the artifact is a
same-day snapshot. Neither state is promoted to COMPLETE.

The known AID `1goCKi_z` chronology regression is preserved, not repaired:
floor 3/source line 212 is 10:46Z, while floor 4/source line 235 is 10:43Z and
has `time_quality=source-minute-regression`. Timeline sorting uses
`occurred_at`; floor remains the thread ordinal.

## Floor-only correction

The exporter now distinguishes:

- `source_line`: source HTML/storage identity;
- `floor`: one-based ordinal within one AID;
- `floor_quality=per-thread-ordinal`: thread-start evidence exists;
- `floor=null`, `floor_quality=unknown`: ordinal cannot be proven.

Floor is derived from the complete ordered push set for one AID only when
`source_page <= 1` or an `article_screens.start_line <= 1` record proves the
thread beginning was captured. It never resets at an hourly boundary, resets to
1 for a new AID, and is never copied from `source_line`.

The fixed-row-set derived artifact is preserved outside Git at:
`~/Documents/HoloViewer-Historical/static-assets-pilot-review-20261018/artifacts/archive-floor-only`

| Check | Result |
| --- | --- |
| Source manifest SHA-256 | `b24215fd07f5bc679d573312f481bd9b89348438a63da702e00787f8034fd27b` |
| Pushes / objects | 54,886 / 371 (unchanged) |
| Identity set preserved | PASS |
| Known / unknown floors | 54,886 / 0 |
| Duplicate identities / AID floors | 0 / 0 |
| Corrected hourly gzip bytes | 2,294,691 |
| Corrected chunks + manifest bytes | 2,427,204 |

An independent audit re-read both source SQLite databases without calling the
exporter's floor helper. It rebuilt AID-local ordinals from complete ordered
push sets only when `source_page <= 1` or `article_screens.start_line <= 1`
proved the thread beginning. All 54,886 derived rows matched this independent
result. Immutable source fields had zero differences, 34 AIDs spanning multiple
UTC chunks retained one continuous floor sequence, and no row happened to use
`source_line` as its floor. The complete receipt is stored as
`INDEPENDENT_FULL_AUDIT.json` beside the preserved artifacts.

A direct re-export from the still-running operational database was rejected as
a replacement strategy: it produced 57,405 rows because 2026-10-17 had grown
after the original snapshot. The accepted correction enriches only the exact
rows named by the original manifest.

## Static Assets package

Offline package:
`~/Documents/HoloViewer-Historical/static-assets-pilot-review-20261018/artifacts/static-package`

Selected corrected chunks:

| Status | Key | Pushes | gzip bytes |
| --- | --- | ---: | ---: |
| COMPLETE | `ptt/v1/chunks/2026/10/05/0900.json.gz` | 17 | 1,339 |
| UNKNOWN | `ptt/v1/chunks/2026/10/09/1600.json.gz` | 208 | 9,312 |
| PARTIAL | `ptt/v1/chunks/2026/10/16/1600.json.gz` | 25 | 1,580 |

The project has no `main` Worker script, bindings, D1, R2 or secrets. The
declarative asset rules provide:

- gzip chunks: `Content-Type: application/json`, `Content-Encoding: gzip`;
- manifest: JSON UTF-8;
- CORS: `Access-Control-Allow-Origin: *` for this public data pilot;
- chunks: `public, max-age=0, must-revalidate`;
- manifest: `no-cache`.

The conservative revalidation policy is required because UNKNOWN/PARTIAL chunks
are replaceable at the same URL. COMPLETE chunks may use long immutable caching
only after URLs are fingerprinted/versioned. A consumer must verify the
decompressed object SHA against its manifest and retry the manifest once on a
mismatch. A release path containing the manifest digest is the preferred
long-term way to prevent old-manifest/new-chunk mixing.

Local integration results:

- HTTP header, gzip, JSON and row-count readback: PASS.
- Headless Google Chrome `fetch()` auto-decompression and `response.json()`:
  PASS (`data-status=pass`, 17 rows).
- Static route bypass: PASS by construction and configuration; there is no
  executable Worker or database binding. Remote Cloudflare routing remains NOT
  VERIFIED until a separately approved test deploy.

## Real VOD timeline receipts

`actual_start` and `actual_end` come from the existing Stream Catalog. The
catalog ingestion maps YouTube `liveStreamingDetails.actualStartTime` and
`actualEndTime`; scheduled/published time was not substituted.

### Normal, single UTC-hour VOD

- Video: `62AgiXDP3tU`
- Window: 2026-10-05T12:01:05Z..12:54:31Z
- Coverage: COMPLETE
- Objects / bytes: 1 / 51,353
- Result: 1,428 pushes, duplicate identities 0
- AID `1gmuCoM5`, floors 341..1768, times 12:02..12:54Z

### Cross-hour and thread rollover VOD

- Video: `FVpLKAiHYFA`
- Window: 2026-10-09T10:00:05Z..11:29:38Z
- Coverage: COMPLETE
- Objects / bytes: 2 / 13,201
- Result: 219 pushes, duplicate identities 0
- AID `1go23y_5`: 57 pushes, floors 633..689
- AID `1goCKi_z`: 162 pushes, floors 1..162
- The day/night AID switch is preserved; floor resets on the new AID, not at
  11:00 UTC.

### Cross UTC date and Taipei date VOD

- Video: `pwJeqkeHtPM`
- Window: 2026-10-04T15:29:35Z..2026-10-05T00:35:17Z
- Coverage days: 2026-10-04 and 2026-10-05, both COMPLETE
- Objects / bytes: 9 / 19,428; one manifest-absent empty UTC hour
- Result: 156 pushes, duplicate identities 0
- AIDs/floors: `1gmYseVG` 3479..3605, `1gmDmbyt` 2052,
  `1gmObGG0` 853, `1gmjfpy4` 1..27
- The empty 18:00 UTC hour is not fabricated as a file; COMPLETE day metadata
  establishes that it contains zero archived pushes.

Separate degraded-status checks:

- `jCy5SoVLZqo` on 2026-10-10: 616 rows returned, status UNKNOWN,
  `strict_complete=false`.
- `ZqVH1jonmgM` on 2026-10-17: 204 rows returned, status PARTIAL,
  `strict_complete=false`.

Rows remain useful in degraded coverage, but the viewer must show a coverage
warning and never claim the timeline is complete.

The five-case regression was rerun after the resolver began requiring
`anchor_source=youtube-liveStreamingDetails-actualStartTime`. A deliberately
untrusted `scheduledStartTime` anchor is rejected by a dedicated regression
test. The full five-VOD receipt is preserved as `VOD_REGRESSION.json`.

## Capacity and packaging measurements

Corrected archive measurements:

| Packaging | Objects | gzip bytes | Largest object |
| --- | ---: | ---: | ---: |
| UTC hourly | 371 | 2,294,691 | 55,404 |
| Repacked UTC daily | 18 | 2,095,089 | 193,945 |

Daily packing saves 199,602 bytes and 353 files for this sample, but causes
large per-VOD overfetch:

| VOD | Hourly bytes | Daily bytes needed |
| --- | ---: | ---: |
| `62AgiXDP3tU` | 51,353 | 119,638 |
| `FVpLKAiHYFA` | 13,201 | 108,406 |
| `pwJeqkeHtPM` | 19,428 | 291,967 |

Keep hourly UTC chunks as the canonical PTT contract for now. Daily packaging
is a future deployment optimization only if the viewer gains byte-range/index
support or measured request overhead outweighs overfetch.

Current Cloudflare documentation states:

- Free Workers versions: 20,000 static asset files; Paid: 100,000;
- individual static asset: 25 MiB;
- `_headers`: 100 rules, 2,000 characters per line;
- matching static asset requests are free/unlimited and asset storage has no
  additional charge; Worker-script requests remain billable;
- static assets, configuration and code are captured together in a Worker
  version.

Sources: [Static Assets billing and limitations](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/),
[platform limits](https://developers.cloudflare.com/workers/platform/limits/),
[headers](https://developers.cloudflare.com/workers/static-assets/headers/),
[routing](https://developers.cloudflare.com/workers/static-assets/routing/worker-script/),
[versions and deployments](https://developers.cloudflare.com/workers/versions-and-deployments/).

The observed hourly rate is 371 files per 17 Taipei coverage days, about 7,965
files/year if traffic stays similar. That gives roughly 2.5 years before a
20,000-file version limit, without counting manifests or other assets. This is
not a storage-GB guarantee.

The same 17-day inventory contains 781 streams and 778 authoritative ended
windows. One transcript file per stream would add roughly 16,700 files/year at
this observed rate; translations or segmented transcripts multiply that count.
No representative production transcript corpus was available, so transcript
bytes are UNKNOWN. PTT plus one-file-per-stream transcripts would exceed the
Free 20,000-file limit in about a year at the observed rate. Transcripts should
therefore use aggregation, a separate versioned asset project, or another
approved storage design after real byte measurements.

## Public Viewer integration contract

1. Require `anchor_source=youtube-liveStreamingDetails-actualStartTime` and
   timezone-aware `actual_start` / `actual_end`; reject scheduled, published,
   inferred, or otherwise untrusted anchors.
2. Fetch a revalidated manifest; reject an unsupported schema.
3. Determine intersecting UTC hours, fetch manifest-listed objects only, and
   verify decompressed SHA/count/bucket bounds.
4. Filter exact `[actual_start, actual_end)` and compute
   `floor((occurred_at-actual_start)/60s)`.
5. Deduplicate by `source_record_key`; sort by absolute `occurred_at`, then AID,
   proven floor and `source_line` tie-breakers.
6. Display `floor` only when non-null. Never substitute `source_line`.
7. Preserve AID and source URL across day/night thread rollover.
8. Claim completeness only when every intersected Taipei coverage day is
   COMPLETE. UNKNOWN/PARTIAL remain visible with an explicit warning.
9. Do not call the Live Worker API or D1 for ended historical VODs.
10. On SHA mismatch, discard the response, refetch the manifest once, then fail
    closed with a retryable archive-version error.

## Tests

Command:

```text
python3 -B -m unittest -v \
  ptt_offline.test_r2_archive_export \
  ptt_offline.test_static_assets_pilot
```

Result: 14 tests PASS. Coverage includes floor provenance/reset/gaps/hour
boundaries, unknown floor behavior, deterministic gzip, timezone rejection,
asset-only configuration, headers, gzip/JSON readback, fixed identity floor
enrichment, cross-hour/date resolver behavior, duplicate suppression and
PARTIAL handling. The added test verifies that the resolver rejects any anchor
authority other than YouTube `liveStreamingDetails.actualStartTime`.

## Proposed separately approved test deployment

Do not run these commands without owner approval and a confirmed free-plan
account target:

```text
python3 -B -m ptt_offline.static_assets_pilot build-bundle \
  --archive-root /path/to/reviewed-floor-archive \
  --out-dir ptt_offline/static_assets_pilot/public \
  --object ptt/v1/chunks/2026/10/05/0900.json.gz \
  --object ptt/v1/chunks/2026/10/09/1600.json.gz \
  --object ptt/v1/chunks/2026/10/16/1600.json.gz

npx wrangler deploy --config ptt_offline/static_assets_pilot/wrangler.jsonc
```

The deployment name is isolated: `holoviewer-ptt-static-assets-pilot`. It must
not share production routes, bindings, domains or secrets. Remote acceptance
must check exact HEAD/version ID, all headers, real browser fetch, SHA/readback,
cache revalidation, missing-file behavior, and confirm Worker invocation/D1
metrics remain zero before any larger package is considered.
