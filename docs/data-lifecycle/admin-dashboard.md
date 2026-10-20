# PTT History Admin Dashboard — read-only monitoring slice

Status: offline prototype on PR #147. It is not deployed and has no production
reader configured by default.

## Scope and ownership

The dashboard is an internal read-only consumer. It does not replace the #48
Collector/Publisher, the PR #135 archive exporter/uploader, or any production
writer. It consumes PR #147 inventory output and sanitized evidence supplied by
those owners. The package lives under `admin_dashboard/`; `site/**`, the Public
Viewer, and the accepted 4174 runtime are unchanged.

The three tabs are:

1. **Data Coverage** — PR #147 daily inventory/reconciliation data: completeness,
   missing identities, source-line gaps, duplicates, conflicts, unconfirmed
   evidence and repair recommendations. Filters never change source state.
2. **Sync Monitor** — normalized read-only job evidence for Publisher, D1 and R2.
3. **System Health** — Collector, Publisher, Archive and Production API probes.

`重新執行同步` is disabled and design-only. There is no route, callable or
imported writer behind it.

## Read-only contracts

`DashboardController` receives three injected zero-argument reader functions:

| reader | accepted payload | authority |
|---|---|---|
| `data_coverage` | `holoviewer-daily-inventory-v1` or PR #147 reconciliation report | PR #147 |
| `sync_monitor` | sanitized `publisher_checkpoint`, `r2_manifest`, `d1_snapshot`, optional job telemetry | #48 / PR #135 / snapshot owner |
| `system_health` | explicit component probe envelope | component owner |

The package opens no database, socket, subprocess, Cloudflare binding or writer.
The WSGI surface accepts only `GET /admin/status`; other methods return 405. A
host may mount it later only after a separate integration review.

### Observable Sync Monitor fields

Every job always exposes these keys, using `null` plus `contract_gaps` when
evidence is absent:

- `job_id`, `component`, `source`, `target`;
- `last_attempted_at`, `last_successful_at`, `status`;
- `attempt_count`, `retry_after`, `backoff_seconds`;
- `input_count`, `published_count`, `verified_count`;
- `error_code`, sanitized `error_message`, `last_progress_at`;
- `evidence_source`, `evidence_observed_at`, `evidence_freshness`.

Optional telemetry uses `holoviewer-sync-job-evidence-v1`. Error text is dropped
unless its producer sets `error_sanitized: true`; displayed text is bounded to
240 characters and line breaks are removed.

Existing evidence currently yields:

- #48 sanitized checkpoint: job/batch identity, state when supplied, day, source
  identity, last batch and budget fields;
- PR #135 manifest: generation time, object/push totals, day coverage/finalized
  evidence and manifest identity when supplied;
- sanitized D1 snapshot: snapshot identity/time and row count;
- PR #147 inventory: source date, expected/actual set, gaps, duplicates,
  unconfirmed rows, version and completeness.

A manifest supports `verified_count` only when every included day is explicitly
COMPLETE and finalized. It never changes R2 job status to completed. A snapshot
existing never proves a successful D1 job.

## Health semantics

`process_alive` and `http_status` are low-level signals only. Overall health stays
`unknown` without an explicit `semantic_check`. Even explicit healthy is downgraded
to `unknown` when stale. PID presence, HTTP 200, synchronization success and data
completeness remain four separate facts.

Missing evidence is `unavailable`; insufficient evidence is `unknown`. Reader
failure preserves the last-good payload and adds the new error instead of showing
a false healthy state.

## Refresh and load control

Full-page and per-section refresh call only the corresponding injected read-only
reader. A default 30-second per-section cooldown returns cached data with remaining
seconds instead of querying a production source again. Responses include `read_at`,
availability, error and source freshness. The default stale threshold is 120 seconds.

## Coverage versus synchronization

Coverage and job state never overwrite one another. `coverage_consistency` warns
when coverage is COMPLETE but a sync job failed, or a job completed while coverage
is UNKNOWN/REPAIR_NEEDED. It does not automatically alter either status.

## Monitoring sources still missing

These do not exist in the reviewed #48/PR #135 contracts and remain null/UNKNOWN:

1. Publisher attempted/successful times, durable attempts, retry/backoff, counts
   and sanitized last error.
2. R2 job identity/timeline/retry/error and uploader verification receipt. The
   manifest proves content, not uploader health.
3. D1 job timeline and independent readback counts tied to the same job/revision.
4. Collector semantic freshness/watermark/gap probe; process presence is insufficient.
5. Production API semantic freshness/content probe; HTTP reachability is insufficient.

#48 should next emit `holoviewer-sync-job-evidence-v1` as a sanitized read-only
sidecar derived from durable checkpoint/receipts. PR #135 should emit the same
shape from export/upload receipts bound to the manifest digest. Neither change
should alter cadence, retry policy or writer behavior.

## Offline acceptance evidence

`test_admin_dashboard.py` covers read-only refresh, cooldown, stale detection,
failure retention, unavailable sources, sanitized errors, synchronization failure,
coverage/job disagreement, HTTP/PID false positives, manifest semantics, required
tabs and rejection of write methods.
