# 4174 UI parity — authoritative handoff (not design inspiration)

## Pinned owner-accepted reference
- Private source repo: `physicsdog0505/Hololive-PTT-Viewer`
- Exact reference commit: `cab0adb51b627205e39541d7b985258fb861fb24` (History acceptance branch `feat/4174-history-day-391`)
- Shared UI implementation: `client_ui_shell.py`; page implementations: `client_home.py`, History branch's History modules, `client_watchalong.py`, `client_custom_view.py`, `client_ptt_today.py` and shared viewing modules.
- **Do not substitute current private main for the pinned accepted 4174 UI without owner approval.** Do not publish private DBs/source-only application internals to this public repo.

## Owner-mandated migration method (hard rule, 2026-10-15)

The Public site is **not** an independent reimplementation of 4174.

The required migration sequence is:

1. **Transplant the complete accepted 4174 viewing implementation first.**
   - Move the 4174 HTML structure, CSS, browser-side JavaScript state/state-machine logic, YouTube IFrame API integration, single-view behavior, multi-view Equal/Focus behavior, immersive mode, and PTT layout together.
   - Do not selectively rewrite these parts into a new Public implementation before the full transplant has been attempted.

2. **Run the transplanted implementation in the Public environment as-is.**
   - The first test is whether the original 4174 implementation works after deployment.
   - Do not pre-emptively replace working 4174 logic because the server/runtime is different.

3. **Only modify what actually fails after transplant.**
   - A change is allowed only when a concrete runtime incompatibility or error has been reproduced.
   - Record the exact failure node, error message, affected file/line, and why the original 4174 code cannot run unchanged in Public.
   - Fix the smallest incompatible boundary only.

4. **Adapters are exception paths, not the default architecture.**
   - Use adapters only for proven environment-specific boundaries such as data access, server routing, filesystem access, local SQLite, Python-only APIs, or Cloudflare-specific runtime interfaces.
   - The adapter must preserve the 4174-visible behavior and must not introduce a parallel Public-only player/layout implementation.

5. **Do not create a second product implementation.**
   - No Public-only rewrite of the shared viewer, Equal/Focus state machine, immersive layout, YouTube player lifecycle, or PTT viewing layout is allowed merely to make deployment easier.
   - If a transplanted component fails, diagnose and adapt that component; do not replace it with a lookalike implementation.

6. **Acceptance is behavioral, not architectural.**
   - Public must reproduce the accepted 4174 result using the transplanted implementation.
   - CI, static similarity, or matching screenshots alone do not prove parity; the same user flow must work in-browser.

**Operational shorthand:** _copy 4174 first; run it; if it throws or proves incompatible, then adapt only that failing boundary._

## Frozen sidebar contract (exact visual order, icon, wording)
1. 今 — 今日直播 (`/`)
2. 史 — 歷史直播 (`/history`)
3. 視 — 同時視聽 (`/watchalong`)
4. 自 — 自訂觀看 (`/custom-view`)
5. 👥 — 多人連動 (`/collab`)
6. PTT — PTT 今日專串 (`/ptt-today`)

The Public static SPA may use internal hash routing, but this must not change labels, screen transitions, appearance or behavior observed by users. Do **not** introduce decorative English eyebrows; no new UI or design reinterpretation. 4174 source CSS tokens (light appearance, 72px collapsed/250px expanded rail, typography, spacing) are a reference, **not** proof of pixel parity.

## Migration state / outstanding differences

| Area | Public as of 2026-10-15 | Required accepted 4174 state |
|---|---|---|
| Sidebar labels/order | Corrected in source | Compare icon, hover, mobile and active state in browser |
| Shared shell / home | Re-authored static HTML/CSS | Port matching layout, cards, counters, color details and interactions |
| History | Simplified cards and pagination | Port accepted History 50/page union, date, verified-ended behavior and page layout |
| Watchalong | Video iframe only | Port 4174 watching session, PTT timing, controls and visual layout |
| Custom view | URL-to-iframe only | Port 4174 selection, audio, primary, layouts and session controls |
| Collab | Manual video IDs only | Port 4174 collaboration detection and multi-POV controls |
| PTT today | Placeholder-only | Port accepted reader, floor toggle and update behavior |
| Cached subtitles and other viewers | Not ported | Preserve accepted 4174 behavior and layout |

Do not mark any row as accepted without side-by-side desktop/mobile screenshots and interaction checks on both the exact 4174 reference and Cloudflare production. A passing CI or a lookalike layout **does not establish 100% UI parity**.

## Safe execution policy
- UI migration only: do not alter Cloudflare API permissions, deployed PTT Workers, D1 schema or local 4174/8501.
- Preserve the Public manual Cloudflare deployment and no-unbounded-polling rules.
- Any change to public data, copyright policy, credentials, API write paths or Cloudflare privileges requires a separate security review.
- Implement interface elements in the order of accepted 4174 source components; do not add embellishments to compensate for missing backend data.
