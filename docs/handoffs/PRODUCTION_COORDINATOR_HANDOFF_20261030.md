# HoloViewer Production Coordinator Handoff — 2026-10-30

## Role of this coordination unit

This chat/unit is the HoloViewer / Holodocchi **Production coordinator and release gate**.

Primary responsibilities:
- GitHub reviewer for frontend/public release work.
- Production release gate and exact-SHA reviewer.
- Runtime/deployment-boundary owner.
- Cross-PR integration coordinator.
- Incident-safety reviewer.
- Owner-local deployment coordinator.
- Verify live GitHub state, PR head/base SHA, mergeability, diff, evidence, and Production readback.
- Distinguish VERIFIED / INFERRED / UNKNOWN.
- Decide READY_FOR_REVIEW / READY_FOR_MERGE / MERGE=HOLD / READY_FOR_OWNER_LOCAL_ROLLOUT / PRODUCTION_ACTIVATION=HOLD.
- Never treat CI green as Production acceptance.

The coordinator may merge reviewed PRs when explicitly authorized by Owner, but does **not** independently deploy Production.

## Fixed deployment policy

```
OWNER_LOCAL_DEPLOY=YES
GITHUB_ACTIONS_DEPLOY=NO
CI_DEPLOY=NO
CI_GREEN_IS_NOT_ACCEPTANCE=YES
```

Production mutation is executed only by Owner on the Owner machine.

Before any Production mutation require:
1. exact reviewed SHA;
2. clean checkout/worktree;
3. required bounded tests;
4. read-only Production preflight;
5. current active version / rollback target recorded;
6. runtime ownership and deployment unit verified;
7. controlled Owner-local activation;
8. live readback/smoke;
9. rollback path retained.

Do not claim Production acceptance until live readback is reviewed.

## Runtime boundaries

Treat these as separate deployment units even if code is in the same repo:

- PTT backend = Collector / Publisher / Today PTT line (original #48).
- Backend API = Production API Worker (original #47), Worker `holoviewer-public-api`.
- Public frontend = `holoviewer-public`, Production `https://holodocchi.com`.
- Historical packaging = #163 daily PTT history closeout.
- 8501 = main local frontend/admin runtime.
- 8502 = collaboration review/dev environment.
- 8503 = translation workspace; do not merge translation execution into 8501.
- YouTube lifecycle/runtime is separate.
- YouTube Static Assets Worker is separate.
- PTT Static Assets Workers are separate.

Never infer one runtime can be restarted/deployed because another runtime in the same repository changed.

Without explicit Owner authorization do not:
- restart Collector/Publisher;
- migrate/reset/move/copy production DBs;
- clear checkpoints;
- deploy API Worker;
- deploy PTT Static Assets;
- restart 8501;
- perform any Production mutation.

## Public frontend deployment

Repo:
`physicsdog0505/HoloViewer`

Production:
`https://holodocchi.com`

Worker:
`holoviewer-public`

Public custom domain is already live.

Normal frontend release gate:
- review exact GitHub PR/head SHA;
- merge only after review and explicit Owner authorization;
- fetch merged `main` exact SHA;
- create clean detached Owner-local deployment worktree;
- run the appropriate Owner-local release script;
- compare expected active Worker version;
- record rollback target;
- deploy from Owner machine only;
- review live readback.

Generic frontend release script:
`scripts/run_public_frontend_owner_release.sh`

Important: the generic release gate protects some runtime-owned paths, including `site/data/watchalong/**`. Do not force normal Watchalong asset changes through the generic frontend release script.

Watchalong static asset deployment uses the dedicated Owner-local unit:
`scripts/deploy_watchalong_event_owner_local.sh`

Always inspect the current scripts/runbooks at the exact candidate SHA before deciding which release unit applies.

## Frontend architecture constraints

- 4174 is old UI parity reference only.
- Do not introduce a new SPA.
- Pages remain independent HTML/JS/CSS where that is the accepted architecture.
- Viewer / Watchalong remain standalone.
- Owner acceptance is on the Production site; do not substitute local 4174 testing for Production acceptance.
- Viewer modes are fixed names: 預設｜輪播｜鎖定.
- Multi-VOD share-state experiment was rolled back; do not reintroduce it.

## PTT / archive reader constraints

Cross-day VOD coverage must be evaluated per Taipei day:

- COMPLETE => Archive only.
- PARTIAL/MISSING => Archive + bounded D1.
- Merge into one timeline.
- Do not hard-split previous day=Archive and today=D1.
- Do not claim authoritative zero unless coverage is COMPLETE and row count is zero.

## Review style

For every PR/release:
- verify live GitHub state instead of trusting pasted PASS labels;
- check base/head SHA and whether head moved;
- inspect changed files and scope;
- inspect unresolved review threads;
- verify tests and evidence;
- separate code acceptance from deployment acceptance;
- use exact SHA guards for merge;
- after merge, read back `main`;
- before deployment, read current Production active version instead of assuming the previously known one;
- after deployment, review actual upload list, new version, live readback, smoke, and rollback receipt.

## Current active work

### Watchalong Export Authority

Durable sources:
- `docs/handoffs/WATCHALONG_EXPORT_AUTHORITY_HANDOFF_20261030.md`
- Issue #290 — evidence/root-cause investigation.
- Issue #291 — Codex implementation task.

Known Production defect:
- `x7bMoyNWaEE` Public asset has 3 segments while current authoritative 8501 mapping has 4 sources and runtime transcript analysis shows 4 confirmed starts.
- Do not hotfix a hard-coded constant only.
- #290 confirmed the approved-sync authority chain is broken.
- `eFYByyw5AJc` is version-sensitive: legacy 7-source state must not override later corrected accepted 6-source sync.

Current gate:
```
PRODUCTION_HOTFIX=HOLD
WAIT_FOR_CODEX_291_EVIDENCE=YES
```

### Daily Digest v2 preview

Draft PR #288 exists for Daily Digest v2 layout/readability work.
Last reviewed preview head:
`f6a502496f239d58bf913b3e62f7777caa13672e`

This work is preview-only unless Owner explicitly resumes it.
No merge/deploy without fresh review.

## Recent Production frontend state

PR #289 was merged and Owner-local deployed.

Merge/release SHA:
`46119575acba0b686e6187959f096885cacdd593`

Resulting active Worker version from that rollout:
`09a0f6d0-dfe0-4fe2-b275-1df97c64aa31`

Rollback target recorded at rollout:
`5dc895ed-e328-4cdc-9f8a-4b09030bed8b`

Do not assume either version is still current for a future release; always re-read Production before mutation.

## Handoff rule for next coordinator/chat

Start by reading this file from GitHub.

For task-specific work, then read the relevant durable handoff / issue / PR.

Do not reconstruct the project from chat memory if GitHub durable sources exist.

Do not independently deploy Production.

Owner-local deployment only.
