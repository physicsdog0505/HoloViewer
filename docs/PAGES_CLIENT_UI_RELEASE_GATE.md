# Pages PoC → near-final Client UI deployment acceptance gate (2026-10-08)

This is a **Draft/PoC**, not production. Current preview: https://physicsdog0505.github.io/HoloViewer/ ; its published source currently matches public PR #8 commit `c57055feae498e03c5cb70cdf033c0ab02f97b7b`. Both CI workflows on that commit passed; no final browser parity acceptance yet.

## Source tracking

- Private Client UI base: `physicsdog0505/Hololive-PTT-Viewer`, PR #278, head at check time `347001903d602e9c220851b81fc62166e252e296`.
- Public Pages current homepage is **reviewed output** of private `client_home.build_home_html()`, produced on PR #300, blob SHA `cb9f2cf2c6e723496c0b7e5b349d3b5f1f50c7bc` (offline static fixture). Real Client body rendering, but scripts/navigation are disabled and sample data is generic.
- Private PR #278 advanced 5 commits since `0178b2a6`: `client_app.py`, `client_watchalong.py`, `test_client_routes.py`, `test_client_watchalong.py`, `watchalong_archive_store.py`; homepage renderer changes are **not** included in that delta, but active local worktree/other workstreams may differ.

## Deployment handoff: required from UI workstream

1. Final **running** local 4174 worktree/ref + commit SHA and whether there are uncommitted changes; do not assume the last GitHub PR branch equals the running code.
2. Acceptable representative public-safe homepage fixture: stream ID, title, channel title/group/state, start label, thumbnail/avatar if approved. No operational SQLite, local paths, tokens, unpublished mapping or private data.
3. Exact versions of `client_ui_shell.py`, `client_home.py`, `client_custom_view.py`, relevant shared player JS; identify any pending UI changes not yet pushed to GitHub.
4. Browser acceptance screenshots at two viewport sizes (desktop e.g. 1440x900 CSS pixels and mobile e.g. 390x844), 100% zoom, same font availability, data, active tab/filter/rail state and scroll position. Confirm computed font size/weight/line height, card width/gaps, header and nav.
5. List required browser-only interactions for the Pages test (not translation/collector/live PTT). Flag absolute URLs, fetch to local server, cookies/session routes, playlists and CORS blockers.

## Cloud acceptance plan

- Stage 1: re-export audited actual Client homepage HTML from exact final UI source using the same fixture; **do not hand-redraw** or silently tweak type scale or colors.
- Stage 2: replace PoC homepage and run strict public-safe/route tests and Pages deploy.
- Stage 3: browser verify: root/direct path/refresh/query/hash, desktop/mobile RWD, Custom View single-public-YouTube URL and iframe playback (provider embed policy may reject some videos).
- Stage 4: compare same viewport/data vs local 4174, document measured differences and classify platform constraints vs fixture/commit drift.
- Stage 5: give explicit PASS/PARTIAL/FAIL; no main merge, Streamlit shutdown, operational DB upload, Mac inbound, or production cutover.

## Current known limitations

Current static homepage is visual-only (scripts removed, nav noop); therefore it cannot validate live filters or home refresh. Current Custom View session uses a minimal `youtube-nocookie.com` embed path and is **not** yet the full original multi-player renderer. Watchalong and PTT are routing placeholders. Production slow/fast lanes belong to separate backend workstreams and must not be reinvented here.
