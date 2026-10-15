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
