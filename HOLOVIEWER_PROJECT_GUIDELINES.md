# HOLOVIEWER_PROJECT_GUIDELINES — mandatory first read
Last updated: 2026-10-09. Applies to **both** `physicsdog0505/Hololive-PTT-Viewer` (private engineering) and `physicsdog0505/HoloViewer` (public site), every ChatGPT/Codex/Antigravity/other agent, every new chat, handoff, review, implementation, and deployment task.

## 0. Read before acting (mandatory)
1. Read THIS file **from the current GitHub repository revision**, not a pasted historical copy. Read the counterpart file in the other repository when work crosses repository boundaries. The two copies must stay synchronized.
2. Read this repository's `AGENTS.md`, the relevant Issue/PR and comments, current code, and (for the private repo) `docs/DEVELOPMENT_CHECKLIST.md`, `docs/PROCESS_REVIEW.md`, `docs/LESSONS_LEARNED.md`, architecture and runbooks where relevant.
3. Read [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) and the task handoff using [docs/HANDOFF_TEMPLATE.md](docs/HANDOFF_TEMPLATE.md). Refresh actual GitHub and deployed state; report any stale status rather than blindly continuing.
4. Confirm repo, branch, HEAD SHA, task capability (INVESTIGATE / IMPLEMENT / HIGH_RISK), acceptance criteria, protected resources, and what is **actually deployed**. If a file cannot be read, state this and STOP risky work. Never pretend to have read it.
5. In the **first substantive reply**, explicitly report: guideline revision/link read; repo/branch/HEAD; task scope; permitted actions; prohibited actions; evidence gaps. Do not mistake reading a file or CI passing for compliance or user acceptance.
6. A task prompt without this preflight is incomplete. The agent must run this preflight itself even if the initiating chat forgot to include it.

## 1. Two authoritative product baselines (user decision, 2026-10-09)
- Running **port 8501** interface: authoritative functional behavior, interaction flows, controls, playback, synchronization, data behavior.
- Running **port 4174** interface: authoritative UI layout, appearance, visual structure/styling.
- **No function or UI change may exceed, silently replace, or reinterpret those baselines.** Do not infer parity from port number, screenshot, CI, or code alone: observe the actual interface, or mark comparison **NOT VERIFIED**.
- If these two interfaces conflict, or requirements cannot preserve both, **STOP the affected change and ask the user**. Only the user decides product tradeoffs; Issues, agents, and review approvals cannot silently overrule these baselines.
- New functionality or changed behavior requires a specific explicit user decision; do not infer permission from a broad objective, technical convenience, or a passing PR.

## 2. CURRENT FREEZE — safety is higher priority than progress
As of 2026-10-09 all **feature development, new agent dispatch, merges, deployment, live data writes, restarting the PTT D1 publisher, schema changes, deletion/cleanup, and unapproved UX changes are frozen** pending project audit and user release. Explicitly authorized documentation work and read-only investigation may proceed. A documentation request does NOT lift the freeze for other work. Do not spawn work in other windows as a workaround.
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
