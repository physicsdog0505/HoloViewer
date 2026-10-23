# Isolated D1 atomic-batch acceptance — NOT PRODUCTION AUTHORIZATION

This branch now contains `collab_disposable_batch.mjs` (no HTTP listener, no scheduled handler, no deploy configuration) and its offline Node fixture tests. The batch engine only accepts a stated disposable Cloudflare D1 binding identity and calls `DB.batch([...prepared statements...])` once.

**Critical limitations / next work:** the identity metadata alone does not prove actual Cloudflare binding UUID. A caller must verify authenticated Wrangler account + exact disposable database ID, bind `DB` only to that UUID, verify a uniquely created sentinel in that database, and fail closed on any mismatch. The actual canonical artifact must be SHA-verified against `9ab74e8d722e0d53731e85cdd6d83f261e2c9cbafebe11869ac00681847c78b2` before packet creation; offline fixtures are not acceptance evidence.

The current `makeBatchPacket()` test fixture is a *shape fixture*, not the final canonical payload. It has not yet been checked byte-by-byte against the Owner-local artifact. The new batch SQL/values are not claimed byte-identical to the old literal SQL: the canonicalized statement+parameter digests are new, and need a separate acceptance proof that DML semantics/data values are identical.

The following must be done against an actual **disposable Cloudflare D1** before #45 re-entry:
1. Deploy/invoke the isolated test executor bound only to the disposable DB, never to the active `holoviewer-public-v1` and never by modifying `holoviewer-public-api`.
2. Show exact disposable binding UUID and sentinel; use the current schema.
3. Prove success, exact target/meta/readback values and revision.
4. Replay identical batch: no duplicate event/meta.
5. Set up an existing live row, force statement 2 to fail and prove statement 1 rolled back and statement 3 did not commit.
6. Prove cross-day replacement and next-empty-live keeps history, clears live membership.
7. Export statement digests, combined digest, executor HEAD, artifact SHA, remote evidence and zero Production writes.

**Current authorization:** engineering/disposable testing only. No Production writes, import retry, Worker deploy or schema reapply.
