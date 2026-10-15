# #47 / PR #53 — #45 T1–T8 contract remediation checkpoint

**Snapshot HEAD:** `abc5a28ac8f40542c98b1e835b63c261b8fa8272` (branch `issue47-public-today-offline-ingestion`, pinned from `be4ba1d1020cfecad6ee4a525e86ba9235cf998a`). Only backend-owned files changed. No Cloudflare, site, PTT, 8788 vendored source, Google API or private DB operation.

## Core and contract
- Provider-neutral `TodayProvider.read_today(day, limit)`, local callback-backed adapter and Cloudflare callback-backed adapter return identical product-facing read model. Concrete adapters do not expose Cloudflare/D1/quotas/SQL keys.
- Envelope: `schema_version=public-consumer-v1`, `as_of`, `freshness.status=fresh|stale|unknown`, `completeness.status=complete|partial|unverified`, explicit `gap`, opaque `checkpoint`, `streams[]`.
- `complete` requires explicit accepted evidence bound to roster version and Today scope; full successful scan alone stays `partial`. Global coverage gaps never erase fresh verified item evidence. Per-item age can independently make lifecycle `unknown`.
- Roster version is propagated through ingestion into normalized evidence. Unapproved publisher quarantined; mismatched read roster omitted.
- Positive actual-start/end timestamps must be no more than 300 seconds after observed source time; future metadata cannot certify `live`/`ended`. Stale and contradictory replay cannot replace positive ended timestamp with fresh unknown.
- Retry decisions terminate past `max_retries`; scan count uses ceiling for non-divisor interval.
- `backend/today/test_today_contract.py` contains mandatory Today vectors T1–T8 plus regression cases; prior `test_today_offline.py` / `test_provider_ingest.py` updated. Reproduction command: `python -B -m unittest -v backend.today.test_today_offline backend.today.test_provider_ingest backend.today.test_today_contract`.

## Verification status
GitHub diff and exact HEAD are verifiable. **Actual Python execution of combined exact-HEAD tests: NOT RUN in this session** (connector read/write environment has no repository checkout and container cannot resolve GitHub). **GitHub CI NOT RUN** until an exact-HEAD matching run is observed. This checkpoint does not claim tests green, runtime readiness or independent approval. Run the command above on an exact-HEAD checkout or approved offline CI and attach raw receipt before compatibility PASS.

## Known architecture/deploy blocks
Pure ingest model still uses injected fixture metadata callback; actual HTTP, discovery-page quota, durable quota ledger, distributed lease, real D1 conditional writer and scheduled Worker are not implemented. Proposed SQL schema migration is unexecuted. Public roster/rights, quota balance, Cloudflare billing/security and actual stale UX integration are Owner/UI review gates. No YouTube/Cloudflare production execution authorized. Cost **illustration**: 66*48+72=3,240 quota units/day before extra pages/retries; 3,716 D1 written rows/day scenario, not account measurement. Rollback after future authorized deployment: disable scheduled trigger, retain last good snapshot marked stale, restore known-good API revision without touching private/PTT data.
