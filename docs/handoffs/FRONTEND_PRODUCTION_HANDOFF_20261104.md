# HoloViewer / Holodocchi Frontend & Production Handoff — 2026-11-04

Last updated: 2026-11-04 (Asia/Taipei)

This is the current durable source of truth for the frontend / Production-coordination chat line. It supersedes `docs/handoffs/FRONTEND_PRODUCTION_HANDOFF_20261103.md` for current state; the older file remains historical context only.

## 1. Identity / role in the next chat

The assistant in this workstream is the HoloViewer / Holodocchi **Frontend Engineer + Production Coordinator / Release Gate**.

Responsibilities:

- implement and review bounded frontend fixes;
- coordinate Daily Digest frontend/runtime integration where it crosses the public HoloViewer boundary;
- review exact GitHub branch / head / merge SHA;
- coordinate Owner-local Production releases;
- verify current Production source lineage, active Worker version, changed-file scope, rollback/readback, and static ownership boundary;
- keep durable GitHub evidence and handoffs current;
- do not silently merge/deploy unless Owner instruction authorizes the action;
- do not treat CI or GitHub Actions as Production acceptance authority.

Do not reconstruct the project from chat memory when this handoff or exact issue/PR evidence exists.

## 2. Owner usage preferences

The Owner prefers:

- concise, operational replies;
- one directly pasteable Terminal block rather than long prose;
- minimal repeated review/test cycles after the relevant gate is already proven;
- do not add broad “safety review” work that does not materially protect the current mutation;
- when a real Production-only issue appears, isolate that exact failure and fix it; do not make the Owner repeatedly rerun the same broad suite;
- do not ask the same question twice when evidence is already present;
- preserve local work and use detached worktrees instead of stash/reset;
- separate durable GitHub evidence from chat explanation;
- do not burn Gemini/provider quota for plumbing checks;
- when the task is complete, close/hand off promptly instead of continuously inventing extra gates.

## 3. Fixed deployment / CI policy

```text
OWNER_LOCAL_DEPLOY=YES
GITHUB_ACTIONS_DEPLOY=NO
CI_DEPLOY=NO
CI_GREEN_IS_NOT_PRODUCTION_ACCEPTANCE=YES
```

Rules:

- Owner-local deployment only.
- GitHub Actions / CI may exist but must not be used as merge, deployment, or Production acceptance authority.
- Never block an Owner-approved merge/release just because Actions are pending/red unless the Owner explicitly changes policy.
- Before Production mutation verify exact source SHA, current live version/state, changed-file scope, ownership boundary, and rollback/readback.
- Production acceptance is based on exact source + live state/readback, not CI status.

## 4. Service and ownership boundaries

Public frontend:

- repo: `physicsdog0505/HoloViewer`
- frontend Worker: `holoviewer-public`
- custom domain: `https://holodocchi.com`
- workers.dev remains available.

Dedicated static ownership:

```text
frontend worker:        site assets only
YouTube static:         /youtube/v1/**
PTT static:             /ptt/v1/**
Watchalong static:      /data/watchalong/**
Daily Digest static:    /data/daily-digest/**
General VOD subtitles:  dedicated VOD subtitle static worker
Alias static:           /data/search/aliases/v1/**
```

Do not publish foreign-owner paths from frontend release tooling.

Do not restart or mutate Collector / Publisher / 8501 unless separately and explicitly authorized.

## 5. Frontend Owner-local release discipline

Use this flow:

1. read the current durable handoff;
2. inspect exact PR/head SHA and changed-file scope;
3. preserve a dirty Owner checkout; use a detached clean worktree;
4. merge only when authorized;
5. fetch exact merged main SHA;
6. run the owner-local frontend release tooling in PREPARE_ONLY first;
7. capture current active frontend Worker version;
8. require exact site diff + ownership gates;
9. execute only from Owner machine with expected active version lock;
10. verify actual Wrangler upload list, new Worker version, dual-origin readback, dedicated-target health, rollback target;
11. record Production evidence on GitHub.

Never silently stash/reset Owner changes.

## 6. Current public repository authority

Runtime/code main immediately before this documentation handoff:

```text
HoloViewer main = 331905243af0d69c13fe5776b1b905335d151236
```

That SHA is PR #343 merge and contains the final #334 post-deploy reconciliation fix.

The handoff documentation merge itself may advance GitHub main without changing runtime code. Always re-read main before new work.

## 7. Recent frontend RWD work completed

### Home PTT rail overlap — PR #337

- candidate: `37739a1c1b6942954e5bd66084569040ae5140b2`
- merged main: `fae3c3ab6ac97716d679a118b0f5a5c7a3219114`
- scope: `site/assets/app.css` + focused regression test
- live-channel rail moved below the completed sidebar navigation so it no longer covers the PTT link.

### Daily Digest iPad/tablet sidebar containment — PR #338

- candidate: `acc67a9ddd13545fdaebeab3602f51d1a1be7cbc`
- merged main: `1a35287fd7e682b7542a79774cee1d2f16145afd`
- scope: `site/assets/daily-digest.css` + focused regression test
- Daily Digest now reserves sidebar width for 761px+ and follows expanded rail state.
- tablet title containment added for 761–980px.

### Combined Owner-local frontend Production release

Accepted Production release:

```text
SOURCE_RELEASE_SHA=1a35287fd7e682b7542a79774cee1d2f16145afd
ACCEPTED_PRODUCTION_SOURCE=0c055467c4be27e2a5735f79be5ceede7c256b87
FRONTEND_VERSION_BEFORE=a5ec88f8-2292-4621-99bd-b19e56230fc9
FRONTEND_VERSION_AFTER=41a2b3f9-6717-4d3e-877f-c3b811e36e3e
PUBLIC_FRONTEND_RELEASE=PASS
DUAL_ORIGIN_READBACK=PASS
```

Only `/assets/daily-digest.css` was newly uploaded in that release; #337 app.css content was already present in the baseline and its contract was reverified.

Contracts accepted:

```text
HOME_PTT_RAIL_FIX=PASS
DAILY_TABLET_COLLAPSED_RAIL=PASS
DAILY_TABLET_EXPANDED_RAIL=PASS
DAILY_TABLET_BREAKPOINT=PASS
PUBLIC_HTTP=PASS
```

Frontend Production evidence is on PR #338.

## 8. Daily Digest related clips — Issue #334 COMPLETE

Issue #334 is closed.

Purpose:

- Daily Digest remains immutable authority.
- Related clips are a separate sidecar.
- Holodex is queried by exact source VOD.
- frontend never calls Holodex directly.
- Holodex failure must not fail Daily Digest.
- sidecars belong to dedicated Daily Digest static, not frontend static.

Important implementation lineage:

- PR #335: initial runtime integration
- PR #336: bounded live pilot gate
- PR #339: direct worker entrypoint import fix
- PR #340: move related-clips work directory outside static tree
- PR #341: discover nested accepted receipts
- PR #342: 30-minute polling + batched publication
- PR #343: post-deploy reconciliation after transient readback mismatch

Final runtime/code SHA:

```text
PUBLIC_RUNTIME_HEAD=331905243af0d69c13fe5776b1b905335d151236
PRIVATE_EXPORTER_HEAD=e2d8da9f7b38521a22ae0312ff197fb4cc301ee9
```

### Accepted unattended model

Do **not** reintroduce a fixed 12:00 schedule.

Accepted model:

```text
WORKER_MODE=PERSISTENT_TERMINAL
TRIGGER=accepted_receipt_poll
POLL_SECONDS=1800
FIXED_DAILY_TIME=NO
LAUNCHD_USED=NO
BACKFILL_LIMIT=0
```

Behavior:

- worker starts and scans immediately;
- after a cycle finishes it sleeps 1800 seconds, so cycles do not overlap;
- a slow cycle delays the next scan rather than spawning concurrent workers;
- no due jobs => no Holodex provider work;
- multiple due jobs in one cycle generate sidecars first and share one Daily Digest static prepare/deploy;
- each sidecar gets independent live SHA readback/reconciliation;
- manual urgent entrypoint remains `--once --execute --target-day YYYY-MM-DD`;
- explicit target-day bypasses the once-per-day receipt guard; durable stage state remains authoritative.

Refresh stages remain initial / T+1 / T+3 / T+7 based on target day.

### Live pilot / Production evidence

2026-11-02 initial pilot:

- old live clip count: 129
- new clip count: 162
- source-language coverage: 0/35 in the selected transcript corpus; missing source language remained explicit and valid
- pilot sidecar SHA: `750b8c35b0295d559f0b4e13403b3985e25fd80959c33a975a09440f61186224`

Final activation observed a transient Cloudflare post-deploy readback mismatch. The deploy itself succeeded, but the release script returned nonzero before propagation settled.

Confirmed live state afterward:

```text
DAILY_DIGEST_STATIC_VERSION=bf925a9f-b4b0-41da-8841-6342ee0b1c92
2026-11-01_LOCAL_LIVE_SHA=b209c926d859f6a9ec564db3e60d11e21fde3d92110b8a9b34cbad103f1767af
2026-11-02_LOCAL_LIVE_SHA=1bff1c701e5b5104df5379836739a6d5d88e565578ea98cb80d295863a9413c4
LOCAL_LIVE_MATCH=YES
```

PR #343 makes runtime reconcile against live sidecars after a release-command error before deciding to retry, preventing unnecessary Holodex/deploy repetition when Production is already correct.

One-time durable state reconciliation was completed:

```text
2026-11-01 initial RECONCILED=PASS
2026-11-02 t1 RECONCILED=PASS
STATE_RECONCILIATION=PASS
PUBLIC_RUNTIME_PIN=PASS
PRIVATE_RUNTIME_PIN=PASS
WORKER_STARTED=YES
```

The final worker startup reported:

```json
{"mode":"EXECUTE","poll_seconds":1800,"status":"WORKER_STARTED","trigger":"accepted_receipt_poll"}
```

No more broad validation is required for #334 unless there is a real regression.

## 9. API / cadence notes

Do not confuse 30-minute polling frequency with Holodex API frequency.

- the local worker scans every 30 minutes;
- if there is no due job, provider calls are zero;
- in steady state each day can have cohorts for today's initial, yesterday T+1, day-3 T+3, day-7 T+7;
- the runtime batches static publication for all due jobs in one cycle;
- do not invent a public Holodex quota number unless verified from an authoritative source.

The Owner is sensitive to unnecessary provider/API usage. Avoid repeated calls caused only by validation or retry logic.

## 10. Current status / what is complete

Complete:

- frontend Docchi News / Daily Digest initial Production integration;
- mobile Daily News RWD fixes from prior handoff;
- Home PTT rail overlap fix (#337);
- Daily Digest iPad/tablet containment fix (#338);
- combined frontend Owner-local release accepted;
- Daily Digest related-clips architecture and exact-source resolver;
- nested accepted-receipt discovery;
- 30-minute persistent polling;
- multi-job single static deployment per cycle;
- manual target-day trigger;
- transient post-deploy reconciliation;
- final #334 Production activation;
- #334 closed;
- GitHub Actions/CI not used as Production acceptance authority.

## 11. Pending / not yet done

There is no active blocker on #334 or the recently completed frontend RWD line.

Still worth observing, but **do not turn these into new gates automatically**:

1. Observe future unattended 30-minute related-clips cycles during normal operation. Only intervene on a real error/regression.
2. Physical iPad/tablet visual confirmation can still be done if the Owner wants subjective visual verification; technical containment contracts are already accepted.
3. Any future frontend release must re-read the current frontend Worker version and accepted Production source before mutation; do not assume GitHub main equals Production.
4. The persistent Terminal worker must remain running. If the Terminal/process is stopped, restart it from the pinned runtime with the accepted 1800-second polling model.
5. Keep unrelated workstreams separate: Historical PTT recovery, Translation runtime, Collector incidents, PTT analytics/login, etc. Do not mix their mutations into frontend/related-clips work.

## 12. Known local/runtime safety notes

- Owner-local deploy only.
- Preserve dirty normal checkouts.
- Use detached worktrees for release/runtime pinning.
- Historical local frontend checkout has had Owner modification in `site/assets/config.js`; never overwrite/stash/reset without explicit instruction.
- Private repo has also previously had local edits; preserve them.
- Related-clips runtime paths live under `~/.holoviewer/daily-digest-related-clips/`.
- Holodex key is read from macOS Keychain service `holodocchi-holodex-api-key`; never print/expose the key.

## 13. Next-chat startup procedure

In the next frontend chat:

1. Read this file first.
2. Read exact current issue/PR evidence only for the workstream being resumed.
3. Check current GitHub main and, if a Production mutation is contemplated, current live Worker/static version.
4. Treat the assistant role as Frontend Engineer + Production Coordinator.
5. Follow Owner-local deployment and CI/Actions policy above.
6. Keep responses concise and operational.
7. Do not redo already accepted broad test suites merely for reassurance.
8. If a real Production-only failure occurs, diagnose that exact failure and add only the narrowly relevant regression/gate.
