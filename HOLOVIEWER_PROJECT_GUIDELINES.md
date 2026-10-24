# HOLOVIEWER_PROJECT_GUIDELINES — mandatory first read
Last updated: 2026-10-25. Applies to **both** `physicsdog0505/Hololive-PTT-Viewer` (private engineering) and `physicsdog0505/HoloViewer` (public site), every ChatGPT/Codex/Antigravity/other agent, every new chat, handoff, review, implementation, and deployment task.

## 0. Read before acting (mandatory)
1. Read THIS file **from the current GitHub repository revision**, not a pasted historical copy. Read the counterpart file in the other repository when work crosses repository boundaries. The two copies must stay synchronized.
2. Read this repository's `AGENTS.md`, the relevant Issue/PR and comments, current code, and (for the private repo) `docs/DEVELOPMENT_CHECKLIST.md`, `docs/PROCESS_REVIEW.md`, `docs/LESSONS_LEARNED.md`, architecture and runbooks where relevant.
3. Read [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) and the task handoff using [docs/HANDOFF_TEMPLATE.md](docs/HANDOFF_TEMPLATE.md). Refresh actual GitHub and deployed state; report any stale status rather than blindly continuing.
4. Confirm repo, branch, HEAD SHA, task capability (INVESTIGATE / IMPLEMENT / HIGH_RISK), acceptance criteria, protected resources, and what is **actually deployed**. If a file cannot be read, state this and STOP risky work. Never pretend to have read it.
5. In the **first substantive reply**, explicitly report: guideline revision/link read; repo/branch/HEAD; task scope; permitted actions; prohibited actions; evidence gaps. Do not mistake reading a file or CI passing for compliance or user acceptance.
6. A task prompt without this preflight is incomplete. The agent must run this preflight itself even if the initiating chat forgot to include it.

## 0.5 Production Worker deployment hard gate (owner-approved lesson, 2026-10-25)

This gate applies to every Cloudflare Worker backend release, especially `holoviewer-public-api`. It was derived from the failed binding-preservation rollout before #231 and the successful #231 / #235 releases. Treat it as a mandatory deployment safety invariant, not optional ceremony.

1. **Lock the actual active Production version first.** Before building or uploading anything, run authoritative deployment readback and record the exact active Worker Version ID. That immediately-predeploy version is the rollback target. Do not reuse an older historical rollback ID just because it worked before.
2. **Lock exact source HEAD and test that exact HEAD.** Source review, focused tests, syntax checks and cost/read-amplification checks must refer to the candidate SHA that will actually be uploaded. A prior PASS does not carry across a new HEAD.
3. **Never trust a direct `wrangler deploy` or upload receipt as proof of runtime parity.** A Worker can upload successfully and still lose version-bound runtime resources. The 2026-10-24 rejected candidate `c20c90bc-04e4-409a-aa1f-4b4558847e71` returned HTTP 200 on some routes but had lost 12 Production plain-text bindings and caused Today/WebSub regression.
4. **`--keep-vars` alone is NOT a parity proof.** The rejected preview candidate `7f508a34-dc11-4f06-9def-c4239a7ed2a5` still lacked the same plain-text runtime bindings despite using a keep-vars flow. Always inspect authoritative version resources for both the active version and the candidate using `wrangler versions view <version> --json`.
5. **Compare candidate vs active version resources by name and type before traffic cutover.** Required result is exact parity for all runtime resources that the current service depends on: plain-text vars, secrets, D1 bindings and any other versioned resources. Compare names and types; report missing, extra and type differences. The accepted #231/#235 baseline happened to be 31 bindings = 19 plain_text + 11 secret_text + 1 D1, but **the number 31 is not a permanent contract**. The contract is exact parity with the current active Production version unless the release explicitly and intentionally changes resources.
6. **Preserve active plain vars from authoritative version resources without printing secret or sensitive values.** Build a temporary deploy config from the active version's plain-text values plus the reviewed base config. Keep generated configs in disposable local paths (for example `/tmp`); do not commit runtime values.
7. **Upload candidate with zero Production traffic first.** Record candidate Worker Version ID and preview URL. Immediately confirm Production still serves 100% of the old active version.
8. **Run preview semantic parity, not just HTTP smoke.** Compare the candidate preview with current Production for unchanged critical behavior. For Today, compare row count, lifecycle-state distribution and video-id set; for profile releases compare existing single-profile output and required fields such as non-empty `avatar_url`; exercise the new endpoint with real known IDs. A 200 response alone is insufficient.
9. **Use valid endpoint semantics in regression checks.** Do not misclassify expected 400s as regressions: for example `/v1/history` requires a valid `day=YYYY-MM-DD` query. For API CORS/read checks use GET/OPTIONS rather than HEAD unless the route explicitly supports HEAD.
10. **Verify protected dormant/write boundaries before cutover.** If a release is read-only, prove no new writer/migration/backfill path was introduced. For the current Collab rollout, `POST /internal/collab/live` must remain `503 {"error":"publisher_disabled"}` until a separately approved publication gate. Capture read-only D1 counts when they are part of the protected invariant.
11. **Cut traffic only by the already-verified candidate version ID.** Use `wrangler versions deploy <candidate>@100%`; do not rebuild/re-upload during the final cutover step. This preserves the exact artifact that passed parity and preview checks.
12. **Post-cutover authoritative readback is mandatory.** Re-run deployment status, critical API checks, the newly added endpoint, required payload semantics, dormant/write gates and any protected D1 invariants. Only then label DEPLOYED/PASS.
13. **Rollback immediately on semantic regression, not only transport failure.** If Today collapses, lifecycle sets diverge unexpectedly, required profile/avatar fields disappear, bindings differ, or a dormant writer becomes active, route 100% back to the immediately previous active Worker version and investigate offline.
14. **Record the deployment receipt on the owning PR.** Include exact source SHA, accepted Worker Version ID, rollback version, binding/resource parity result, preview gate result, post-cutover readback and protected no-write/dormant evidence.

Verified successful pattern:
- #231 accepted Worker `4fd32112-3233-4203-97d8-9e2823b98c81`: exact resource parity, preview semantic parity, dormant Collab writer, then 100% cutover.
- #235 accepted Worker `1edc5f00-5660-4721-8b74-287a78b0aecd`: exact resource parity, single-profile parity, batch-profile + avatar preview gate, Today parity, then 100% cutover.

The important lesson is **version-resource parity + semantic preview parity + exact-version cutover**. Passing source review, passing tests, successful upload, or HTTP 200 by themselves are not sufficient Production evidence.

## 1. Authoritative THREE-STAGE product architecture (owner clarification, 2026-10-09; supersedes earlier 8501=all user-facing behavior interpretation)
- **8501 = INTERNAL development and verification** of source data, complete engineering information, acquisition/synchronization, core behavior/underlying logic and diagnostics. It is NOT the public user interface specification; engineering controls need not appear publicly.
- **4174 = OWNER'S RUNNING LOCAL PRODUCTION PREVIEW and authoritative USER-FACING product**: content selected for users, layout, presentation, controls, user journeys, UX/UI and user-visible behavior. Owner continually inspects and accepts changes THERE, not on proliferating test websites. Its functions are a user-oriented subset or simplified presentation of capabilities proven in 8501.
- **Public deployed website = faithful delivery of the accepted 4174 experience**. Do not reinvent navigation, reader controls, viewing workflows, or UI. Main deployment engineering concerns are replacing local source access with secure timely public snapshot/API delivery and checking PUBLIC DATA correctness, coverage, latency and deploy integrity. Do not demand repeated owner acceptance of unchanged 4174 behavior.
- **Shared underlying logic:** 8501 and 4174 must not have divergent core data/behavior logic. If a requested 4174 feature needs new or changed underlying logic, implement and validate that logic in 8501 FIRST, then integrate the user-facing UX/UI in 4174. Pure presentation/UX changes can be designed and verified directly in 4174 without cloning those screens into 8501.
- **Conflict authority:** Only the owner decides when existing 8501 core behavior and 4174 user-facing behavior/UX conflict. Default user-facing preference is the owner-accepted 4174 behavior; do not change underlying logic without 8501 verification, and never guess an unaccepted choice.
- **Do not mistake a Public PR for product requirements.** Public #16/#18 reader speeds, article selector, and other prototype UI are NOT automatically owner-approved, even if CI passes or they appear in a branch. Neither source-code inspection nor a passing CI proves live 4174 acceptance; label unavailable observations NOT VERIFIED.
- **No invented parallel preview sites or repetitive owner acceptance tasks.** Keep current 4174 local preview available for ongoing user testing. If separate technical fixtures are essential, they are internal offline tests, not an alternate user-facing test product.
- **Four scoped workstreams (assignment requires distinct owner authorization):** A maintain/accept 4174 local product preview; B faithfully migrate accepted 4174 to public site and convert local data to safe snapshots/APIs; C verify new/changed underlying capabilities in 8501, then feed accepted 4174 integration; D independent offline infrastructure repairs. Separate file ownership/reviews, protect live services. Coordination chat REVIEW/CORRECTION ONLY, delegated developer performs coding.
- **Mandatory GitHub traceability:** full task brief, baseline evidence, preflight with guideline SHA, scope and risk, progress, decisions, files/commits, exact tests/results, unresolved items and final handoff MUST be recorded on GitHub before handing status back to owner. Developer sends owner a GitHub link + exact SHA; owner forwards to coordinator for review. No chat-only handoffs or unrecorded product decisions.
- No merge, production deployment, D1 writes/Publisher restart, protected Collector changes or other high-risk operation without separate explicit owner approval. Earlier partial-release restrictions continue.

## 2. PARTIAL DEVELOPMENT RELEASE — production safety remains higher priority
**Partial release authorized by owner on 2026-10-09:** Broad inventory is closed and bounded **D1-independent implementation** may resume on existing branches, including read-only GitHub Pages snapshot integration and offline tests. This is NOT authorization to merge, deploy production, write live data, restart the D1 publisher, alter production schema, delete/clean operational data, or change unaccepted UI/reader behavior. These HIGH_RISK actions remain frozen pending separate explicit owner approval. No new agent dispatch or parallel chat work unless the owner asks. Never use a documentation request to imply approval for protected operations.
- Cloudflare D1 free write quota incident: approximately 180k metered rows written, with only 601 rows currently visible; old 5s Publisher repeatedly transmitted up to 1000 recent pushes. Repetition is established; precise D1 cost attribution remains **unverified**. Do not restart after the daily quota resets.
- Protect private Collector SQLite (authoritative), local 8501/4174, Cloudflare Worker/D1 evidence, PTT credentials, API tokens, and the separate `cloudflared tunnel --url http://127.0.0.1:8787` used for YouTube WebSub. Do not shut down unrelated healthy services.
- Streamlit Community Cloud smoke app was removed by user on 2026-10-09: do not redeploy it; the public destination is GitHub Pages, subject to separate verification and approval.
- Never assume a private PR, public PR, or local test branch is in production. Confirm deployed artifact and SHA separately.

## 3. Evidence, scope and release gates
- **Source of truth for development:** GitHub current code, PR diffs, Issues and evidence. **Product truth:** live 8501 behavior and 4174 UI, ultimately user acceptance. **Operational truth:** actual running services, deployed versions, metrics, and real data.
- Label every material conclusion VERIFIED / INFERRED / UNKNOWN; provide commit/Issue/PR/test/runtime evidence. Historical handoffs and memory are pointers, not verification.
- Separate CODED / TESTED (exact tests) / DEPLOYED (actual URL + artifact revision) / HUMAN ACCEPTED. Never say 'done' because CI is green.
- Stay within an explicit Issue/goal and the minimum needed diff. Do not invent requirements, change read-speed semantics, add UI features, rewrite architecture, widen scope, change dependencies or infrastructure without authorization. If progress is blocked, explain cause and proposed options rather than autonomously launching a new Issue/PR chain.
- Private/public are separate deployment/security boundaries. Public code and assets must be reviewed for secrets, credentials, private SQLite, copyrighted media, and sensitive data before publication.
- Use isolated branches/worktrees and disposable data for authorized implementation; never commit to main as an incidental effect. Independent review must test specification **and** engineering safety. User must authorize merge, release, deployment, production data operations, and deviations from accepted behavior.
- State rollback, cost/usage budget, duration/stop conditions, and a real monitoring method **before** any live external-system test. Simulate failures and write amplification offline. No unbounded 5-second watch on production D1.
- No unauthorized secrets requests, destructive SQL, production DB schema changes, PTT crawler loops, or cloud plan upgrades.

## 4. Cross-window governance
- No chat/agent may claim to control or stop another chat/agent unless it can verify this. An instruction recorded on GitHub is NOT a technical enforcement mechanism.
- Before delegating, the dispatcher must explicitly prepend the mandatory prompt header below, identify the GitHub revision, allowed scope, and stop conditions. The receiving agent independently fetches and acknowledges this file and checks the *latest* state.
- Prefer reading existing documents to generating new process Issues. If there is a conflict between a prompt, prior handoff, old Issue, and these rules, STOP and report it; for product baseline conflicts ask the user.
- Every handoff must list revision, exact evidence, changes, tests run/not run, protected boundaries, blockers, risks, and smallest next action. No unsubstantiated claims of syncing to GitHub.

## 5. Mandatory prefix for EVERY future development prompt
Copy this at the **very beginning** of any prompt sent to another development window/agent. Replace the placeholders, do not omit the first instruction:

```text
[HOLOVIEWER MANDATORY PREFLIGHT — READ BEFORE ANY ACTION]
Repositories:
- Private: https://github.com/physicsdog0505/Hololive-PTT-Viewer
- Public: https://github.com/physicsdog0505/HoloViewer
FIRST read HOLOVIEWER_PROJECT_GUIDELINES.md from the CURRENT GitHub default branch of the target repository; for cross-repository work read BOTH copies. Then read AGENTS.md, docs/PROJECT_STATUS.md, the task handoff prepared using docs/HANDOFF_TEMPLATE.md, and relevant docs/Issues/PRs/current code.
In your first substantive reply report file link + revision actually read, the PROJECT_STATUS checkpoint and any discrepancies with current evidence, repository/branch/HEAD, VERIFIED facts versus UNKNOWNs, 8501 functionality and 4174 UI boundaries, active freeze, permissions and stop conditions. If you cannot read the files, STOP: do not guess.
NO unapproved feature/UI/behavior changes. Conflict between 8501 function and 4174 UI -> STOP and ASK USER. No merge, deployment, live DB writes, D1 Publisher restart, destructive changes or new development dispatch while freeze is active.
TASK: <explicit task and acceptance criteria>
CAPABILITY: <INVESTIGATE | DOCUMENTATION ONLY | IMPLEMENT | HIGH_RISK>
ALLOWED: <precise actions>
PROHIBITED: <precise actions>
STOP CONDITIONS: <explicit conditions>
```

## 6. Enforcement limitation / follow-up
These are mandatory **human-readable rules**, not proof an agent read them. During the freeze the audit must separately assess branch protection, required checks, prompt/templates, CI policy gates and protected deployment credentials. Do not claim automatic enforcement until tested. The user's decisions take precedence when explicitly communicated and must be reflected in both copies without quietly changing old accepted behavior.

## 7. OWNER OVERRIDE — product-first delivery, low Actions cost (2026-10-11)
**This section supersedes any conflicting routine development/review ceremony above, including automatic PR/review/Full CI expectations, while preserving explicit authorization for merges, production/public deploys, operational data, secrets, paid APIs and other high-risk changes.** The owner has reported repeated regressions in previously working features, excessive GitHub Actions usage and repeated owner debugging. Treat these as process failures, not reasons to impose more gates.

1. **Deliver the requested behavior, not process artifacts.** Before coding, write a one-sentence before/after acceptance scenario grounded in the owner's existing working 8501 core and accepted 4174 UI. Implement only the requested delta. Do not introduce unrequested daily API limits, new flags, UI redesigns, quotas, architectures, or feature restrictions. For example, 'background translate' means the existing complete translation runs asynchronously; it must not silently become a 12-generation-call-per-day feature. Any behavior change requires owner agreement.
2. **Developer owns baseline regression and first-line verification.** Check unchanged accepted workflow plus new workflow using isolated, offline, focused checks before asking the owner. When an actual browser/API/runtime test is impossible, say precisely NOT VERIFIED and give the smallest owner acceptance step; never substitute mocks, CI PASS or reviewer PASS for user-visible operation. Do not make the owner repeatedly restart 8501/4174 or troubleshoot basic errors; combine updates into one owner-authorized acceptance window.
3. **Protect operating 8501 and 4174.** Preserve already-working full-video Gemini translation, Corpus, checkpoints and stable player behavior; preserve owner-accepted 4174 UX. Maintain a reversible Git commit and known running revision; no unrelated refactor or shared-checkout branch switch affecting the owner's session. For changes touching video translation, first verify original full VOD translation semantics and that playback is not blocked.
4. **Light-by-default and bounded CI.** Keep PR/push Light checks. Do not dispatch Full automatically or merely for ceremonial review. Choose local/offline focused tests and record actual commands/results; run the manual Full only for integration, significant regression risk, or owner-requested release verification and with an exact target SHA. Avoid unnecessary repeated PR pushes, workflow triggers, test matrices and cost-expensive reruns. Do not claim quantified cost savings without billing evidence.
5. **Risk-based independent review, not infinite review loops.** Block on demonstrated functional breakage, accepted-behavior regression, material security/data-integrity risk, or clearly failed mandatory integration tests. Triage stale or inconsistent tests to developer-owned batch fixes; distinguish evidence of failure from tests never executed. P2/docs/style and harmless cleanup are follow-ups, not repeated owner gates. Review as a single concise pass when useful, not default multi-round ceremony. Production release, secrets, irreversible data and unbounded paid provider usage retain safety controls.
6. **One owner per feature, reuse existing work.** No duplicate A/B/C/D workstreams, unnecessary branches/PRs or independent UI rebuilds. 8501 remains core function authority, 4174 remains accepted user-facing product, and public deployment adapts the accepted 4174 rather than recreating it. Reuse existing Issue/PR and post one accurate GitHub handoff rather than spawning more process documents.
7. **Use honest delivery labels.** CODED, focused TESTED, Light CI PASS, Full CI PASS, REVIEWED, BROWSER VERIFIED, OWNER ACCEPTED, MERGED and DEPLOYED are independent states. Do not call a feature done or hand it to the owner as usable without stating what's been verified in a real application. Prioritize a working, owner-accepted outcome over high check counts.
8. **Review and implementation follow the latest owner decision.** If older checklists say every routine change requires new branch, heavyweight Full CI, independent review or owner action, this product-first policy controls routine recoverable 8501/4174 development. Do not relax constraints for production D1/Collector, Public deployment, credentials, data loss, live quota/cost exposure, or merging without approval.

## Owner decision — 2026-10-11: streamlined code review and merge
- Routine 8501/4174 changes: implement the exact requested behavior, run focused **developer-owned offline/local checks**, commit and push reversible history. A PR, independent review, and GitHub Actions CI are **not mandatory** for each routine iteration. Human acceptance of visible features occurs on the existing 8501/4174 environments, not through CI badges.
- When a PR is used for integration or owner-requested independent review, the reviewer inspects **current HEAD**, requirement fit, existing working-function regressions and material security/data risks. Provide PASS / PASS WITH CONDITIONS / REQUEST CHANGES and explicitly distinguish what was and was not executed. Non-blocking cleanup is follow-up, not endless approval loops.
- **A PASS means code is eligible for the owner's merge decision, not automatic merge, not proof of browser/product acceptance.** Explicit owner permission is required before merging; a reviewer does not silently merge. GitHub branch protection or required status checks, if actually configured, remain applicable until explicitly changed.
- No GitHub CI is automatically triggered by PR or push. Manual workflow_dispatch tests are optional for ordinary development and may be requested for significant integration risk or release; do **not** impose Full CI as a universal PR merge prerequisite. Developers still own basic verification.
- Public deploy, live D1/operational SQLite/Collector, secrets, unbounded paid API usage or irreversible changes need distinct owner approval and proportionate safety checks. No auto-deployment or deletion is authorized by this policy.
- Respect the owner's separate Antigravity investigation: no duplicate audit or workflow edits except when expressly assigned.


## 8. OWNER DECISION — Review is a continuation instruction, not a status-only handoff (2026-10-11)

**Purpose:** Reduce owner copy/paste, repeated “continue?” prompts, AI context use, and GitHub Actions spend. This section refines routine IMPLEMENT tasks under Section 7; it does not authorize autonomous execution across separate chat sessions or override protected operations.

### Standing task contract (bounded continuation)
- A developer already explicitly assigned an `IMPLEMENT` task retains authorization to **read the latest review on its existing PR and implement requested in-scope corrections**, with focused local/offline tests and a reversible commit/push on the same task branch. It must not stop after merely summarizing an actionable review.
- On receiving an instruction such as “check the review,” “review is up,” or “continue,” fetch **current PR HEAD**, latest submitted review, inline threads, and relevant Issue/PR comments. Check whether review refers to current HEAD or a stale commit. Do not treat a stale PASS as current approval.
- For `REQUEST CHANGES`: classify each finding as (a) verified, in-scope blocker to fix; (b) mistaken/stale claim to rebut with evidence; or (c) changed requirement/high-risk/out-of-scope issue to escalate. **Continue directly with (a)**: edit, run focused checks, push the existing branch, update the same PR with exact SHA and tests, then return a concise result. Do not request a second “please continue” authorization for already authorized, safe work.
- For `PASS WITH CONDITIONS`: fix actionable **in-scope blocking** conditions; distinguish optional follow-ups. If only nonblocking conditions remain, report **READY FOR OWNER DECISION** with evidence and stop; do not silently merge, deploy, or launch another review loop.
- For `PASS`: report **READY FOR OWNER DECISION** and smallest owner acceptance/merge step. Do not perform unnecessary code changes or rerun Full CI by default. Reviewer PASS is not browser acceptance or permission to merge.
- If review feedback is missing, ambiguous, contradictory, outdated, or blocked by environmental access, identify the precise blocker and the single needed decision. Never invent permission, make speculative changes, or claim a different chat has been notified.

### Reviewer-to-developer actionable handoff
- Independent reviewers must post their result to the **existing PR**, not only chat. Use one of `PASS`, `PASS WITH CONDITIONS`, `REQUEST CHANGES`, with exact reviewed HEAD and clear blocker/nonblocker separation.
- For each blocking correction give affected file/behavior, reproduction/evidence, expected outcome, and whether it is safe under the developer's existing IMPLEMENT scope. Conclude with `NEXT OWNER: DEVELOPER — FIX IN SCOPE` or `NEXT OWNER: USER — DECISION REQUIRED`. Avoid abstract “needs more review” loops.
- Developers read GitHub directly and act on this handoff the next time they are invoked; the human need only give the PR number or “review is up.” An Issue/PR comment **does not automatically wake another ChatGPT/Codex session**; no false claims of autonomous routing.

### Cost and stopping rules
- Do not trigger GitHub Actions merely because a review arrived. Use targeted local/offline checks; GitHub CI remains manual/risk-based under the latest owner policy. Do not create another PR, new worktree, speculative feature or full test matrix to process feedback.
- Batch closely related fixes into one push where safe. Stop after the in-scope correction and concise PR handoff; if the same root-cause fix fails twice, newly threatens a working baseline, increases live API/data costs, or crosses HIGH_RISK boundaries, escalate with evidence rather than cycling indefinitely.
- Production/public deployments, merges, secrets, D1/Collector and operational data changes still require explicit owner permission. Preserve accepted 8501 core behavior and 4174 UI, and use the existing verification environment.


## 9. OWNER DECISION — Short PR-number independent review command (2026-10-11)

### Accepted short commands
- `Review Private #<number>`: review that PR in `physicsdog0505/Hololive-PTT-Viewer`.
- `Review Public #<number>`: review that PR in `physicsdog0505/HoloViewer`.
- `Re-review Private #<number>` / `Re-review Public #<number>`: review current HEAD, verify previous blocking findings, and inspect any newly affected behavior.
- An unqualified `Review #<number>` is allowed only when the repository is unambiguous from the active task or a verifiable PR URL. Otherwise ask only which repository; never silently guess.
- These commands constitute authorization for a **read-only independent code review and posting review feedback on the existing PR**, not implementation, deployment, merge, or GitHub Actions execution.

### Reviewer execution contract
1. Fetch current root guidelines, AGENTS, project status and the relevant PR/Issue; verify repository, base, latest HEAD SHA, complete diff, previous reviews, inline threads and relevant comments. Follow the mandatory preflight without treating the short command as missing instructions.
2. Review actual behavior against owner-accepted 8501 core and 4174 UI, regression risks, security/data boundaries, cost and integration. Do not rely solely on the previous reviewer or green CI. For re-review, recheck previous blockers **against current HEAD** and any affected changes; do not inherit old approval.
3. Prefer existing offline/local evidence. **Do not dispatch GitHub Actions, paid API calls, live data tests, deployment, or speculative new agents** without separate permission. Clearly label unexecuted checks and browser/runtime acceptance as NOT VERIFIED.
4. Post **one concise actionable review on that same GitHub PR**, using `PASS`, `PASS WITH CONDITIONS`, or `REQUEST CHANGES`. Include reviewed SHA, only material blocking findings with file/behavior and reproduction or evidence, nonblocking observations, checks run/not run, and exactly one of `NEXT OWNER: DEVELOPER — FIX IN SCOPE` or `NEXT OWNER: USER — DECISION REQUIRED`.
5. Return a brief chat summary with PR link, SHA, verdict, blockers and next owner. **Do not stop after a chat-only review** when PR-comment access is available. If writing to GitHub fails, state that explicitly and provide the review text for manual posting.
6. Reviewer is independent and **read-only for code**; an earlier IMPLEMENT authorization for a different window is not transferred to the reviewer. Developer continuation after an actionable review follows Section 8 when that developer is next invoked.

### Boundaries
- Do not start another review cycle for P2/docs/style findings or to satisfy ceremony. Review remains risk-based, not an implicit Full CI requirement.
- GitHub comments do not automatically notify or wake a separate ChatGPT session. User can invoke that developer with `Review is up on Private/Public #<number>; continue`.
- Preserve owner approval for merge, public/production deployment and protected systems.
