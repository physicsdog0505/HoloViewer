# Public PTT Reader parity contract (2026-10-09)

## Authoritative reference

Private `physicsdog0505/Hololive-PTT-Viewer`:
- `frontend_app.py` calls `frontend_chat.build_chat_html()` for current/historical reader, supplying `auto_follow`, `animate_new`, `message_delay_ms`, `storage_key`.
- `frontend_chat.py` builds a scoped chat viewport with `#chat {overflow-y:auto}`; new items are queued as hidden `.new` rows and revealed via a single `setTimeout` chain.
- Each revealed item persists `message.key` via `sessionStorage[storageKey]` so the same tab continues displaying pending new items after rerender.
- Jump Latest flushes pending rows and saves the latest message key. Delay affects **new-message reveal cadence**, not movement through rows that are already visible.
- For historical date view, `animate_new=False` (no staged replay of historical messages). Live view uses `animate_new=True`.

**Parity gaps identified (public PR #16 at review):**
1. `speedSelect` advances viewport scroll every 1/3/5 seconds through **already rendered history**; this is a different feature. Do not call it speed parity or ship as equivalent.
2. Public `goLatest()` only scrolls; it does not flush pending reveal queue because no queue exists.
3. Public has no per-tab reader queue/checkpoint state; existing UI is not equivalent to private sessionStorage behavior.
4. Public renders all snapshot pushes immediately. This is correct for historical baseline; stage only **new** relay pushes when the authoritatively defined viewer mode requests it.
5. Both private and public implementations require stronger manual-scroll override behavior so user scrolling upward is never overridden by follow/reveal.

## Required behavior before owner acceptance

- Historical baseline appears immediately, keeps floor/source-line ordering, permits unrestricted manual scrolling; no 1/3/5-second auto-scroll through old rows.
- New live relay pushes are appended to an ordered presentation queue; visual reveal cadence is independent of Relay polling, authentication, backend collection cadence, and snapshot ingestion.
- Slow/normal/fast delay controls **queue reveal**, not scrolling. Use current authoritative preferences instead of hardcoding old version values; frontend_app.py currently offers 200/500/1000ms with 500ms default in advanced settings and a quick-display toggle.
- Manual scrolling upward pauses auto-follow; queued messages may continue to become visible without changing the user's scroll position. If reading position is preserved during DOM mutations, it must not jump.
- Jump Latest reveals all queued messages immediately, clears pending playback timers, advances per-tab checkpoint, and resumes following. Repeating Jump Latest is idempotent.
- Toggle follow off means no automatic scroll. Toggle follow on may explicitly return to latest; never silently re-enable after manual upward scrolling.
- Changing AID clears old queue/timers and isolates callbacks/state; a delayed prior AID poll cannot update the newly selected thread.
- A transient Relay error retains baseline, cursor and queue; idle successful polls do not rebuild the entire DOM.
- A failed multi-page poll commits neither pushes nor gap/cursor flags; history gaps remain partial until proven coverage.
- Initial local real dataset was 3,169 pushes across three articles (27/519/2623). Do not publish that JSON to GitHub/Pages. Browser performance acceptance must include 2,623+ rows and manual upward scrolling during incoming pushes.
- UI controls must be responsive and keep labels readable; keyboard and touch-scroll behavior should match wheel.

## Required automated evidence

1. Behavior test with fake timers: append N new messages, reveal exactly one per configured interval, queue state and checkpoint advance; old baseline is already visible.
2. Manual-scroll test: while queue drains, neither scroll restoration nor auto-follow snaps user downward until explicit Jump Latest / resume.
3. Jump Latest: clears timer, reveals all, checkpoint persists and repeated clicks are safe.
4. Switch-AID cancellation and stale-result test, including delayed failures and multi-page partial batch rejection.
5. DOM or browser-like test verifying initial long article, idle Relay, new pushes, and no layout jump.
6. Read-only fetch contract guard validates actual network methods rather than banning incidental substrings in all JS text.
7. Run complete public CI and independent compare/review against current private HEAD before any user-facing acceptance.

## Scope / release gates

This document is a behavior contract, not a claim that parity is implemented. Public and private frameworks have different DOM structures and may require an adapter; preserve semantics instead of copying implementation literally. Private source has a conditional `moveTo()` during reveal but lacks an explicit user-pause state; user-reported manual-scroll priority is an additional acceptance requirement.

No deployment, real data upload, secret access, local Collector modification or PR merge without explicit owner approval.
