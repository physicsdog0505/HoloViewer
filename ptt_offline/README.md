# Issue #48 — PTT offline provider-neutral contract slice

**Status: Draft / offline-only / review candidate. Not production.**

This directory is standard-library Python plus synthetic fixtures only. It never reads PTT, SQLite, Collector/Publisher state, Cloudflare/D1, secrets, network endpoints, `site/**`, 4174/8501, or 8788 product source.

Run: `python -B -m unittest -v ptt_offline.test_public_today_contract`

## Pinned reviewed inputs

Private #311 `4c0d45d0de3eb5c06afa25e157f1efc2fc9120fa`; #312 `cc3a78d7bd77b9fc3a283eb71610ea57c5aa6f52`; #313 `980ec18ed310261395c6c66fdec86419f60aa322`; #315 `672822409a62939fbf08ca84f416eb9128249158`; #328 `379c567ca7013a1fd9cf6ef3b315f87a65eadefd`; Public #12 `6891d5514282f289ef39a6ed718831246e0d9d5e`; Public #19 `804a9e76353ea40c300d54d5fceca4d3057c0a12`.

Observed HoloViewer main while preparing this slice: `bbd08ce6a0347737debdd1f1cbc67f2ea189a2e0`. This branch stays isolated; no merge/rebase of main is performed here.

## What this slice now proves offline

- Canonical `push_id` is byte-compatible with reviewed #311: `ptt:v1:<sha256>`, normalized public AID (`#AID` -> `AID`), UTC-second timestamp, UTF-8 compact JSON over AID/source_line/author/time/content. Floor is excluded.
- `PttProvider` is the storage-neutral seam. Future `LocalPttProvider` and `CloudflarePttProvider` can supply the same contract without exposing SQLite/D1 schemas to 8788/UI.
- Today merges multiple AIDs for one Taipei day and stores a **per-AID cursor vector**, never one global merged cursor.
- Initial visible window is 300. Collector precedence, authoritative `source_line`, nullable display `floor`, deterministic order, replay dedup, stale last-good state, retention-gap PARTIAL latch, and Taipei PTT-only rollover are preserved.
- Relay pages are fail-closed for wrong AID, expired/regressive/out-of-order cursor, inconsistent gap predicate, >500 rows, >512 KiB and canonical-ID mismatch.
- Known bootstrap bug is guarded: raw `tail=1` with `has_more=true` can never directly establish a forward checkpoint. Provider code must first return a coverage-safe `InitialWindow`; otherwise initialization fails closed. This prevents continuing from a newest visible cursor while silently skipping retained rows.
- Byte-truncated/CJK forward continuation is bounded to at most 3 pages per AID per poll.
- History completeness is separate. Only synthetic accepted evidence bound to exact day + exact AID set can return COMPLETE; caller flags, checksum, empty day, or title-known rows cannot.

## Real integration gate

This PR intentionally does **not** choose how a future Cloudflare provider obtains a coverage-safe initial window. That provider must reconcile actual Worker wire semantics (including tail/byte truncation) and prove its bootstrap before it can satisfy `initial_window()`. Latest accepted 4174 runtime SHA also remains a source-of-truth item for the 4174 owner lane; this slice encodes the already accepted behavior recorded in Issue #48, not a local runtime inspection.

Still HOLD: real PTT/owner SQLite, Collector/Publisher start, raw-history export, Worker/D1/schema/secret/route mutation, production canary, `site/**`/UI change, merge or deployment. #317 real-data G3 remains HOLD.


## Independent review hardening — follow-up to #48 comment 6187020719

Changes on the same isolated Draft branch:
- **Atomic batch application**: stage normalized identities, canonical checks, source-day/floor checks and Collector-winning rows before committing the entire snapshot/relay page. Invalid later row leaves previous rows and cursor unchanged.
- **Strict Taipei day key**: only canonical date-only YYYY-MM-DD is accepted; datetime-shaped keys fail.
- **Freshness clock regression**: a now timestamp older than last checked fails closed and marks freshness unknown.
- **Completeness evidence**: core requires explicit `verify_authority(manifest)` injection; without an injected verifier it always returns PARTIAL. Only tests inject the synthetic fixture verifier.
- **Consumer checkpoint**: `consumer_checkpoint()` provides an opaque day-bound offline token; `check_consumer_checkpoint()` rejects foreign-day, expired or mismatched tokens. Internal per-AID cursor integers stay inside the adapter. **This is in-memory proof only**, not a durable/signed production checkpoint or a finalized #45 read-model surface.
- Added five negative regressions: mixed-valid/invalid snapshot batch, mixed-valid/invalid relay page, malformed day keys, regressive clock and foreign-day/expired token.

This does not implement a real `LocalPttProvider` or `CloudflarePttProvider`, nor authenticate a durable production resume token. Those remain separately reviewed integration work. If exact-HEAD Python execution is unavailable, report tests as **NOT RUN**, never recycle a prior HEAD's receipt.

## #48 History pagination correction (Review #6187418898)

History `read_history(day, page_request)` now advances through a real day-sorted,
canonical-deduplicated snapshot using an **opaque next-page continuation token**.
`PttHistoryReadModel.checkpoint` is the snapshot identity, while
`page.next_checkpoint` is a separate page continuation; neither exposes offsets,
cursor integers, or AID-specific progress. Resume verifies the exact selected
Taipei day and a deterministic snapshot generation. Unknown/stale/cross-day
tokens fail closed. Terminal pages return `has_more=false` and
`next_checkpoint=null`. New tests cover 1/2/3 pages, distinct IDs/no duplicates,
terminal behavior, invalid limits, unknown token, cross-day reuse and
snapshot mutation invalidation.

Also committed independent regression modules for the previous #45 integration
boundary: all-AID initialization atomicity, mixed-success poll stale/partial,
consumer model shape, and snapshot-only token invalidation.

The token registry is intentionally in-memory for the authorized offline slice.
It is NOT signed/restart-persistent/cloud-ready. Provider restart recovery requires
a separately accepted production design and is not claimed here.

Verification command from repository root:

```sh
python3 -B -m unittest -v ptt_offline.test_public_today_contract ptt_offline.test_consumer_boundary ptt_offline.test_consumer_paging ptt_offline.test_public_consumer_envelope
```

GitHub Actions: NOT RUN if no exact-head run exists. Runtime verification must
not reuse receipts from older commits.

## #45 consumer-boundary follow-up (Issue #48 review 6187540814)

The offline reader now projects public pushes through a fixed allowlist of
`push_id,aid,source_line,kind,author,content,occurred_at,floor,source_url`.
Backend `cursor`, `origin`, and arbitrary future fields cannot escape.
`source_url` is emitted only if it matches a strict HTTPS PTT C_Chat article
path; malformed or untrusted URLs become null. Unknown `kind` is kept null
instead of inventing a vote; known values must be 推, 噓 or →. Real-provider
mapping for source URL/kind is an integration gate, not assumed from fixtures.

Both Today and History use the `public-consumer-v1` envelope with `as_of`,
`freshness={status,last_success_at}`, `completeness={status,gap}`,
opaque checkpoint, projected pushes and page metadata. Today ages freshness
at every read via an injectable timezone-aware clock, including no-checkpoint
reads. Regressive timestamps fail closed to unknown.

A verified, successfully readable day with zero rows returns an honest empty
feed with no fabricated COMPLETE/gap; unresolved AIDs or read failures raise
typed `SourceUnavailable` (provider-neutral unavailable condition), never
complete-empty. Existing last-good state is retained for poll failures.

The added `test_public_consumer_envelope.py` contains seven regressions for
projection/internal-field leakage, fresh/stale TTL without checkpoint, clock
regression, valid/untrusted URL, kind, verified empty and typed unavailable.
All new contracts remain offline-only and cannot authorize live PTT or D1
integration. Exact-head execution evidence must still be collected.

## Owner's single permanent D1 architecture (Issue #48, 2026-10-15)

`Existing PTT Collector -> canonical local SQLite -> Publisher -> Cloudflare D1 -> Worker API -> Public/8788`.

The owner has authorized **implementation source code** for the D1 lane, but
has NOT authorized production D1 creation/migration, importing owner data,
enabling live Publisher, secrets, deployment or merge. No staging backend,
disposable database, second scraper, or second public provider will be built.

New offline code:
- `d1_migrations/0001_canonical_ptt.sql`: forward-only v1 schema, version
  ledger, canonical push PK, AID/day/source line, nullable floor, kind,
  source URL, source evidence and provider watermarks/gap state.
- `d1_publisher.py`: canonical, idempotent upsert SQL preserving Collector
  authority and source evidence; batch validation before writes.
- `d1_provider.py`: D1 readback provider interface, with explicit prohibition
  on inventing real relay continuation or claiming live authority.
- `test_d1_publisher.py`: offline SQLite compatibility checks for
  idempotence, Collector precedence, upsert repair, schema replay, source
  ordering, and invalid-batch rejection.

**These modules are NOT a connected production Worker or live Publisher.**
Canonical SQLite column mapping, D1 batch transactions and Worker API routing
must be proven against the accepted owner runtime before activation.
Forward migrations, not drop/rebuild, are the durability policy.

Current comprehensive offline verification command:
```sh
python3 -B -m unittest -v ptt_offline.test_public_today_contract ptt_offline.test_consumer_boundary ptt_offline.test_consumer_paging ptt_offline.test_public_consumer_envelope ptt_offline.test_d1_publisher
```

## Canonical Public DB binding and 2026-10-15 review correction

The **only** intended production Public D1 is `holoviewer-public-v1`,
exposed through the **existing** `holoviewer-public-api` Worker binding
`DB`. `holoviewer-ptt-relay` and `holoviewer-ptt-live-v2` are NOT
the unified Public target. Never create a fourth D1 or apply the proposed
migration to either legacy PTT D1. Actual migration/route binding remains
owner-gated. Schema SQL is a proposed additive migration for the existing
Public D1; check deployed schema compatibility before any application.

Four exact-head production review blockers addressed in source:
- Stable source evidence conflict is now **fail closed** in the same
  transaction, rejecting reparse to a different canonical `push_id`
  instead of repointing evidence and leaving two visible rows.
- Higher/equal-priority replay with null floor cannot erase known enrichment.
- `D1PttProvider` now requires the selected day at construction and
  constrains `initial_window` by day **and** AID.
- The Worker only claims fresh when parsed `last_success_at` has a finite,
  nonnegative age within 30 seconds. Invalid/future/missing timestamps
  become unknown.

Python offline regression command:
```sh
python3 -B -m unittest -v ptt_offline.test_public_today_contract ptt_offline.test_consumer_boundary ptt_offline.test_consumer_paging ptt_offline.test_public_consumer_envelope ptt_offline.test_d1_publisher ptt_offline.test_d1_provider
```

Node offline Worker freshness regressions:
```sh
node --experimental-default-type=module --test ptt_offline/test_d1_worker_freshness.mjs
```

No CI or exact-head local execution is implied by committed test source;
report these as NOT RUN until genuinely executed. No production DB
mutation, SQLite owner-data read, Publisher activation or deploy authorized.

## Follow-up: shared-D1 three-gate review 6188494686

- `publicPttFreshness()` now distinguishes known old success (`stale`)
  from malformed/missing/future timestamps (`unknown`); only [0,30s]
  finite elapsed time is `fresh`.
- `publish_provider_state()` writes real per-day/AID last-success,
  gap latch and observed cursor/purge watermarks. Replays use monotonic
  updates; absent watermark inputs do not invent resume cursor evidence.
  This is a separate explicit write path; production caller still must
  invoke it with Collector/Publisher-verified evidence.
- Migration ledger is `public_ptt_schema_migrations`, preventing a
  generic ledger collision with other subsystems of shared
  `holoviewer-public-v1`; tests verify re-application and version row.

Testing continues with the six-module Python command and Node freshness
command above. Committed tests alone do not establish executed PASS.

## Existing Public Worker route integration seam (after review 6188659557)

The neighboring #47 branch's accepted `backend/today/d1/worker-read.mjs`
exports `handleTodayRead(request, env)` for the existing
`holoviewer-public-api` router. #48 now likewise exports
`handlePttPublicRead(request,env)` in `d1_worker_routes.js`.
The owner of the existing Worker route table can dispatch only
`/v1/ptt/today` and `/v1/ptt/history` to it, passing the existing
`env.DB` bound to `holoviewer-public-v1`. The adapter rejects missing
bindings and non-GET methods. There is **no automatic deployment, Worker
entrypoint replacement, or binding mutation**.

The existing `holoviewer-public-api` router source/route table has not
been verified in this branch and MUST be reviewed at integration; the
bridge is therefore an export contract, NOT proof of a connected route.
Production D1 migration, Publisher activation and deploy remain owner-gated.

## Review 6188824728 — multi-AID and verified gap-close hardening

- Worker day freshness now evaluates **every** verified `ptt_threads` AID
  against `ptt_provider_state`, not just nonnull timestamp rows.
  Missing/invalid any required AID => `unknown`; all known with one
  outdated => `stale`; all current => `fresh`.
  Dedicated Node tests cover the A1-only/A1+A2 partial state regression.
- Ordinary `publish_provider_state` writes still latch gaps. Separately
  `close_verified_gap` requires an injected authoritative positive
  coverage verifier, a stable repair ID/digest, verified timestamp and
  a covered-through watermark at least as high as the known purge cursor.
  A repair record is preserved in `ptt_gap_repairs` and a closure marker
  `gap_closed_at` fences old replay. Only newer explicit gap evidence
  can reopen the gap. Offline SQLite regressions cover reject-without-proof,
  successful closure, old replay and newer re-gap.

Migration note: all of these changes belong to the **proposed** v1 SQL for
the EXISTING `holoviewer-public-v1`. It has not been applied to any real DB.
If an earlier schema version has already been applied elsewhere, use a
forward `0002` migration rather than mutating that applied database's
history. Actual runtime migration is explicitly owner-gated.

Tests remain the six-module Python suite plus
`node --experimental-default-type=module --test ptt_offline/test_d1_worker_freshness.mjs`.
Neither source commits nor missing Actions may be described as test PASS.

## Canonical Collector source-inspection progress (#48)

Inspected **repository source**, not private DB rows:
`physicsdog0505/Hololive-PTT-Viewer/ptt_storage.py`.
`PttDatabase` defines `articles(id,board,aid,url,title_hint,created_at,
last_seen_at,...)` and `pushes(id,article_id,source_line,source_page,kind,
author,content,ptt_date,ptt_time,collected_at)`.
`UNIQUE(article_id,source_line)` is canonical source-location evidence.
`article_screens` stores page/line coverage and must eventually contribute
to gap/completeness evidence. Source `ptt_date` and `ptt_time` are separate,
so the Publisher **must not invent year/timezone/full timestamp**.

`collector_source_preview.py` is now an explicit-path, read-only,
synthetic-friendly source preflight. It checks those exact source columns and
produces a bounded, redacted, **zero publishable rows** receipt whenever time
identity is unproven. Sample invocation only after authorized source access:
`python3 -B -m ptt_offline.collector_source_preview --source /explicit/approved/fixture.sqlite3 --day 2026-10-15 --dry-run --limit 5`.
It never uploads or writes rows, has no inferred owner DB path, and is
**not** a live Publisher/D1 CLI. Synthetic tests cover read-only guarantees,
schema mismatch, bounded preview and fail-closed source time.

Before a live Publisher can exist, separately review:
- trustworthy per-row Taipei day/year/time reconstruction from canonical
  Collector/article source evidence;
- explicit selected day/AID scope, article source URLs and coverage/gap;
- bounded transaction, one-process exclusivity and resumable checkpoint;
- actual D1 transport/binding and hard first-window budget.
No owner SQLite has been opened.

## #48 Publisher CLI bounded preparation

`publisher_cli.py` now supplies an executable **offline-only dry-run
skeleton** with explicit `--source`, `--day`, `--aid`, `--receipt`,
`--batch` and required `--dry-run`. It opens only the caller-supplied
source SQLite in read-only mode; takes a nonblocking exclusive file lock;
checks `articles/pushes/article_screens` schemas and selected AID; samples
screen coverage without declaring completeness; and atomically replaces a
redacted local checkpoint receipt. The upper batch bound is 5.

```sh
python3 -B -m ptt_offline.publisher_cli --source /explicit/approved/synthetic.sqlite3 --day 2026-10-15 --aid A1 --receipt /tmp/ptt48-offline-receipt.json --batch 5 --dry-run
```

By design the result is `BLOCKED_UNVERIFIED_TIMESTAMP` with zero
publishable rows, zero D1 requests and no automatic retries. This CLI
does **not** upload, resolve source timestamps, read arbitrary private
owner data, start a real Publisher, or represent a production-ready
checkpoint/replay writer. Positive complete-source coverage and trustworthy
event time still require independent acceptance. Test module:
`ptt_offline.test_publisher_cli`.

## #47 exact shared API seam now available — #48 handler injection

Owner review #48 6192092942 points to #47 exact HEAD
`149a80361654b06377dbae580e1d8da2e5010cf0`.
Directly verified `backend/today/d1/api-shell.mjs` at that HEAD exports
`createExistingApiRouter({legacyHistory,legacyVideo,pttHandler})`, whose
routing already preserves CORS, GET/OPTIONS, /health, missing DB, canonical
#47 Today and legacy history/video paths. The PTT seam passes the same
`env.DB` to the injected handler.

#48 now exports `createPttMountedApiRouter(createExistingApiRouter,options)`
from `ptt_offline/api_shell_ptt_extension.mjs`, wiring only the already
reviewed `handlePttPublicRead(request,env)`. It neither reconstructs a
second shell nor introduces another service. The adjacent
`test_api_shell_ptt_extension.mjs` uses a deterministic signature-matched
fixture to verify the two PTT routes, read-only GET behavior and preservation
of the host guards. **This fixture is not a byte-for-byte execution of #47's
actual shell**: final combined-router testing requires the exact #47 source
in the same checked-out integration branch and remains outstanding.

After the #47 base is integrated into the exact combined tree, the intended
call is `createPttMountedApiRouter(createExistingApiRouter)` using its
real factory, with no duplicate worker entrypoint.


## #48 Publisher authority follow-up — timestamp, coverage, resumability

Canonical Collector source inspection establishes a strict split between event
and observation time. `pushes.ptt_date` + `pushes.ptt_time` contain only
`MM/DD HH:MM`; `collected_at` and `article_screens.captured_at` are
Collector observation timestamps and are **not** event-time substitutes.

`timestamp_authority.py` therefore has no current-year/collection-time
fallback. A publishable event timestamp requires explicit positive evidence
for year, `Asia/Taipei`, authority type and a stable source reference.
Synthetic rollover tests prove that identical `01/01 00:01` text resolves to
different years only when different verified evidence is supplied.

Coverage is now positive only when canonical `article_screens` intervals
continuously cover source lines `1..articles.last_source_line`. Readable
pushes, first-N samples, page count alone, or partial screens cannot produce
`complete=true`; internal/tail gaps are reported explicitly.

`resumable_publisher.py` is a pure offline transport-neutral state machine:
explicit source identity + selected Taipei day + verified AID vector, at most
5 rows per batch, one request cap, zero automatic retries, deterministic batch
digest, replay skip by per-AID source-line checkpoint, and **checkpoint advance
only after an exact all-row ACK**. It has no network/D1 implementation.

This closes the source/offline contract shape but does not fabricate missing
production evidence. Real source timestamp evidence, D1 transport mutation,
Publisher activation/Cron, secrets, deploy and merge remain owner-gated.


## Review 6192891842 — identity/chronology/continuation corrections

The URL-epoch time adapter is still a **candidate, not production timestamp
authority**. The article URL epoch can anchor the article posting year, but
does not by itself prove all later push years or the AID ↔ URL identity.
`article_epoch` now **requires an independently supplied positive
`identity_verifier(board, normalized_aid, url)`**. A missing, negative or
malformed identity proof aborts before timestamp reconstruction. Synthetic
tests inject an explicit fixture verifier. No trusted production verifier has
been approved or wired.

The source-line monotonic chronology reconstruction rejects invalid date
text, backward chronology except observed Dec→Jan, duplicate/regressive line
order and unobserved gaps exceeding 45 days. This limit is a **conservative
fail-closed policy**, not a claim that a PTT article cannot remain idle longer.
A thread with ambiguous multi-year calendar evidence must remain blocked until
external positive evidence exists. Never infer it from `collected_at`,
`captured_at` or system year.

`collector_day_stage.stage_selected_day()` requires exact calendar
`YYYY-MM-DD`, one verified article identity, source-only line-order read,
a 50,000-row maximum audit scan, selected-day filtering, a five-row return cap,
and a stable `next_after_source_line` for continuation. The
`after_source_line` argument filters already ACKed source lines; the opaque
Public History cursor is a distinct consumer contract and is not reused as
the Publisher source checkpoint.

`coverage_receipt()` now keeps **observed** line gaps distinct from
**unverified** terminal/completeness evidence. `has_gap=true` represents
actual source-line holes; continuous screens with no verified terminal page
return `has_gap="UNKNOWN"`, `complete=false`, avoiding an unjustified sticky
provider purge-gap latch. Even structurally contiguous current coverage is
not automatically accepted historical final-complete evidence.

The first-window D1 cap of 20 Rows Written is a conservative **abort ceiling**,
not logical push count or SQL statement count. Five pushes can attempt one
thread insert, five push upserts, five evidence upserts and one separately
ordered provider-state update (up to 12 possible row mutations before
accounting for actual affected-row behavior). `logical_rows_acked` must
equal the batch's five-or-fewer pushes independently of Cloudflare
`d1_rows_written`; real rows-written/query counters remain an owner-gated
runtime measurement.

`publisher_session.py` proves an **offline injected synthetic**
ACK→atomic checkpoint order and fail/restart/replay contract. It neither
certifies a real remote ACK nor authorizes D1 transport, live execution or
source-data access. Only approved independent identity and chronology evidence
can lift the positive transformation gate.
