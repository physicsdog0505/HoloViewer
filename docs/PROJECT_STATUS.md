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
