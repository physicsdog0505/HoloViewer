# Public VOD / Historical PTT handoff — 2026-10-21

## Current production baseline

- Public Worker: `holoviewer-public`
- Production source: `563ddb5838a3d2132314b986eb6092671fbd9e7e`
- Cloudflare Version ID: `72839f6c-0750-49d0-8f60-50e2ba4d060a`
- Local acceptance: `84/84 PASS`
- Production deploy: PASS

## Implemented behavior

- Public viewing remains standalone: `/viewer/` and `/watchalong-viewer/`; do not regress to SPA.
- Shared VOD metadata resolver:
  - catalog first
  - metadata fallback
  - transport failures bounded / fail-closed
  - `actual_start` is authoritative
- Historical PTT:
  - month registry in `site/assets/config.js`
  - 2026-08 → Full Offline Worker
  - 2026-09 → Pilot Worker
  - 2026-10 → Full Offline Worker
  - cross-month VOD loads every intersecting month
  - per-month `base + manifest`
  - only intersecting UTC hourly chunks are read
  - merged rows are deduplicated by stable identity
  - manifest/chunk failure => `UNKNOWN / UNAVAILABLE`, never fake zero-push state
  - coverage completeness is checked from manifest coverage, not HTTP 200 alone
- VOD PTT pre-roll restored:
  - archive data fetch starts from `vodPttFetchStartMs(context)`
  - scheduled/actual anchor can preload roughly 1 hour before stream start
  - coverage status still uses the trusted `actual_start ~ actual_end` window
  - pre-roll crossing a month boundary can load the previous month's source
- CSP includes September Pilot archive origin.
- Viewer modes `預設 / 輪播 / 鎖定` remain unchanged.
- PTT polling cadence remains 60 seconds.
- Archive read path is read-only; no POST/PUT/PATCH/DELETE, no D1/R2 writes.

## Key acceptance VOD

`J33JnrVJiIQ`

- actual_start: `2026-09-18T11:00:25Z`
- actual_end: `2026-09-18T16:13:34Z`
- September source: Pilot Worker
- authoritative VOD-window pushes: 2,019
- source_line: 247–2265
- no missing / duplicate source lines
- pre-roll fetch includes the hour before start; playback 0:00 should show pre-start PTT instead of an empty message.

## Files changed in this line

- `site/assets/config.js`
- `site/assets/viewer-standalone.js`
- `site/_headers`
- `test_4174_ui_parity.py`
- `test_public_smoke.py`

## Important operating rule

**Deployment is owner-operated.**

Do not deploy on your own. Do not create or use GitHub Actions / CI as the deployment path unless the owner explicitly asks for it. The owner runs the local terminal acceptance and `wrangler deploy`; GPT should prepare/review code and exact commands only.

Also:
- do not write D1/R2
- do not modify Publisher / Collector
- do not re-fetch PTT
- do not redeploy archive workers unless explicitly assigned

## Next-thread starting point

If a Public VOD/PTT issue appears:
1. inspect current production behavior first;
2. keep standalone Viewer architecture;
3. preserve monthly archive registry + cross-month selection;
4. preserve pre-roll behavior;
5. test locally against exact HEAD;
6. hand deployment commands to the owner only.
