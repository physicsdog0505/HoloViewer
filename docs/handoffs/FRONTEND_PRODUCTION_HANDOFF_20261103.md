# HoloViewer / Holodocchi Frontend & Production Handoff — 2026-11-03

Last updated: 2026-11-03 (Asia/Taipei)

This is the durable handoff for the current frontend / Production-coordination work window. Read this file first in the next chat window, then read the exact PR/issue evidence for the specific workstream being resumed.

## 1. Role of this work window

This chat/unit acts as the HoloViewer / Holodocchi **frontend engineer + Production coordinator/release gate**.

Primary responsibilities:

- review and implement bounded frontend fixes;
- inspect the current public frontend source at exact SHA;
- preserve deployment ownership boundaries;
- prepare Owner-local release commands;
- verify exact release SHA, accepted Production source SHA, active Worker version, changed-file scope, and rollback target;
- review actual Wrangler upload list and dual-origin readback after deployment;
- keep GitHub durable evidence current;
- coordinate Daily Digest frontend/runtime integration when it crosses the public HoloViewer boundary;
- do not treat GitHub CI / GitHub Actions as deployment authority or Production acceptance.

The Owner may explicitly authorize merge and Production rollout. Production mutation itself is Owner-local.

## 2. Owner operating preferences

Persistent preferences observed in this work window:

- **Owner-local deploy only.**
- **GitHub Actions / CI must never block merge or Production rollout.**
- CI green is not Production acceptance.
- Prefer one complete, directly pasteable Terminal command block over long explanations.
- Keep chat responses short and action-oriented; put detailed technical evidence in GitHub.
- Do not ask repeated clarification questions when the current evidence is sufficient.
- Verify exact SHA / live version / changed-file scope before mutation.
- Do not silently broaden scope.
- Do not restart unrelated services.
- Do not touch Collector / Publisher / 8501 unless separately and explicitly authorized.
- Preserve local modifications; if the normal checkout is dirty, use a clean detached worktree instead of stash/reset/overwrite.
- Do not use Gemini as a test merely to prove plumbing; quota/cost matters.
- For Daily Digest unattended runtime, the accepted production mode is **persistent Terminal worker**, not launchd.
- Do not reintroduce launchd as a required Daily Digest production dependency unless separately reviewed and explicitly approved.
- Do not silently change Codex automation cadence; cadence/event-trigger work is a separate follow-up.
- When a bug is visually obvious, prefer a bounded fix + exact Production validation over generic architecture discussion.

## 3. Fixed deployment and ownership policy

```text
OWNER_LOCAL_DEPLOY=YES
GITHUB_ACTIONS_DEPLOY=NO
CI_DEPLOY=NO
CI_GREEN_IS_NOT_ACCEPTANCE=YES
```

Public frontend:

- repo: `physicsdog0505/HoloViewer`
- Worker: `holoviewer-public`
- custom domain: `https://holodocchi.com`
- workers.dev remains available.

Static ownership boundaries:

```text
frontend worker:        site assets only
YouTube static:         /youtube/v1/**
PTT static:             /ptt/v1/**
Watchalong static:      /data/watchalong/**
Daily Digest static:    /data/daily-digest/**
General VOD subtitles:  dedicated subtitle static worker
Alias static:           /data/search/aliases/v1/**
```

Generic frontend release must not publish foreign-owner static data.

## 4. Frontend release discipline

Normal flow:

1. inspect exact PR/head SHA;
2. verify site diff and ownership boundary;
3. merge only with Owner authorization;
4. fetch exact merged main SHA;
5. create a clean detached Owner-local worktree;
6. run `scripts/run_public_frontend_owner_release.sh <release_sha> <accepted_production_source_sha>` in PREPARE_ONLY mode;
7. capture current active Worker version;
8. require exact site diff and all predeploy gates PASS;
9. execute from Owner machine only with `--execute --expected-active-version <version>`;
10. verify actual Wrangler upload list, new active version, dual-origin readback, dedicated-target health, rollback target;
11. record Production evidence in GitHub.

If the Owner's normal checkout has local changes, **do not stash/reset them**. Use a separate worktree.

## 5. Daily Digest production runtime — current accepted state

Private operational repo:

- `physicsdog0505/Hololive-PTT-Viewer`

Public runtime repo:

- `physicsdog0505/HoloViewer`

Private Daily Digest production lineage:

- PR #567 — return finalize / production handoff fix
  - accepted candidate head: `83001f9bf10d9c12aa5163409d67c9666abab08f`
  - merged private main SHA: `f535f7b7bdb88c15039f4a0aa29671943845d31c`
- PR #568 — live month preservation across runtime repins
  - merged production runtime SHA: `f2a816b534438d97503e7443f496292e5cf9ecac`

Current accepted runtime:

```text
PRIVATE_RUNTIME_HEAD=f2a816b534438d97503e7443f496292e5cf9ecac
PUBLIC_RUNTIME_HEAD=2f19357ce3fe5a251d314ae8b55c3c5885d784db
WORKER_MODE=PERSISTENT_TERMINAL
WORKER_RUNNING=YES
SCHEDULE=08:10 Asia/Taipei
LAUNCHD_USED=NO
LIVE_DAYS=2026-11-01,2026-11-02
LIVE_SHA256=a93041c912dadd6535326b92db405ffeaf623f3bc1cb8e610debecc1fa8e2b64
LOCAL_LIVE_MATCH=YES
CURRENT_BLOCKER=none
```

Accepted chain:

```text
Daily Summary readiness
-> immutable Daily Digest input + ACTIVE_RUN authority
-> Codex exact Drive transport only
-> Gemini scheduled web task
-> Codex exact return transport
-> return_readback_complete
-> deterministic local ingest
-> validated_accepted
-> dedicated Daily Digest Static Assets publication
-> live byte readback
```

Important contract:

- Codex is Drive transport-only.
- Codex does not choose runs, call Gemini, ingest, publish, or deploy.
- successful download results must record exact source MIME / transfer mode evidence;
- once return transport is durably accepted, retries must not replay Drive transport;
- publication completion requires publication receipt + live readback;
- Daily Digest publication is dedicated static publication, not frontend deployment.

## 6. Daily Digest frontend Production state

Initial first Production frontend release:

- PR #324
- merge/release SHA: `5dfed4313baa873f688d7cc9a2bebae01600e499`
- resulting frontend Worker version: `321cbea3-4f7d-4d0a-b92a-ca9e7ccdffd7`
- Docchi News UI live.

Story truncation / normalizer work:

- PR #325
- merge SHA: `2f19357ce3fe5a251d314ae8b55c3c5885d784db`
- Daily Digest static republish was separate from frontend deploy.

## 7. Mobile Daily News RWD incident — resolved 2026-11-03

Owner reported mobile News story images visually breaking / using uneven widths.

### First bounded fix

PR #326:

- candidate head: `479e49ea973d26a0f19cc2f182e08d22a62cdbee`
- merged main: `63d742224d46b345d5f5d03dd4f1737c4a0d3746`
- intended to add mobile containment only.

During release review, current main and the last accepted Production frontend source had diverged. A direct deploy would have unintentionally carried unrelated site differences.

### Production-lineage reconciliation

PR #327:

- reconciliation candidate: `ef6016385b968b35864ebb1b3a1803e4a34b64c8`
- merged main / release SHA: `2497d00f22f39e42438e5fd9838eb75110972286`
- accepted Production source: `5dfed4313baa873f688d7cc9a2bebae01600e499`
- tree-level Production `site/**` diff after reconciliation: **only `site/assets/daily-digest.css`**
- PREPARE_ONLY PASS
- baseline frontend version: `321cbea3-4f7d-4d0a-b92a-ca9e7ccdffd7`
- Production release PASS
- resulting frontend version: `e734c1ee-7ac9-4ddb-aa74-9513896d1335`
- Wrangler uploaded exactly one asset: `/assets/daily-digest.css`
- dual-origin readback PASS
- GitHub Production evidence comment on PR #327: `6597290342`

The first production containment fix prevented overflow but did not fully correct uneven mobile visual-slot sizing.

### Root-cause fix

Actual conflict found in later layout-specific CSS:

- `hero-full-carousel` still applied `grid-column: span 6 !important` to slots 2–5 below 900px.
- the first mobile containment rule limited width but did not override those layout-specific `!important` slot spans.

PR #328:

- candidate head: `c9e389fec648ab1c3d0ab272617d65e4e78a2886`
- merged release SHA: `f68482c46b97dc831a517ebe7ab0061a12fbb7af`
- accepted Production source: `2497d00f22f39e42438e5fd9838eb75110972286`
- exact Production site diff: `site/assets/daily-digest.css` only
- mobile <=760px now forces all Daily News story visual layouts into one canonical full-width column;
- all visual slots use `grid-column:1/-1!important`;
- full-card width and 16:9 media ratio are preserved.

Owner-local release:

```text
SOURCE_RELEASE_SHA=f68482c46b97dc831a517ebe7ab0061a12fbb7af
BASELINE_ACTIVE_VERSION=e734c1ee-7ac9-4ddb-aa74-9513896d1335
NEW_ACTIVE_VERSION=0fdb4206-b79f-401d-a0fc-aeef668a7506
WRANGLER_UPLOAD=/assets/daily-digest.css only
DUAL_ORIGIN_READBACK=PASS
DEDICATED_TARGET_HEALTH_AFTER=PASS
GITHUB_ACTIONS_DEPLOY_USED=NO
CURRENT_BLOCKER=none
```

GitHub Production evidence comment on PR #328:

- `6597461647`

Owner visually confirmed the mobile issue is fixed. **This issue is closed.**

## 8. Important local-worktree safety note

During the mobile release, the Owner's normal `~/Downloads/HoloViewer` checkout had a local modification in:

- `site/assets/config.js`

Do not overwrite/stash/reset this merely to run a release. Use a detached release worktree.

A separate private repo working copy has also previously shown a local modification in:

- `gemini_translation_provider.py`

Preserve local Owner changes unless the Owner explicitly says otherwise.

## 9. Current frontend Production authority

Latest accepted public frontend release:

```text
SOURCE_RELEASE_SHA=f68482c46b97dc831a517ebe7ab0061a12fbb7af
ACTIVE_WORKER_VERSION=0fdb4206-b79f-401d-a0fc-aeef668a7506
ROLLBACK_TARGET=e734c1ee-7ac9-4ddb-aa74-9513896d1335
MOBILE_DAILY_NEWS_RWD=OWNER_VISUAL_ACCEPTED
CURRENT_BLOCKER=none
```

Do not assume these remain current forever; always re-read active Worker version before any new Production mutation.

## 10. Recent work completed in this window

Completed:

- Daily Digest unattended return/finalize/publication path reviewed and activated.
- Daily Digest runtime moved away from launchd dependency to accepted persistent Terminal worker mode.
- PR #568 production runtime activated successfully.
- Daily Digest 2026-11-01 and 2026-11-02 live and byte-matched.
- Daily Digest frontend / Docchi News initial Production release accepted.
- mobile Daily News image overflow/uneven-width defect diagnosed through two bounded fixes.
- frontend production lineage reconciled so unrelated current-main site drift was not silently deployed.
- final mobile single-column story-media fix released and visually accepted by Owner.
- PR #327 and #328 Production evidence recorded.
- GitHub Actions / CI were explicitly not used as deployment authority.

## 11. Next actions / pending items

Immediate state:

- mobile RWD issue: **closed**.
- Daily Digest production runtime: **active, no blocker**.
- frontend Production: **active, no blocker**.

Next meaningful work:

1. Observe the next scheduled Daily Digest cycle under the persistent Terminal worker and verify the unattended chain still completes normally.
2. Keep the Codex automation cadence/event-trigger question separate. Do not silently change cadence; the Owner previously rejected an aggressive 5-minute cadence.
3. If a new frontend issue appears, start from the latest live Worker version and exact accepted source SHA rather than assuming current `main` equals Production.
4. Continue using detached Owner-local release worktrees when the normal checkout is dirty.
5. Keep GitHub durable handoff/evidence updated before switching long chat windows.
6. No further work is required on the mobile Daily News RWD issue unless it regresses.

## 12. 2026-11-10 Daily Digest related-clips asset-loss incident

During the Owner-local publication of the accepted 2026-11-09 Daily Digest month shard, a clean detached publication worktree contained the canonical month data but did not contain the already-live related-clips sidecars. Wrangler therefore deployed an asset manifest that omitted those sidecars.

Observed Production evidence:

- Daily Digest 2026-11 month shard remained valid and included `2026-11-01` through `2026-11-09`.
- live month SHA-256 after the 2026-11-09 Digest publish: `a165c61ce1b3bf7e8161fdc1cd64b50ef0d13b24004272714cc0dcbb802b9af6`.
- immediately after that publish, related-clips endpoints for `2026-11-01` through `2026-11-08` returned HTTP 404 even though their local sidecars still existed in the related-clips runtime publication tree.
- `2026-11-09` had no clips sidecar yet and correctly remained pending for the persistent 30-minute worker.
- restore used the related-clips publication tree while first seeding the current live month shard.
- restore release moved the dedicated static Worker from `7c6bbccc-c44d-43a0-8c6d-7a66d4a5bfbf` to `939105da-d843-4a1c-8267-28fb76046d3b`.
- post-restore readback: `2026-11-01` through `2026-11-08` related-clips endpoints HTTP 200; month shard still contained `2026-11-01` through `2026-11-09` with the same SHA-256 above.
- related-clips worker PID 19971 remained active with `--poll-seconds 1800 --execute`.
- its canonical month authority was resynchronized to the live 2026-11 month shard and byte-matched the SHA above.

Root cause:

The Daily Digest static release gate validated month shards and any sidecars present in the local candidate, but it did not protect live sidecars that were absent from a clean publication tree. A valid month-only candidate could therefore remove previously published related-clips assets from the Worker asset manifest.

Permanent release rule:

- Daily Digest static `prepare` and `deploy` must preserve any already-live `YYYY-MM-DD-related-clips.json` associated with days in candidate month shards when those sidecars are absent locally.
- locally present sidecars remain authoritative refresh candidates and are never overwritten by the preservation step.
- HTTP 404 means no prior live sidecar and is allowed.
- any other live read failure/status fails closed before deployment.
- preserved sidecars are then validated by the same sidecar contract gate before release.
- Production mutation remains Owner-local only; GitHub Actions/CI are not Production authority.

Implementation branch: `fix/daily-digest-preserve-live-clips-20261110`.
PR: `#363` — Preserve live Daily Digest related-clips on month-only static releases.
Candidate head at handoff update: `f5634afb367b1175356041a56fd46951016d8bde`.
Regression coverage was added to `test_daily_digest_static_release_gate.py` for both live-sidecar preservation and fail-closed unexpected live status.

## 13. Handoff rule for the next chat

At the beginning of the next frontend / Production-coordinator window:

1. Read this file first.
2. Read the latest exact PR/issue evidence for the workstream being touched.
3. Do not reconstruct the project from chat memory when GitHub durable sources exist.
4. Establish exact current Production Worker version and exact repo/main SHA before a new release.
5. Preserve Owner-local changes and runtime boundaries.
6. Do not let GitHub CI / Actions block Owner-approved local merge/release.
7. Keep responses concise and operational.
