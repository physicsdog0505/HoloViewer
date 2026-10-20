# 8501 Admin Dashboard fixture-only UI / UX acceptance

Status: **offline / fixture-only / read-only**. No running 8501 mount and no Production data connection.

## UI hierarchy

The Admin surface now follows:

1. summary cards / action-needed counts;
2. day, component or job rows;
3. structured expandable evidence;
4. raw sanitized evidence at the bottom of the drilldown.

There are no writer, retry, replay, repair, deploy, upload or restart controls.

## Data Coverage

Visible states:
- COMPLETE
- LOCAL_MISSING
- PENDING_SYNC
- PARTIAL
- CONFLICT
- UNKNOWN

Filters:
- status / action-needed
- date range
- AID/date search
- ascending / descending day order

Day drilldown preserves sanitized expected/actual/missing AIDs, split/all-day/thread evidence, source-line ranges/gaps, legal-empty-push evidence, target readback state, source revision, expected-AID authority and contract gaps.

COMPLETE remains governed by the reviewed Python contract and the browser fallback mirrors it: bounded samples and legacy `verified=true` cannot promote COMPLETE; exact day and expected-AID scope are required.

## Sync Monitor

Main rows show:
- Publisher
- D1 Snapshot
- Archive

Archive is target-neutral: it does not assume R2. Missing #48 Archive Delivery Job Evidence stays UNKNOWN with an explicit contract gap.

The Archive row separates:
- archive data coverage;
- delivery job status;
- expected-AID authority.

The future `holoviewer-archive-job-evidence-v1` consumer slot accepts target kind (for example workers-static-assets or r2), job/source/manifest identities, attempt/success counts, readback, verification, coverage and contract gaps without inventing missing evidence.

D1 Snapshot keeps job_id, snapshot_id, manifest_digest and source_revision distinct and surfaces bounded-read cost evidence: verification mode, query/row/page limits, rows_read and cache hit/miss.

## System Health

Collector, Publisher, Archive and Production API are separate components.

Production API:
- reachability and semantic status are separate;
- HTTP 200 can coexist with semantic degraded;
- HTTP 503 is displayed as 503;
- missing health probe displays no synthetic status;
- stale/unknown semantic evidence never becomes healthy.

## Refresh and last-good

- full and per-section **重新整理** only;
- 30-second UI cooldown remains UX-only;
- 120-second stale threshold remains display freshness;
- failed refresh retains last-good payload and exposes both current attempted read time and last successful read time.

## Privacy boundary

Before returning a browser payload, the controller applies a final browser sanitizer that removes known secret/content/credential keys and replaces local absolute filesystem paths. Valid evidence fields such as `content_hash` and API paths such as `/health` are retained.

## Browser acceptance receipt

An isolated headless Chromium harness was used with sanitized fixture envelopes and the Admin render behavior; it did not touch running 8501 or any production source.

Desktop (1440x1000):
- 8 coverage days rendered;
- six coverage summary cards rendered;
- action-needed filter reduced rows from 8 to 7;
- AID search `all-c` returned exactly one PARTIAL day;
- ascending sort started at 2026-10-14;
- all-day thread evidence was visible in drilldown;
- Archive showed UNKNOWN coverage / UNKNOWN AID / unknown job;
- D1 showed `bounded_sample`;
- no writer controls were present;
- Production API displayed HTTP 200 + semantic degraded as separate facts.

System-health fixture variants:
- semantic healthy + HTTP 200 -> healthy;
- semantic degraded + HTTP 503 -> degraded / HTTP 503;
- no health probe -> HTTP status absent;
- unavailable component -> unavailable;
- stale semantic evidence -> stale / unknown, not healthy.

Narrow viewport (390x844):
- document width remained 390px;
- buttons remained inside the viewport;
- the table overflow stayed inside `.table-wrap` rather than widening the page.

## Runtime / production disposition

- running 8501 modified: **NO**
- Production D1 connected: **NO**
- Production R2 connected: **NO**
- Workers Static Assets production reader connected: **NO**
- Static Assets deploy: **NO**
- write action: **NO**

Still HOLD:
- running 8501 mount;
- Production readers;
- least-privilege Production credential;
- cross-process/global production query admission;
- live semantic producer;
- uploader/repair/write controls.

Independent #45 / PR #147 review is still required before any real mount.


## Archive integration convergence (#48 PR #154)

#147 no longer parses raw Archive delivery evidence or legacy R2 manifests. The injected reader now supplies the canonical normalized row produced by #48's `project_archive_as_sync_job()` contract.

Consumer boundary:
- input key: `archive_sync_job`
- component must be `Archive`
- generic Sync Monitor fields are consumed directly
- producer-specific details remain nested under `evidence_source_fields`
- coverage comes only from `coverage_summary.status`
- expected-AID completeness comes only from `expected_aid_completeness.status`
- verification comes only from the producer projection's `verification_mode` / `job_verified`
- missing or invalid normalized evidence remains UNKNOWN with explicit contract gaps

A sanitized consumer fixture derived from PR #154 exact HEAD `d1651e96654c982959ede7678ac6b6582f1f50e7` is stored at:
`fixtures/data-lifecycle/archive-sync-jobs.sanitized.json`.

Regression coverage includes the eight #45 integration cases: COMPLETE manifest without a job, completed delivery with PARTIAL coverage, full-partition job verification, bounded-sample non-verification, missing expected-AID authority, Static Assets labeling, missing evidence, and browser privacy scrub.
