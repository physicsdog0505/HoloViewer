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
