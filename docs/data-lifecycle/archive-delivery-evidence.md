# Archive Delivery Job Evidence contract (#48 → PR #147)

Status: offline producer contract only. No Production R2, Static Assets deployment,
uploader execution, Worker/D1 mutation, process restart, or runtime mount is
authorized by this document.

## Current lane truth

- Workers Static Assets is the current historical delivery candidate.
- Production R2 is **not enabled**.
- This contract is target-agnostic so the same evidence shape can later describe
  either `workers-static-assets` or `r2` without changing job semantics.
- No R2 fixture in this slice represents a production execution.

## Schemas

### `holoviewer-archive-job-evidence-v1`

One evidence document describes one archive delivery attempt and keeps the
following identities separate:

- `job_id`: one delivery attempt;
- `source_revision`: exact archive/source revision used by that job;
- `source_hash`: SHA-256 of the sanitized source/archive input snapshot;
- `manifest.digest`: SHA-256 over the immutable canonical manifest bytes;
- `readback_receipt.snapshot_id`: SHA-256 identity of one independent readback
  observation.

The contract rejects any attempt to substitute `job_id`,
`manifest.digest`, and `snapshot_id` for one another. `source_hash` is also
kept semantically separate from the manifest digest.

Required target kinds:

- `workers-static-assets`
- `r2`

Only a sanitized logical target identity may be included. Cloudflare account
IDs, tokens, credentials, signed URLs, secrets, local absolute paths, raw
subprocess output, raw exception text, authors and push bodies are prohibited.

Missing delivery evidence remains `null` with explicit `contract_gaps`.
Retry/backoff, timestamps, success, upload counts, verified counts and R2
presence are never inferred.

### `holoviewer-archive-readback-receipt-v1`

Independent target readback evidence contains:

- `snapshot_id`, `observed_at`
- sanitized `target.kind`
- `job_id`, `manifest_digest`, `source_revision`
- scope
- objects expected/checked/verified
- manifest/hash/scope/count verification
- pagination completion and unresolved-object count
- `verification_mode`
- `job_verified`
- bounded error code and `contract_gaps`

`bounded_sample` may prove that sampled objects are readable and hash-correct,
but always keeps `job_verified=false`.

`full_partition` may set `job_verified=true` only when all intended objects
are independently read back and all of these are true:

1. manifest readback and manifest digest match;
2. canonical object SHA-256 values all match;
3. objects checked/verified equal objects expected;
4. object-count verification matches;
5. coverage scope matches;
6. zero unresolved objects remain;
7. pagination/readback completed;
8. all required receipt fields are present.

Budget/evidence insufficiency remains UNKNOWN through null fields and
`contract_gaps`; it is never relabeled as a successful sample.

## Object identity

Canonical archive object identity is exactly:

`manifest_digest + object_key + canonical_object_sha256`

Upload/deployment/generated timestamps are not object identities.

## PTT identity

If a future delivery evidence producer includes authoritative thread scope, it
must retain #48 meanings:

- Taipei day
- AID
- source_line
- source_record_key
- floor only when per-thread ordinal authority exists

`source_line` is never a floor.

This Archive contract does not derive expected AID completeness from a manifest.

## Three independent states

The PR #147 projection deliberately exposes these separately.

### Archive data coverage

Derived only from the manifest day matrix:

- COMPLETE
- PARTIAL
- UNKNOWN

It answers what the local archive claims to contain. It is not delivery status.

### Archive delivery job status

Derived only from explicit job evidence:

- pending
- attempted
- succeeded
- failed
- unknown

A successful job may deliver a PARTIAL archive. A COMPLETE manifest may exist
without any job having run.

### Expected-AID/source completeness

Owned by #48 expected-AID/source-coverage authority. Missing authority remains
UNKNOWN even when archive coverage and delivery readback are both verified.

## PR #147 projection

Canonical handoff is frozen at the producer boundary:

- `project_archive_job_for_pr147()`
- `project_archive_as_sync_job()`

PR #147 should consume the normalized output of `project_archive_as_sync_job()`
rather than independently reinterpret raw `holoviewer-archive-job-evidence-v1`
fields. Producer semantics for job status, verification mode, coverage summary,
expected-AID authority and contract gaps live here.


`ptt_offline/archive_pr147_projection.py` exposes a pure producer-side
projection for Sync Monitor. It does not modify the Admin UI.

| Archive evidence | PR #147 projection |
| --- | --- |
| `job_id` | `job_id` |
| `target.kind` | `target.kind` / generic Sync Monitor target |
| `source_revision` | `source_revision` |
| `source_hash` | `source_hash` |
| `manifest.digest` | `manifest_digest` |
| `attempted_at` | `attempted_at` / `last_attempted_at` |
| `succeeded_at` | `succeeded_at` / `last_successful_at` |
| `attempt_count` | `attempt_count` |
| `retry_after` | `retry_after` |
| `backoff_seconds` | `backoff_seconds` |
| `uploaded_count` | `uploaded_count` / `published_count` |
| `independently_verified_count` | `independently_verified_count` / `verified_count` |
| `readback_receipt.snapshot_id` | `snapshot_id` |
| `readback_receipt.observed_at` | `readback_observed_at` |
| `readback_receipt.verification_mode` | `verification_mode` |
| `readback_receipt.job_verified` | `job_verified` |
| manifest day matrix | `coverage_summary` |
| explicit delivery status | `job_status` |
| #48 authority | `expected_aid_completeness` |
| missing evidence | `contract_gaps` |

PR #147/8501 must not convert manifest COMPLETE into a completed delivery job,
and must not convert a succeeded delivery job into expected-AID completeness.

## Offline fixture

`ptt_offline/fixtures/archive_delivery/archive_delivery_cases.sanitized.json`
contains test-only Workers Static Assets cases. It declares
`production_execution=false`.

Covered cases include:

- COMPLETE + succeeded + full readback verified;
- COMPLETE manifest with no job execution;
- succeeded delivery with PARTIAL archive coverage;
- verified archive with missing expected-AID authority;
- bounded-sample readback;
- mismatch/fail-closed cases in tests;
- null + contract_gaps preservation;
- identity separation and sensitive-field rejection.

## Operational boundary

This slice contains only pure contracts, sanitized fixtures, tests, documentation
and pure projections.

Production R2 action: NO  
Static Assets deploy: NO  
Uploader execution: NO  
Production mutation: NO
