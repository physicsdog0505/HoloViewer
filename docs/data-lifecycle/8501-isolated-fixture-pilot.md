# 8501 limited pilot — isolated fixture-only preparation

**Status: HOLD.** No running 8501 mount, production network reader, Worker route, privilege, migration, restart or deployment.

## Proposed architecture

```text
8501 host (future, separate Owner approval)
  -> existing authenticated internal-only host boundary
  -> AuthenticatedDashboard(app, trusted_server_side_authenticate)
     -> DashboardApplication (GET-only)
        -> DashboardController (30s UX cooldown; 120s stale; last-good)
           -> injected FixtureReaders
              -> fixed sanitized fixture filenames
              -> SharedFixtureCache (>=60s TTL, key=(schema,target,scope,manifest_digest,mode), coalescing)
```

The auth wrapper is a **reference boundary only**. The trusted host authenticator and actual 8501 identity/isolation are not implemented or demonstrated. It must not be mounted without a reviewed authenticator. The fixture reader uses no production credentials, client, network or writer; the fixture root is passed by trusted server code, not HTTP parameters.

## Existing PR #147 work retained

- Data Coverage multi-day projection includes missing days, status filter, date/AID search, source-line drilldown.
- Sync Monitor and System Health show unknown/unavailable and contract gaps.
- Full/per-section Refresh, 30s controller cooldown, 120s stale, last-good.
- The browser-side single-day fallback was corrected to reject legacy `target_evidence.verified` and bounded sample as COMPLETE.

## #45 fixture integration

- `FixtureReaders` validates the D1 readback via `validate_d1_snapshot` and exposes only a fixed fixture; bounded sample remains UNKNOWN.
- API semantic fixture is consumed separately from reachability. Missing/stale watermark, gap or partial evidence never becomes healthy.
- Cache is shared within one host process; **cross-process/global production rate admission and Rows Read enforcement are not implemented**. This is an explicit P0 HOLD for production.
- D1 query budget metadata is present in the sanitized snapshot, but UI cost presentation and cross-process admission require additional independent browser review.
- #48 Publisher/Collector and R2 uploader receipt fixture producers remain separate owners; missing evidence remains unavailable.

## Independent review required

Run exact-head commands supplied by #45 plus `test_admin_dashboard_isolated`. Browser fixture screenshot, privacy payload audit, fixture semantics (day/night/split/all-day), stale/watermark cases and actual 8501 host-auth proof remain outstanding. Do not claim PASS for 8501 pilot from unit tests alone.

**No running 8501 mount. Production integration HOLD.**
