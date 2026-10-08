# HoloViewer — Project Status / Cross-window State Index
Updated: 2026-10-09 Asia/Taipei
Status owner: active integration/audit agent (NOT a chat-specific narrative)
**This is an evidence index, not proof of deployment or automatic synchronization. Always refresh GitHub and runtime state.**

## Immediate operating condition
- **DEVELOPMENT FREEZE**: only explicitly authorized documentation and read-only audit. No feature implementation, agent dispatch, merging, deployments, production DB changes, or D1 PTT Publisher restart.
- Product source of truth: live **8501 = functional behavior**; live **4174 = visual/UI behavior**. Runtime parity **NOT VERIFIED in this document**. Conflicts go to user; no agent arbitrates.
- [Mandatory guidelines](../HOLOVIEWER_PROJECT_GUIDELINES.md) and [AGENTS](../AGENTS.md) govern all new windows.
- User deleted the old Streamlit Cloud App; screenshot showed no apps in the current account. **GitHub Pages production acceptance remains UNVERIFIED.**

## Evidence-backed state (status observed 2026-10-09)
| Area | State / evidence | Verification limitation |
| --- | --- | --- |
| Private engineering | [Repo](https://github.com/physicsdog0505/Hololive-PTT-Viewer) has multiple open Draft PRs, including [#324](https://github.com/physicsdog0505/Hololive-PTT-Viewer/pull/324) | No implied acceptance, merge or deployed SHA |
| Public website | [Repo](https://github.com/physicsdog0505/HoloViewer) public `main` README describes Streamlit smoke preview; public [#10](https://github.com/physicsdog0505/HoloViewer/pull/10) is Draft | Not proof that GitHub Pages hosts finished site |
| D1 P0 incident | User-supplied Cloudflare metrics: ~179.87k rows written, ~1.62k write queries. Read-only SQL: 601 pushes, max cursor 174020, retention watermark 2420 | Root cause and deployed Worker digest **UNKNOWN** |
| Publisher | Earlier Mac command found no `ptt_live_relay_publisher.py` process | Current Mac process status **UNKNOWN**, verify on machine before any action |
| D1 write-amplification | An older Publisher watch loop repeatedly submitted up to 1000 rows per 5 seconds; a `received=1000, accepted=0` result was reported | Exact D1 billed row attribution **UNKNOWN** |
| WebSub tunnel | Mac `cloudflared tunnel --url http://127.0.0.1:8787` observed previously | Distinct from D1 Publisher; must not be terminated as cleanup |
| Accepted product | User designates 8501 function and 4174 UI as only authorities | Individual pages' acceptance mapping **NOT YET AUDITED** |
| GitHub governance | Existing `AGENTS.md`, development checklist, process review, lessons learned in private repo; shared guideline now in both repos | Policy documents do **not** prove enforcement |

## Incident boundaries and next safe investigations
1. Preserve Mac Collector SQLite and D1 evidence; no destructive SQL, live stress testing, Publisher restart or upgrade decision based on quotas alone.
2. Read actual Cloudflare D1 per-query Insights and deployed Worker revision where available; contrast with source history to determine write-amplification root cause, with VERIFIED/INFERRED separation.
3. Audit current GitHub PRs, accepted product baselines and CI/ruleset protection as **read-only**.
4. Inventory any externally running service only with authorized read-only operations; do not infer from GitHub code that a process is live.
5. Propose minimum recovery changes and gated checks; implementation/release only with renewed user permission.

## How to keep this index accurate
- On handoff or verified milestone/incident: update only statements backed by fresh evidence; specify checked date, URL, SHA and evidence class.
- Do not paste entire chat histories, invent statuses, or replace current source/runtime truth. If disputed, mark **CONFLICT / UNVERIFIED** rather than silently overwriting.
- This index is global; individual work belongs in task handoffs using [HANDOFF_TEMPLATE](HANDOFF_TEMPLATE.md).
- Before next work, read docs and CURRENT GitHub state; if status here differs, record discrepancy and stop unsafe progression.

## 2026-10-09 recovery triage checkpoint (evidence from current GitHub open-PR search)
**Purpose:** sort existing work, not initiate another implementation stream. No PR was merged, closed, retargeted, or deployed during this checkpoint.

**Current recommended execution sequence (not an authorization to execute while frozen):**
1. Keep Collector + accepted local 8501 function/4174 UI intact. Preserve D1/Worker evidence and leave Publisher OFF. Investigate cost root cause before any live writer restart.
2. Determine current exact SHA and deployment status of the public GitHub Pages site; identify the smallest existing public Pages Client branch that can preserve 4174 visuals and 8501 functions, rather than reimplementing them.
3. Reconcile the current PUBLIC PR stack: #8 Pages PoC (explicit DO NOT MERGE), #10 read-only Pages client, #12 canonical relay, #13-15 hardening, #16 integration, #17 parity-document contract and #18 behavior-changing reader. No blind sequential merge: these are stacked/overlapping alternatives and need a single verified integration decision.
4. Reconcile the current PRIVATE relay/snapshot stack: #311 canonical identity → #313 publisher and #312 projection → #315 snapshot, #318/#319 hardening, #321/#322 fixes, #324 integration. These are not independent merge-ready units. D1 incident safety first.
5. Other old private stacked ASR, historical backfill and client rendering PR families are **PARKED**, not failed and not deleted, until scoped against accepted 8501/4174 runtime. No parallel feature streams during recovery.

**Explicit HOLD labels (comments, not status mutation):**
- PUBLIC #6 and #7: obsolete Streamlit-preview lineage since user deleted hosted Streamlit app; no new Streamlit deployment.
- PUBLIC #18: proposed reader timing/interaction changed; may conflict with 8501. STOP until actual functionality is compared.
- PRIVATE #289: alternate full-VOD/progressive subtitles behavior; requires 8501 function and 4174 UI check.
- PRIVATE #325: governance expansion beyond existing guidelines; do not merge during cleanup.

**Known unknowns / blockers:** exact actual running 8501/4174 commits; exact GitHub Pages deployed SHA and functional acceptance; deployed Cloudflare Worker artifact; query-level D1 metered write attribution; current Mac process presence; complete individual PR diff/CI audit. No workflow document can substitute for these checks.

**Next receiving agent must do:** read root guideline + AGENTS + this status index; refresh current GitHub SHA and open PRs; choose ONE bounded read-only reconciliation step. Never confuse HOLD comments with technical enforcement. User requested visible, tidy handoff and ability to resume product development; do not create new feature Issues/PRs until risk and baseline alignment are demonstrated.

## 2026-10-09 read-only source inspection — D1 Publisher and Public reader
- Private [PR #313](https://github.com/physicsdog0505/Hololive-PTT-Viewer/pull/313), source `ptt_live_relay_publisher.py` at `cloud/issue-296-live-relay-canonical`: `--watch` initializes `seen_push_ids = set()`; `publish_cycle` excludes already seen IDs and updates the set only after successful publish calls. In-process idle cycles can therefore send zero pushes (verified from source logic, NOT live cost proof).
- **Unresolved safety gap:** set is *memory-only*, resets on process restart, and is deliberately cleared after >20,000 IDs; replays of the configured tail then remain possible. No durable checkpoint or production D1 daily write-budget circuit breaker found in this inspected module. This is a verified code-path limitation, NOT a claim that it caused the entire 180k billed writes. Publisher must remain STOPPED.
- Public [PR #18](https://github.com/physicsdog0505/HoloViewer/pull/18) diff changes read timing from `5/3/1` seconds row scroll to `1/0.5/0.2` seconds new-push reveal queue, adds session checkpoint; this is **behavioral divergence candidate**, not a safe automatic parity fix. Keep HOLD until actual 8501 function + 4174 UI evaluation.
- Private [PR #324](https://github.com/physicsdog0505/Hololive-PTT-Viewer/pull/324) is a stacked integration on #311 rather than a main-based deployable release. Public #10/#12-#16 similarly stack; do NOT blindly merge any.
- Current evidence only from GitHub files/diffs. Actual Mac services, deployed Worker and Pages SHA remain UNKNOWN. No runtime or D1 modification performed.

## 2026-10-10 Mac mini health & Collector safety check — pending (READ-ONLY)
Context: Cloudflare D1 exceeded free daily Rows Written quota on 2026-10-09. This **does not imply** equivalent local SQLite writes: inspected private PR #313 publisher uses `connect_read_only` to read Collector SQLite. However local resource health, unrelated writers, and growth are not yet measured. Do not declare the Mac safe without runtime evidence.

**Next user-attended session (not a scheduled automation):**
1. Identify actually running services/processes. Distinguish Collector / frontend 8501 / Client 4174 / backfill / D1 Publisher / YouTube WebSub cloudflared tunnel. Confirm the D1 publisher remains stopped **without killing Collector or** `cloudflared tunnel --url http://127.0.0.1:8787`. Be aware a process may use another name; absence of one filename alone is not proof of absence of all publishers.
2. Inspect system resources without installation or change: `df -h /`, `memory_pressure`, `ps -axo %cpu,%mem,rss,command -r | head -20`. If concern remains, inspect Activity Monitor memory pressure and CPU. Record output timestamp, Mac host and interpretation; do not disclose environment secrets or personal paths unnecessarily.
3. Identify **exact** authoritative Collector database path by documented runtime configuration, not guesswork. Inspect file size, modification time and available disk headroom read-only (`ls -lh`, `du -h` as appropriate). Check adjacent logs for unbounded growth without posting tokens or sensitive push content. Do not truncate/delete.
4. Confirm whether an existing backup/recovery path is documented and usable, without running a repair or modifying real DB. Any SQLite integrity/query check against operational DB requires a reviewed non-mutating procedure; favor isolated backup/snapshot for more intrusive checks.
5. Review background schedule/processes for unexpected redundant watchers or large backfills before resuming any work. No process termination, live PTT requests, schema changes, Collector restart, D1 Publisher restart, or Cloudflare edits during this inspection.
6. Independently review D1 deployed Worker version, Query Insights if accessible, actual write-amplification root cause, and safe restart criteria; D1 investigation is separate from local machine resource health.
7. Update this index with **VERIFIED / INFERRED / UNKNOWN** evidence, exact time, observed resource use, potential alerts, and specific next permitted step. If urgent low-disk space, severe memory pressure or high CPU appears, report risk and seek user authorization before taking any operational action.

**Status: PENDING.** No Mac commands have been executed by this GitHub-only agent; no result is implied. The user intends to do the system checks the following morning. No automatic background execution is scheduled.
