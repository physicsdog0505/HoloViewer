# Relay → Snapshot coverage proof gate

Status: **NOT IMPLEMENTED / fail closed**. This document prevents claiming a refresh has restored all purged PTT pushes.

## Observed shape (2026-10-08)

- Public Pages reader receives a historical PTT artifact (private exporter PR #302) with `snapshot_id`, `generated_at`, `completeness`, `date`, `source_hashes`, `articles[*].pushes`. It does **not** carry per-AID relay cursor coverage.
- Worker GET provides `history_gap`, `purged_through_cursor`, `next_cursor` per AID. Its cursor is a D1-generated global sequence, **not** PTT floor or source line.
- A later `generated_at`, `complete` flag, matching AID, push count, floor number, or overlapping push IDs alone cannot prove that every purged Worker push is contained in a historical snapshot.
- Current Pages client correctly keeps an incomplete warning latched; a refreshed snapshot is additive only.

## Required trusted proof (future contract version)

For each article AID, after a read-only historical projection was built **with access to the publish ledger**:

1. Snapshot carries an explicit authenticated, immutable publish-ledger coverage marker, e.g. `relay_coverage: { contract_version: 1, relay_instance_id: ..., aid: ..., covered_through_cursor: ..., publisher_ledger_sha256: ... }`. Exact field/schema must be reviewed in both repos before writing code.
2. A trusted exporter/publisher proves that all published push IDs for that AID up to `covered_through_cursor` (including deleted Worker rows) were either included in the snapshot or represented in a persisted recovery-proof manifest. A mere cursor high-watermark is **not proof**.
3. Browser can only clear the latched gap when authenticated/validated coverage refers to the same Worker instance and AID, covers at least the reported `purged_through_cursor`, and the artifact is committed/immutable. Otherwise status remains partial.
4. Proof must handle failed publish, retries/duplicates, changing date articles, old Snapshot cache, Worker redeploy/D1 reset and revoked records. Publisher must never infer coverage from wall clock alone.

## Before claiming PASS

- Add controlled fail-closed producer+consumer contract tests for missing/wrong AID/wrong relay instance/stale or forged high-watermark, and complete ledger coverage.
- Test actual exporter and Worker on disposable synthetic data with forced retention, disconnect, replay and eventual new Snapshot.
- Independently review any first real PTT publication; no operational SQLite, secrets or Mac mini path in public artifacts.

Current recommendation: keep explicit PARTIAL status until trusted publish-ledger coverage is available, and continue live polling + deduplicated snapshot merge. Do not enable optimistic reset.
