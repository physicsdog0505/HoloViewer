# Offline UI acceptance — PR #147 (2026-10-20)

Scope: **fixture-only / read-only**, no 8501 mount, no Production D1/R2 reader, no publisher/collector actions, no public site changes.

## Dashboard UI
- Three tabs: Data Coverage, Sync Monitor, System Health; replaces raw JSON panel with structured evidence tables.
- Coverage: date/AID search, date range, descending/ascending ordering, COMPLETE / LOCAL_MISSING / PENDING_SYNC / PARTIAL / CONFLICT / UNKNOWN / action-needed filters, summary counts and sanitized evidence detail.
- Monitor: component, job, source/target, status, input/published/verified, attempts/success, retry/backoff, errors, evidence freshness and contract_gaps.
- Health: Collector, Publisher, Archive, Production API semantic status and supporting evidence.
- Only GET /admin/status for full/per-section Refresh; shared DashboardController still owns 30s cooldown / 120s freshness / last-good errors. UI does not contain write requests or active re-sync.
- UI uses textContent and createElement for data-driven markup, avoiding unsafe innerHTML.

## Day projection
`admin_dashboard.coverage.project_coverage(days, start_day, end_day)` returns `holoviewer-admin-coverage-v1`. Every date in an explicitly bounded requested range appears, including days absent from inputs. Missing dates are UNKNOWN. An independently verified target snapshot is required before local COMPLETE can promote to overall COMPLETE; verified absent target yields PENDING_SYNC. Missing AIDs and source-line gaps remain separate. This projection is an **offline staging contract** and is not wired into 8501 or a live reader.

## Independent review checklist / gates
- P0 **contract**: target_evidence verified and all_expected_present must mean independently bound D1/R2 readback for the exact AID/manifest/revision/hash, not a self-report.
- P0 **implementation**: verify #48 split day/night/all_day AIDs and the semantics of line coverage; snapshot records may be partial or lack target binding, therefore UNKNOWN by default.
- P1 **integration**: producer adapters from #47/#48/#45/R2 are still on their own branches. No production reader or admin access boundary is supplied.
- P1 **UX**: filtered list presumes the injected reader returns `holoviewer-admin-coverage-v1` multi-day payload; single-day PR147 inventory works as fallback, but cannot itself enumerate missing dates.
- P1 **acceptance**: unit tests exist in `test_admin_dashboard_offline_acceptance.py`; browser screenshots and exact-head CI must be independently run/verified. A committed source file is not proof of rendered browser acceptance.

## Reviewer commands
```bash
python3 -B -m unittest -v test_admin_dashboard test_admin_dashboard_offline_acceptance test_data_lifecycle test_snapshot_integration test_public_smoke test_4174_ui_parity
python3 -m compileall -q admin_dashboard data_lifecycle test_admin_dashboard.py test_admin_dashboard_offline_acceptance.py
git diff --check
```
No deployment or merge until independent review and Owner approval.
