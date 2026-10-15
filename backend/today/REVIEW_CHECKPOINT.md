# Issue #47 offline ingestion checkpoint

Isolated draft PR #53; all modifications are backend-owned. **No deployment or real provider calls are authorized.**

- Today consumer: Public `GET /v1/catalog/today` expects `streams || items`, stable `video_id` and `lifecycle_state`, with existing site untouched.
- `TodayProvider` permits a local 8788 adapter or a separately authorized D1-backed callback reader without changing the read contract.
- `ingest_batches` accepts only a versioned, explicitly supplied roster. The 66-channel private test roster is not certified for production. Provider metadata and playlist pages are injected; no transport/credentials.
- Exhaustion, missing page, truncated page, provider failure, unapproved owner and bad metadata set gap. Freshness/gap downgrade visible item state to unknown, never guessed live/ended. Later ended observation cannot be overwritten by replay or contradictory unknown metadata.
- **Known production gaps:** metadata batch cost counted, playlist discovery cost must also be reserved; no persistent quota lock, D1 CAS transaction, distributed lease, real transport, deployed Worker API, authorized roster, Cron or full upcoming coverage. D1 schema is a proposed migration only.
- Test: `python -B -m unittest -v backend.today.test_provider_ingest` plus original `backend.today.test_today_offline`. Exact-run receipt must be attached before review. No CI status assumed.
- Budget model: 66 channels x 48 scans/day + 72 metadata batches = 3,240 quota units/day before retries/overlap; D1 illustrative 3,716 row writes/day (111,480 over 30 days), actual plan unknown.
- Gate: owner approval of roster, schema/UI degraded visibility, real quota, dedicated D1, security review, rollback before any real integration. Rollback is to disable schedule, retain last good snapshot but report stale, restore previous GET API; no private or PTT data touched.
