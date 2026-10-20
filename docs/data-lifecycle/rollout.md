# Production Rollout Plan (not authorized)

1. Integrate this read-only snapshot contract into the current heads of #47 and
   #48; resolve their non-main merge bases without copying production writers.
2. Owner approves versioned roster, expected-set authority, verification
   windows, D1/R2 budgets, and visible UNKNOWN semantics.
3. Run inventory against sanitized exports only; compare with independent D1/R2
   read-only snapshots. Record deployed SHA and metrics. No writes.
4. Add an owner-writer adapter that consumes signed/content-bound plans, first
   against disposable SQLite/R2 mocks. Keep default dry-run and hard zero-write
   assertions.
5. Separately authorize a small staging canary with row/request budgets,
   stop-on-uncertain, checkpoint receipts and exact readback.
6. Only after canary review, authorize schedules independently for YouTube and
   PTT. Rollback disables schedule/writer while retaining last known snapshot as
   stale; never delete canonical history during rollback.

Required monitoring: source freshness, per-day completeness status, action
counts, conflict/gap queue age, requests and rows written, retry rate, budget
stops, checkpoint lag, deployed SHA, and D1/R2 readback hashes.

Not performed in Phase 1: deployment, production read/write, migration, secret
change, schedule enablement, Publisher/Collector restart, live YouTube/PTT scan.
