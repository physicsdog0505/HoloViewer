# YouTube daily expected-video set contract v1

Issue #47 handoff for Data Lifecycle PR #147. This contract is offline/read-only.
It does not deploy, write Production, enable a schedule, or call YouTube.

## Purpose

Data Lifecycle cannot infer a complete YouTube day from the rows that happen to
exist. A daily comparison needs a separately issued, versioned expected-video
set. The expected set is authoritative only for its declared roster scope.

Schema:

`holoviewer-youtube-expected-set-v1`

Machine schema:

`docs/data-lifecycle/youtube-expected-set-v1.schema.json`

Offline validator/auditor:

`data_lifecycle/youtube_expected_set.py`

Sanitized fixture:

`fixtures/data-lifecycle/youtube-expected-set-v1.sanitized.json`

## Two roster authorities are intentionally separate

### history-review-66

Purpose: historical review / History-66 evidence.

Existing source identity is the canonical 66-channel history roster used by
`Hololive-PTT-Viewer/youtube_history_66.py`, which validates exactly 66 unique
channel IDs from `hololive_channels.prototype.json`.

This scope is not the Today roster and must not be promoted to Today coverage.

### today-approved-85

Purpose: current Today ingestion / coverage.

Existing approved production evidence recorded on Issue #47:

- roster version: `today85-20261016-d0e326c0496b`
- approved channel count: 85

This scope is not the historical Review-66 roster. A Today-85 expected set does
not prove History-66 completeness and vice versa.

The contract rejects a 66 scope carrying channel_count=85 or an 85 scope carrying
channel_count=66. Consumers must key evidence by:

`(scope.kind, scope.version, day)`

Never union or force roster versions to match.

## Daily identity and time authority

The daily partition is `Asia/Taipei`.

A video belongs to a daily expected set only when it has:

- `video_id`
- `channel_id`
- verified `actual_start`
- `actual_start_source = YouTube liveStreamingDetails.actualStartTime`
- per-row revision
- per-row SHA-256 content hash

`actual_start` is converted to Asia/Taipei and must resolve to the document's
`day`.

`scheduled_start`, publication time, projection time and first-seen time are
not substitutes for verified `actual_start`.

Cross-midnight streams belong to the day of verified actual start.

## Versioned source authority

Each daily document records:

- `issuer`
- `issued_at`
- scope kind/version/count/hash
- source revision/hash
- late-metadata watermark
- expected video IDs
- normalized verified rows
- UNKNOWN cases
- `completeness_authority = VERIFIED | UNKNOWN`

A source hash identifies the sanitized source snapshot used by the issuer. The
scope hash identifies the exact channel roster. Updating either creates a new
evidence revision rather than silently changing an old day's authority.

## Late-metadata watermark

Late metadata must not make an incomplete day look empty-complete.

Fields:

- `observed_through`: how far the authoritative producer has actually checked
- `required_after`: versioned policy threshold required before closing the day
- `status = SATISFIED | PENDING`

The contract intentionally does not hard-code a 24/36/48-hour policy. That
threshold belongs to the producer policy and must be reviewed/versioned.

A day may be `VERIFIED` only when:

1. watermark status is `SATISFIED`;
2. observed_through >= required_after;
3. every expected row has verified actual_start;
4. expected_video_ids exactly equals the verified row set;
5. `unknown_cases` is empty.

An empty expected set is valid only under the same VERIFIED conditions. Merely
having zero rows is never evidence that the day contained zero videos.

## UNKNOWN cases

Supported v1 reasons:

- `actual_start_missing`
- `actual_start_unverified`
- `source_gap`
- `late_metadata_pending`
- `roster_membership_unknown`
- `metadata_revision_conflict`

Any unresolved UNKNOWN case prevents `VERIFIED`.

## Producer responsibilities

This branch defines the consumer contract only. It does not claim a production
producer already emits these manifests.

Recommended producer split:

### History-66 producer

Read-only input:
- accepted History-66 roster version/hash;
- authoritative History-66 metadata snapshot;
- bounded recent refresh/reconciliation evidence.

Output:
- `history-review-66` daily expected-set documents.

### Today-85 producer

Read-only input:
- exact approved Today roster version/hash;
- server-owned Today discovery/lifecycle evidence;
- verified YouTube liveStreamingDetails actual_start.

Output:
- `today-approved-85` daily expected-set documents.

Neither producer may fill gaps using the other roster.

## Rolling ~30-day bounded audit

`audit_recent(..., window_days=30)`:

- accepts only sanitized expected-set documents;
- allows at most 31 days;
- rejects evidence outside the requested window;
- rejects duplicate day/scope/version evidence;
- preserves 66 and 85 as separate rows;
- performs zero provider calls;
- performs zero external writes.

This is intended for the Data Lifecycle background comparison. It is not a
YouTube recrawler.

If a day is missing authoritative evidence, report UNKNOWN. Do not launch an
unbounded API scan.

## Quota / cost contract

This expected-set validator and rolling audit:

- YouTube API calls: 0
- search.list calls: 0
- D1/R2 writes: 0
- Production mutations: 0

Generating future authoritative source manifests may consume whatever bounded
quota is already authorized for the History-66 or Today-85 producer, but this
contract does not grant new quota and does not schedule any scan.

## Mapping to PR #147

PR #147 currently has an adapter seam for:

- `expected_video_ids`
- `expected_authority`
- daily inventory comparison

Recommended handoff mapping, after #147 owner review:

- `expected_video_ids` <- validated `expected_video_ids`
- `expected_authority.day` <- document `day`
- `expected_authority.version` <- a stable composite of scope version + source revision
- `expected_authority.issuer` <- document `issuer`
- `expected_authority.evidence_hash` <- document source hash

Additionally preserve in evidence/diagnostics:

- scope kind/version/hash
- late-metadata watermark
- completeness authority
- UNKNOWN cases

Do not modify the #147 admin UI to invent these fields. The dashboard should only
display what the producer contract supplies.

## Remaining UNKNOWN / blockers

1. No production issuer currently emits this exact v1 daily expected-set schema.
2. The reviewed late-metadata threshold policy (`required_after`) is not yet
   selected; until selected, affected days must remain UNKNOWN.
3. The current exact roster hash for Today-85 is not supplied by the cited Issue
   receipt; a producer must compute/persist it from the approved roster snapshot.
4. The canonical History-66 roster file hash likewise must be computed by the
   producer from the accepted roster snapshot.
5. A rolling 30-day audit can expose missing days and conflicting revisions but
   cannot prove private/deleted/unlisted YouTube content that was never present
   in the authoritative source.
6. No full API recrawl is authorized by this contract.

These are evidence gaps, not permission to infer data.
