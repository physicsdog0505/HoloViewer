# HoloViewer Public Frontend handoff — 2026-10-21

## Role / scope

This is the **Public frontend owner lane**, not only VOD/PTT.

Owns:
- Public homepage / history / custom view / collab / PTT Today
- standalone Viewer `/viewer/`
- standalone Watchalong `/watchalong-viewer/`
- Custom / Multi-view behavior
- 4174 UI/UX parity and shared viewing behavior
- responsive/mobile frontend behavior
- Public API read wiring and metadata resolver usage
- Public PTT presentation / polling / historical archive routing
- frontend smoke / parity regression tests

Does **not** own backend data repair, D1/R2 writes, Publisher, Collector, or Archive generation.

## Current Production baseline

- Worker: `holoviewer-public`
- Production source: `563ddb5838a3d2132314b986eb6092671fbd9e7e`
- Cloudflare Version: `72839f6c-0750-49d0-8f60-50e2ba4d060a`
- Matching local suite: `84/84 PASS`
- Static frontend deploy only

## Current frontend behavior

### Main Public surfaces
- Home / Today streams
- History
- Custom View / Multi-view
- Collab
- PTT Today
- Watchalong
- Viewer

Normal viewing entry points must stay **standalone**, not regress back into the old SPA viewer mount.

### Viewer
- modes: `預設 / 輪播 / 鎖定`
- single + multi stream
- live channel rail / focus selection
- immersive mode
- linked playback controls
- PTT panel follows current primary stream
- Live PTT polling cadence: 60s
- mode/layout changes must not remount YouTube iframes unnecessarily
- preserve PTT scroll/follow state across layout changes

### VOD metadata / timeline
Shared resolver: `site/assets/video-metadata-resolver.js`

- catalog first
- metadata fallback
- bounded transport/recovery errors
- `actual_start` is authoritative
- `scheduled_start` is only preload/display hint
- historical PTT follows absolute YouTube playback time

### Historical PTT
`site/assets/config.js` has explicit month registry:
- 2026-08 → Full Offline Worker
- 2026-09 → Pilot Worker
- 2026-10 → Full Offline Worker

Rules:
- choose all Asia/Taipei months intersecting the VOD/pre-roll window
- each month owns its own `base + manifest`
- actual push filtering uses UTC timestamps
- only relevant hourly chunks are fetched
- multi-month rows are deduplicated
- manifest/chunk failure => `UNKNOWN / UNAVAILABLE`
- only COMPLETE coverage + true zero rows may show real empty state
- VOD pre-roll is preserved via `vodPttFetchStartMs(context)`
- coverage completeness still uses trusted `actual_start ~ actual_end`

Acceptance VOD:
`J33JnrVJiIQ`
- actual: `2026-09-18T11:00:25Z ~ 16:13:34Z`
- September Pilot archive
- authoritative VOD-window pushes: 2,019
- source_line 247–2265
- pre-roll should already show PTT near video 0:00

### Watchalong
- standalone Watchalong surface
- host/source playback layout
- verified static session assets
- playlist / segment navigation
- subtitle / danmaku presentation
- PTT panel
- metadata fallback for VOD timing
- preserve existing 4174 accepted controls/UX

### Custom / History / Collab
- Custom and History entries open standalone Viewer
- verified VOD timing is propagated through `ptt_window`
- Collab entry preserves event/POV context
- live collab can reconcile POV membership
- VOD collab uses verified timeline sync
- History label / date / paging / cards retain accepted 4174 behavior

### Responsive / mobile
Public frontend has been checked against desktop/tablet/mobile layouts. Preserve existing responsive behavior; do not replace it with a separate SPA/mobile architecture.

## Important files

Core:
- `site/index.html`
- `site/assets/app.js`
- `site/assets/app.css`
- `site/assets/config.js`
- `site/_headers`

Viewer:
- `site/viewer/index.html`
- `site/assets/viewer-standalone.js`
- `site/assets/viewer-standalone.css`
- `site/assets/video-metadata-resolver.js`

Watchalong:
- `site/watchalong-viewer/index.html`
- `site/assets/watchalong-standalone.js`
- `site/assets/watchalong-standalone.css`
- `site/assets/watchalong-static-core.js`
- `site/data/watchalong/**`

PTT Today:
- `site/ptt-today/index.html`
- `site/assets/ptt-today.js`
- `site/assets/ptt-today.css`

Regression:
- `test_public_smoke.py`
- `test_4174_ui_parity.py`
- `test_watchalong_assets.py`

## Operating rules

**Deployment is Owner-operated.**

GPT must:
- prepare/review code
- run/read local test evidence where available
- provide exact terminal commands for Owner

GPT must **not**:
- deploy by itself
- create/use GitHub Actions or CI as the deployment path unless Owner explicitly asks
- treat CI as authoritative acceptance
- write D1/R2
- modify Publisher / Collector
- re-fetch PTT
- redeploy archive workers unless explicitly assigned

Owner performs local acceptance and `wrangler deploy`.

## Next-thread default workflow

1. Inspect current Production behavior first.
2. Identify which Public surface owns the bug.
3. Keep standalone Viewer/Watchalong architecture.
4. Reuse shared resolver/components instead of patching only one entry.
5. Preserve 4174 parity and 60s PTT polling.
6. Run exact-HEAD local regression tests.
7. Stop at deployment handoff; Owner deploys.
