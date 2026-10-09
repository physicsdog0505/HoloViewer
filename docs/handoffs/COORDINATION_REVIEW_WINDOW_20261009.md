# HoloViewer — Delegated Coordination / Review Window Handoff
**Created 2026-10-09. STATUS: PROPOSED — AWAITING OWNER REVIEW. DO NOT START OR DISPATCH ANY WORK.**

## 0. Separation of chat responsibilities
- **Architecture / lessons / strategic project discussion:** remain in the ORIGINAL conversation. This chat owns user decisions about architecture, product boundaries, workstream design, disagreements, and process critique. It is NOT a development, dispatch, or PR review execution channel going forward.
- **NEW coordination / assignment / review chat:** becomes the sole operator for task decomposition, developer prompts, GitHub assignment records, PR review, corrective feedback and handoff verification **after explicit owner activation**. It must not implement features itself. It must escalate architectural/UX/product decisions to owner in the original architecture conversation instead of deciding autonomously.
- **Separate development chat(s), only after individually authorized dispatch:** implement one bounded task on assigned existing branch/PR, record ALL activity on GitHub, report an already-uploaded final handoff + exact SHA. Coordinator reviews and routes corrections; owner approves decisions/deployments.

## 1. Mandatory onboarding (must demonstrate, not merely recite)
Read fresh current GitHub files in BOTH repositories, starting with:
- https://github.com/physicsdog0505/HoloViewer/blob/main/HOLOVIEWER_PROJECT_GUIDELINES.md
- https://github.com/physicsdog0505/Hololive-PTT-Viewer/blob/main/HOLOVIEWER_PROJECT_GUIDELINES.md
- BOTH AGENTS.md, docs/PROJECT_STATUS.md, docs/HANDOFF_TEMPLATE.md
- Private docs/DEVELOPMENT_CHECKLIST.md, docs/PROCESS_REVIEW.md, docs/LESSONS_LEARNED.md; current relevant source/issues/PRs.
Guide blob at preparation: `df945e8771be171db9a9dc5e0024d62d18b38763`, status blob `41376ca9efc9aaa9a9b1b872372416f5e035d738` in BOTH repositories. Recheck before acting; hashes can change.
The first substantive response MUST report actual read links and revisions, target repos/current branch and HEADs, intended capability REVIEW/COORDINATE ONLY, what is verified vs unknown, authority/freeze boundaries, and any stale references. If repository content can't be accessed, pause.

## 2. Owner's authoritative architecture (not subject to reinterpretation)
- **Port 8501:** internal engineering data, core logic, source/data correctness, synchronization and functional validation, diagnostic controls.
- **Port 4174:** owner-operated **local production-preview** and the authority on user-facing content, visible behavior, interaction design, UX/UI; uses the SAME core logic as 8501, typically fewer/simplified user-facing controls. Owner continues acceptance on 4174 — **no extra preview websites or repeated acceptance of unchanged functions**.
- **Public GitHub Pages:** deliver the already accepted 4174 product faithfully. The outstanding cloud engineering difference is replacing local data access with public safe snapshots/APIs; verify deployed public data completeness, freshness, safety, parity, and actual SHA there. Public may not invent reader controls, screens, navigation or UX.
- **New underlying logic:** implement/validate 8501 first, then integrate for users on 4174; pure UX/UI can be reviewed on 4174. 8501/4174 must not diverge in core logic. Conflicts to owner, whose default public-facing preference is the accepted 4174.
- Existing Public #16/#18 code or controls (including `article-select`, 5/3/1s row auto-scroll or 0.2/0.5/1s reveal) are NOT automatically accepted product requirements.

## 3. Workstream plan — NOT YET DISPATCHED
A. **4174 continuity:** protect active local product preview, owner acceptance, only approved UX/UI, no retroactive 8501 UI cloning.
B. **Public fidelity to 4174:** copy actual 4174 approved screens/interactions, preserve data contract, adapt read-only public snapshot/API delivery; validate cloud DATA and release, not duplicated UI.
C. **8501 core validation → 4174 presentation:** code/core data fixes/new underlying behavior tested first in 8501 before 4174 UX integration.
D. **Independent operational repairs:** D1 Publisher, retention, backfill, ASR etc in isolated offline workflows subject to existing freezes.

Coordinator must first review branch ownership/dependencies to avoid conflicting edits. **Arrange and approve each workstream separately with owner**, one at a time. No creating new Issue/PR, agent or test site merely to record process when existing GitHub PR and docs suffice.

## 4. Protected boundaries / current blockers
- No unapproved: PR merge, prod GitHub Pages deployment or Cloudflare config updates, D1 writes or Worker changes, Publisher restart, production schema/data manipulation, Collector SQLite mutation, PTT login or credentials exposure, shutdown of 8501/4174 or YouTube WebSub cloudflared tunnel on port 8787.
- Previously running collector/publisher status and exact Mac runtime SHAs remain unverified from this GitHub-only window.
- Public #18 old task `docs/tasks/READER_8501_PARITY_HANDOFF_20261009.md` is **SUPERSEDED / DO NOT DISPATCH**. Its historical prompt wrongly sought direct 8501-to-Public UX parity. Public PR #18 remains Draft and has NO owner acceptance; PR #16/#17 stacked and must not be blindly merged. Owner correction: https://github.com/physicsdog0505/HoloViewer/pull/18#issuecomment-6073140146 .
- D1 historical cost/retention issue unresolved. Public relay may be intentionally off. Never silently resume writer or change production.
- Historical 3,169-push local PTT snapshot was already accepted for basic loading; no needless repeat testing. Not evidence of approved deployment or permission to publish private data.

## 5. Process for each delegated task (once owner authorizes)
1. Read mandatory guides/status and latest relevant PR/source; cite actual revisions. Prepare a bounded task brief with concrete deliverables, permitted/prohibited files/actions, source of truth, acceptance and stop conditions.
2. Ensure GitHub carries the authoritative task prompt, evidence, status, dependencies and owner decision BEFORE distributing prompt to developer. Invite owner to review task text; **wait for owner activation**.
3. Developer posts its own preflight and substantial progress/decisions/commits/tests in GitHub PR/task log and uses existing scoped branch. Each major claim must have a link/SHA/test evidence; distinguish CODED/TESTED/DEPLOYED/HUMAN ACCEPTED.
4. Developer completes a full GitHub handoff following docs/HANDOFF_TEMPLATE.md BEFORE giving chat a summary. User pastes handoff link/text back to coordinator.
5. Coordinator independently compares requirements, code diff, tests, baseline and safety; requests corrections in PR/GitHub, not ad-hoc chat-only work; do not develop the feature. Escalate design/architecture uncertainties to owner/original discussion chat.
6. Coordinator presents a concise review verdict with exact evidence, current risk and next decision. Only owner authorizes merge, deployment, risky operations and next delegation.

## 6. Documentation/evidence inventory at handoff
- BOTH repository rules and project-status docs were synchronized on 2026-10-09 on main. Public commits guide `e123994`, status `c4ee396`; Private guide `e1d09ef`, status `cffda0e`. Both pairs had identical blobs on subsequent verification.
- Public PR #18 draft https://github.com/physicsdog0505/HoloViewer/pull/18 . Incorrect old developer task is conspicuously revoked in branch document, revocation commit `47ad523`; correction owner comment linked above.
- Current cloud deployed revision, running local 4174 code SHA, full per-page acceptance inventory, current D1 costs and live behavior cannot be established by these docs; explicitly mark UNKNOWN until verified.

## 7. NEW WINDOW HANDSHAKE / OWNER REVIEW GATE
The coordinator's **first** action after the owner pastes the startup prompt is READ AND REPORT ONLY: verify this handoff against current GitHub, check for discrepancies, present role separation and task readiness, and STOP. **Do not create tasks, PRs, prompts, commits, dispatch developers, change code, merge or deploy.** Wait for explicit owner message approving both this handoff and the first workstream. This chat will continue to be reserved for architecture review.
