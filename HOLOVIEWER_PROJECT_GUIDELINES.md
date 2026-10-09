# HOLOVIEWER_PROJECT_GUIDELINES — mandatory first read
Last updated: 2026-10-09. Applies to **both** `physicsdog0505/Hololive-PTT-Viewer` (private engineering) and `physicsdog0505/HoloViewer` (public site), every ChatGPT/Codex/Antigravity/other agent, every new chat, handoff, review, implementation, and deployment task.

## 0. Read before acting (mandatory)
1. Read THIS file **from the current GitHub repository revision**, not a pasted historical copy. Read the counterpart file in the other repository when work crosses repository boundaries. The two copies must stay synchronized.
2. Read this repository's `AGENTS.md`, the relevant Issue/PR and comments, current code, and (for the private repo) `docs/DEVELOPMENT_CHECKLIST.md`, `docs/PROCESS_REVIEW.md`, `docs/LESSONS_LEARNED.md`, architecture and runbooks where relevant.
3. Read [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) and the task handoff using [docs/HANDOFF_TEMPLATE.md](docs/HANDOFF_TEMPLATE.md). Refresh actual GitHub and deployed state; report any stale status rather than blindly continuing.
4. Confirm repo, branch, HEAD SHA, task capability (INVESTIGATE / IMPLEMENT / HIGH_RISK), acceptance criteria, protected resources, and what is **actually deployed**. If a file cannot be read, state this and STOP risky work. Never pretend to have read it.
5. In the **first substantive reply**, explicitly report: guideline revision/link read; repo/branch/HEAD; task scope; permitted actions; prohibited actions; evidence gaps. Do not mistake reading a file or CI passing for compliance or user acceptance.
6. A task prompt without this preflight is incomplete. The agent must run this preflight itself even if the initiating chat forgot to include it.

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
