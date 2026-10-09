# Workstream A — PTT Today Reader, 8501 functionality parity (2026-10-09)

**Owner authorization:** Delegate Workstream A implementation to a separate development window, sequentially. Coordinator chat performs review and corrective guidance **only**, no feature development. Existing Public Draft PR [#18](https://github.com/physicsdog0505/HoloViewer/pull/18) and its current branch `feat/public-reader-reveal-queue-parity` are the work location. Do not create new feature branches/PRs unless demonstrably necessary and approved.

## Mandatory preflight — MUST be the first text in the developer's prompt

```text
[HOLOVIEWER MANDATORY PREFLIGHT — READ BEFORE ANY ACTION]
Repositories:
- Private: https://github.com/physicsdog0505/Hololive-PTT-Viewer
- Public: https://github.com/physicsdog0505/HoloViewer
FIRST read HOLOVIEWER_PROJECT_GUIDELINES.md from the CURRENT GitHub default branch of the target repository; for cross-repository work read BOTH copies. Then read AGENTS.md, docs/PROJECT_STATUS.md, the task handoff prepared using docs/HANDOFF_TEMPLATE.md, and relevant docs/Issues/PRs/current code.
In your first substantive reply report file link + revision actually read, the PROJECT_STATUS checkpoint and any discrepancies with current evidence, repository/branch/HEAD, VERIFIED facts versus UNKNOWNs, 8501 functionality and 4174 UI boundaries, active freeze, permissions and stop conditions. If you cannot read the files, STOP: do not guess.
NO unapproved feature/UI/behavior changes. Conflict between 8501 function and 4174 UI -> STOP and ASK USER. No merge, deployment, live DB writes, D1 Publisher restart, destructive changes or new development dispatch while freeze is active.
TASK: Bring existing Public Draft PR #18 PTT Today reader behavior into faithful parity with the currently running Private port 8501; preserve port 4174 UI styling. The exact implementation must be justified against baseline evidence, not inferred from PR titles.
CAPABILITY: IMPLEMENT (bounded, D1-independent, offline test only)
ALLOWED: Read both repos and existing docs, update only the existing #18 branch reader code and directly related offline tests, commit/push to that branch, publish progress/handoff on GitHub PR #18.
PROHIBITED: Modify Private Collector DB or runtime, start PTT crawler/Publisher, live D1/Worker operations, alter the running 8501 or 4174 services, widen UX/functional scope, rework other pages, merge/deploy, request repetitive owner retesting, expose credentials/private database, dispatch further agents.
STOP CONDITIONS: Cannot substantiate 8501 live behavior, conflicts with 4174 styling, ambiguity about approved controls or changed functionality, failure without reproducible cause, need to change shared cloud data contract, D1 or protected service. Document blockers and ask coordinator/owner.
```

## Mandatory project rules — complete current source (not this summary)

- Public rule: https://github.com/physicsdog0505/HoloViewer/blob/main/HOLOVIEWER_PROJECT_GUIDELINES.md ; private counterpart: https://github.com/physicsdog0505/Hololive-PTT-Viewer/blob/main/HOLOVIEWER_PROJECT_GUIDELINES.md . At dispatch, their content blob SHA was `6cc280c191460332538c7e0777a928ac7fb90a04` (refresh!).
- Public and Private `AGENTS.md`, `docs/PROJECT_STATUS.md`, `docs/HANDOFF_TEMPLATE.md`; private `docs/DEVELOPMENT_CHECKLIST.md`, `docs/PROCESS_REVIEW.md`, `docs/LESSONS_LEARNED.md`; relevant PR comments, Issue, source, current GitHub statuses.
- **Port 8501 is exclusively authoritative for function/interaction/data behavior; port 4174 for UI layout/styling.** An agent's interpretation or CI cannot supersede actual observed behavior. Conflicts require owner decision. Latest owner explicitly rejects adopting any unaccepted 1/0.5/0.2 or 5/3/1 behavior merely because it exists in a PR.
- Partial release of development is NOT approval for merge/deployment/production data operations. Protect Collector SQLite, PTT auth, D1 Worker, WebSub port 8787 tunnel. No Streamlit Community Cloud redeployment, no public export of secrets/DB.
- Separate `CODED`, `TESTED`, `DEPLOYED`, `HUMAN ACCEPTED`. Mark unknowns honestly; CI green alone does not constitute acceptance.
- Smallest scoped diffs, independent regression coverage and strict safety boundaries. No new abstraction, UI invention, or unnecessary PR chain.

## Scope and existing evidence

- Public target: PR #18 https://github.com/physicsdog0505/HoloViewer/pull/18 ; existing branch `feat/public-reader-reveal-queue-parity`; dispatch-observed head `3c7e7b26c008fc90aa4c71a4b4a88e06e4fa3416` (refresh before editing). Draft stacked on #17/#16; do not retarget/merge autonomously.
- Private **source** baseline at dispatch: `frontend_chat.py` blob `130abaf1c4ac934eace2357c30d54913d91d86fa` and `frontend_app.py` blob `be9437e2b3f7c90303ea0125a0a277baed70a194`. Private `main` defines scroll container, seen checkpoint in sessionStorage, `unseenStart`, new push reveal, flush via Latest or bottom scroll; `frontend_app.py` defines 200/500/1000ms, default 500ms; 300 default rows with 50/100/200/300/500 choices. **Source verified, actual running 8501 browser observation NOT VERIFIED by coordinator.**
- Public #18 previously misclassified snapshot rows already present after a checkpoint as seen. Recent branch changes attempt to restore unread checkpoint; re-review actual diff, not verbal claims. PR still has potential behavior differences: bottom-scroll flush, selecting article, manual scroll, item limit and effects of URL navigation. Do not assume #18 is accepted.
- Existing merged-to-branch fixes from #16: Public `public-data/config.json` `sources.live_relay:null`; PTT 16 MiB snapshot cap only; valid empty text body, nontext rejected. Do not regress D1 isolation or these safety checks. Public Demo fixture is **not** the historical 3169-row real snapshot; user already tested loading 3169 locally once and must not be asked to repeat unchanged basic checks.
- No agent has privileged access to the user's local 8501/4174 unless user expressly arranges a supported observation. If unavailable, explicitly label LIVE PARITY NOT VERIFIED, derive **tests from existing source**, and stop before asking owner to accept behavior.

## Bounded implementation plan and acceptance gate

1. Preflight and record current PR HEAD, both guidelines, docs, current 8501 source, 4174 styling evidence and current CI before modifications. Post GitHub PR #18 task-start comment with link to THIS handoff and a verified/unknown table.
2. Create a **behavior matrix** of existing 8501 source/live evidence versus #18 for first visit, reload with checkpoint, missing checkpoint, updated snapshot, new relay push, dedupe/order, hidden-row reveal interval, manual upward/downward scroll, bottom scroll flush, Latest flush, any existing article/navigation context (do NOT assume article switching exists), pause/follow, 300-row default and other existing controls. Mark every cell VERIFIED (source/live independently) or UNKNOWN. No UI redesign.
3. Write failing, executable DOM/runtime behavior regressions on actual Reader code for the mismatches, not just source-string assertions. Use synthetic data and zero live endpoints. Keep current separate snapshot/cost/relay checks intact.
4. Fix only **evidenced** differences in the existing #18 Reader code and tests; avoid changing shared `pollRelay`, Cloudflare, playback/watchalong, homepage, or global CSS. If an actual baseline conflict arises, STOP the affected change and ask.
5. Run required Public tests: `python3 -B -m unittest -v test_pages_poc test_public_smoke`, `node test_cloud_client.mjs`, `node test_relay_worker.mjs` (offline), plus any direct Reader behavioral test and PR CI. State exact versions and results; if not runnable, explain and mark untested. Confirm no production Pages deployment triggered.
6. Record **every substantial milestone**, issue encountered, fix and test result to PR #18 comments (or this handoff file if needed) with commits and evidence. No chat-only state.
7. Completion is **Draft PR prepared for independent coordinator review**, not deployment or human acceptance. Final handoff must already exist on GitHub when reporting to user. Use docs/HANDOFF_TEMPLATE.md headings; link to final comment plus SHA, changed files, tests, untested behavior, rollback, protected boundaries, and next decision. Explicitly report `CODED`, `TESTED`, `DEPLOYED: NO`, `HUMAN ACCEPTED: NO`. User will paste that handoff back to coordinator.

## Separation of duties

- **Developer window**: implementation + tests + GitHub evidence and final handoff only.
- **This coordinator window**: review, corrective feedback, accept/reject readiness for owner verification; no feature code development.
- **Owner**: sole authority on product baseline conflicts and any merge/deployment/production writes.

## Initial dispatch checkpoint

- Status: **ASSIGNED / NOT STARTED**. No developer has acknowledged this task yet.
- This file + PR #18 issue comment are the permanent GitHub task log entrypoint. New execution evidence goes to the same PR thread, not separate informal handoffs.

## Correction — user challenge, 2026-10-09
- **Article switching is NOT an approved 8501 feature.** The coordinator incorrectly promoted Public #18's `article-select` implementation into the user-facing task scope. Do not add, implement, or require article-switch UI based on this handoff.
- First verify which article/selection or navigation controls actually exist in live 8501. If no verified matching control exists, treat Public's selector as an **unaccepted divergence**, not a feature to replicate. Do not remove Public controls without scope/owner approval either; log discrepancy and request a decision.
- No repeated manual test request to user. Scope remains strictly 8501 reader parity.
