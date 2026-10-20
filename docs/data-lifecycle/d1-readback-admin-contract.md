# Public D1 Readback + 8501 Admin Read-Only Contract v1

Status: **offline design / fixture only**. This document does not authorize a
Production Worker route, D1/R2 read, migration, privilege change, 8501 mount or
deployment.

## 1. Sanitized D1 snapshot contract

Schema: `holoviewer-d1-sanitized-snapshot-v1`.

Required envelope:

- `schema_version`: exact schema identifier.
- `sanitized: true`: mandatory. Absence/false is rejected.
- `snapshot_id`: `sha256:<hex>` over canonical JSON of the full sanitized
  envelope with `snapshot_id` omitted. It identifies one immutable readback
  observation, not a sync job.
- `observed_at`: UTC observation time of the independent reader.
- `target`: D1 kind/database/binding/dataset identity.
- `job_binding`: immutable input used only to scope comparison:
  - `job_id`: producer attempt identity.
  - `manifest_digest`: immutable manifest digest for exactly the intended
    payload/scope.
  - `source_revision`: producer/source revision expected by the job.
  - `scope`: exact Taipei day + AID/video partition.
  - `expected_count`: producer-declared expected count; never trusted by itself.
- `rows[]`: sanitized target evidence only. No author/content/raw error text.
- `watermark`, `pagination`, `coverage`, `query_budget`, `verification`.

### Identity / revision / hash semantics

The five identifiers have different meanings and MUST NOT be substituted:

| Field | Meaning | Relationship |
|---|---|---|
| `job_id` | one producer attempt / publish job | scopes the expected target state; may retry with a new job_id |
| `source_revision` | producer/source revision the job intended to publish | bound inside job evidence/manifest |
| row `revision` | target-visible revision/watermark for one canonical identity | may be derived by the reader from existing immutable target timestamps/sequence; no D1 migration required |
| row `content_hash` | SHA-256 of canonical target fields read independently from D1 | computed by the readback reader; raw private/content text is not exported |
| `manifest_digest` | SHA-256 of the immutable job manifest/receipt scope | binds job_id to the set/revision it intended to publish |
| `snapshot_id` | SHA-256 of the entire sanitized readback artifact | binds the independent observation and its pagination/coverage/query budget |

`snapshot_id != job_id`. A snapshot is evidence *about* a job, not the job.
A matching `manifest_digest` proves the compared scope is the same manifest;
it does not prove D1 contains every intended row. Only independent target
identity/hash/count verification can do that.

### PTT target identity

Planning identity remains `(day, AID, source_line)`; existing
`push_id` and `source_record_key` are preserved as compatibility evidence.
The reader must not manufacture a new identity when either writer identity is
already available.

### YouTube target identity

Canonical identity remains `video_id`. Authoritative playback timestamps keep
the #47 rule: only positive YouTube `liveStreamingDetails.actualStartTime` /
`actualEndTime` provenance can establish actual bounds.

## 2. Independent readback modes

### A. Dashboard bounded sample

This is the only mode suitable for automatic 8501 refresh.

Hard contract maxima per one server-side refresh:

- max 3 D1 query groups;
- keyset pagination only;
- page size <= 100;
- max 5 pages;
- max 500 rows returned;
- reader records actual D1 `rows_read` metadata when available;
- cache TTL >= 60 seconds per target/scope;
- one shared/global budget across browser sessions, not a per-tab cooldown.

A 30-second UI cooldown is UX only and MUST NOT be the quota boundary.

`verification.mode=bounded_sample` MUST keep `job_verified=false`.
Even if sample identity/hash/count match, it may only report sample agreement.

### B. Full partition readback

Manual/review-controlled only. Never triggered by ordinary admin refresh.

It may set `job_verified=true` only when all are true:

1. immutable manifest digest matches the job evidence;
2. exact expected identity set is independently available;
3. all target identities are read within an explicitly approved Rows Read budget;
4. no missing/duplicate identity;
5. all independently computed target content hashes match;
6. pagination terminates normally;
7. coverage/watermark prove the complete requested partition.

If the approved query/row/Rows Read budget would be exceeded, fail closed to
`UNKNOWN/BUDGET_EXCEEDED`; never silently downgrade to sampling and call it
verified.

## 3. Query/cache cost policy

The 8501 reader should cache by:

`(schema_version, target, scope, manifest_digest, verification_mode)`

and share that cache across all UI sessions.

Recommended initial policy for a small 8501 pilot:

- 60s minimum server-side cache TTL;
- one in-flight request per cache key (request coalescing);
- max 6 D1 refresh admissions / 10 minutes globally;
- bounded-sample contract above;
- retain last-good sanitized evidence on read failure, but label it stale;
- never execute a full table scan from a dashboard click;
- exact identity/keyset lookups only; no arbitrary SQL from the browser;
- capture returned/rows-read/query-count metadata in the evidence envelope.

Rows Read limits are release gates, not display hints. If production D1 cannot
provide a predictable bounded read plan for the selected scope, 8501 integration
remains HOLD.

## 4. API semantic health probe

Schema: `holoviewer-api-semantic-health-v1`.

HTTP reachability and semantic health are separate:

- `/health HTTP 200` => reachable only; semantic status remains UNKNOWN.
- Today probe checks expected schema, bounded sample, semantic watermark and
  source freshness.
- PTT probe checks expected schema, bounded sample, source/provider watermark,
  explicit coverage/gap status.
- History/Watchalong probes may be added only with the same bounded semantics.

The probe exports no titles, push content, author, cookies, headers or secrets.

A component can be `healthy` only when:
- evidence itself is fresh;
- expected response schema is present;
- semantic watermark/freshness passes the producer-specific contract;
- no explicit gap/conflict is present.

HTTP 200 + stale data, partial/gap coverage, schema mismatch, missing watermark
or unknown authority => `degraded` or `unknown`, never healthy.

## 5. 8501 authentication / isolation / privacy review

Current PR #147 `DashboardApplication` is GET-only but has **no authentication
middleware**. Therefore mounting it on a reachable 8501 interface is currently
a **P0 HOLD**.

Required before any 8501 mount:

1. authenticated internal-only boundary proven before request reaches dashboard;
2. browser receives no D1/API token, Wrangler credential, HMAC secret or raw
   producer sidecar path;
3. reader capability is least-privilege/read-only and scoped to approved
   sanitized sources; exact credential mechanism remains UNKNOWN until reviewed;
4. no arbitrary SQL/path/url parameters; only fixed reader operations;
5. dashboard process/module has no import path to Publisher/Collector writers;
6. GET-only plus method rejection remains; writer buttons stay disabled;
7. response `Cache-Control: no-store`; sanitized bounded errors only;
8. loopback/internal network binding or authenticated reverse proxy; no Public
   Worker route;
9. audit log may record auth subject, section, cache hit/miss and cost counters,
   but never push content, raw errors or secrets;
10. fixtures and UI must preserve null/UNKNOWN and `contract_gaps`.

Authentication is necessary but not sufficient: isolation + least privilege +
global query budget are separate gates.

## 6. Field-level alignment

### #48 PTT

Already available offline:
- `holoviewer-ptt-expected-aids-v1`;
- `holoviewer-ptt-source-coverage-v1`;
- `holoviewer-collector-semantic-evidence-v1`;
- `holoviewer-sync-job-evidence-v1`;
- PR #147 expected-set + monitor projection.

Bridge required:
- map `job_id/source_identity` to `job_binding`;
- preserve day/AID/source_line + push_id/source_record_key;
- independent D1 target hash/readback remains #45-owned.

### #47 YouTube / Public API

Keep:
- video_id canonical identity;
- roster/version and trusted actual timestamp provenance;
- Public HTTP response is not completeness authority.

Needed for dashboard health:
- sanitized semantic probe with schema + watermark + explicit gaps;
- no title/video metadata payload is required for health.

### R2 / Static Assets PR #135

Manifest `COMPLETE` is data coverage evidence only, not uploader job success.
R2 owner must provide job evidence that binds:
`job_id -> manifest_digest -> source_revision -> object identities/counts -> independent readback timestamp/count`.

The D1 and R2 readback envelopes should share:
- job_id;
- manifest_digest;
- source_revision;
- observed/readback time;
- published/verified counts;
- contract_gaps.

They do not need to share target-specific row identities.

## 7. PASS / HOLD for limited 8501 read-only integration

### PASS for a small pilot only when all are true

- offline contract validators/fixtures green;
- #48 producer projection shape is accepted;
- R2 manifest-bound job receipt fixture is accepted;
- #45 D1 sanitized snapshot/readback fixture is accepted;
- Production API semantic probe fixture is accepted;
- an authenticated internal-only 8501 boundary is demonstrated;
- no writer imports/capabilities are reachable;
- global server-side cache/admission/query/Rows Read budgets are enforced;
- bounded sample is visibly labeled as sample and cannot become COMPLETE;
- last-good/stale/UNKNOWN/error states are visibly distinct;
- no production route/migration/privilege change is required.

### HOLD conditions

Any one is sufficient:
- unauthenticated 8501 mount;
- account-wide or write-capable credential required by the reader;
- browser-visible secret/token/raw path;
- arbitrary SQL/URL input;
- unbounded COUNT/full-table scan/pagination;
- UI cooldown used as the only rate limit;
- HTTP 200/PID presence promoted to healthy;
- manifest presence promoted to completed job;
- bounded sample promoted to full verification/COMPLETE;
- missing/null evidence filled by inference;
- D1/R2 job binding cannot prove same manifest/revision scope;
- Rows Read cost cannot be bounded before production access.

## 8. Current blockers

P0:
- 8501 auth/isolation is not implemented/proven in PR #147.
- No reviewed least-privilege production D1 reader capability exists yet.

P1:
- #45 independent D1 target readback producer is still fixture/design only.
- PR #135 manifest-bound uploader job receipt/readback is still pending.
- Production API semantic probe producer is still pending.
- Current #147 target adapter assumes row revision/hash fields; production D1
  may not store them. They must be derived in the sanitized readback layer,
  not added by migration in this phase.

No production query is required to close the contract/design work above.
