# Watchalong Export Authority Handoff — 2026-10-30

## Read first

Durable sources of truth for the next coordinator/chat:

1. Issue #290 — investigation, evidence, root cause, versioning corrections.
2. Issue #291 — implementation task for Codex.
3. PR #289 — prior Pekora asset packaging/deploy history.

Do not reconstruct this work from chat memory if GitHub is available.

## Current state

Production frontend:
- Worker: `holoviewer-public`
- Production: `https://holodocchi.com`
- current deployed version from the last accepted rollout: `09a0f6d0-dfe0-4fe2-b275-1df97c64aa31`
- rollback target: `5dc895ed-e328-4cdc-9f8a-4b09030bed8b`
- release SHA for PR #289 rollout: `46119575acba0b686e6187959f096885cacdd593`

Known Production defect:
- `x7bMoyNWaEE` Public event exports 3 segments.
- authoritative current 8501 mapping has 4 source URLs.
- 8501 runtime transcript analysis shows 4 confirmed starts.
- do not hotfix by editing one hard-coded constant; #290 confirmed an authority-chain defect.

## Root cause already confirmed

Private 8501 DB `watchalong_source_mappings` durably saves playlist/source mapping but does not durably save confirmed breakpoint timing.

8501 derives confirmed starts at runtime from transcript analysis:
`parse_manual_transcript -> infer_watchalong_cues -> confirmed_episode_start_cues -> archive_starts -> episode_master_starts`.

Public exporter `scripts/export_watchalong_assets.py` currently rebuilds Public sync from hard-coded `SESSIONS[*].sources` and `SESSIONS[*].starts_ms`.

Therefore Public export is not currently a lossless serialization of Owner-approved 8501 state.

## Important version exception

`eFYByyw5AJc` has multiple historical transcript/state versions.

- legacy state had a 7-source mapping;
- later corrected public-caption/repaired version uses accepted 6-source sync;
- do not compare current corrected Public asset directly to the stale 7-source row and call it drift.

Approved sync authority must be transcript/version-aware.

## Next action

Have Codex execute Issue #291.

Required order:
1. read #290 completely;
2. produce six-event parity evidence;
3. implement durable version-aware approved-sync authority;
4. make exporter validation + serialization only;
5. return exact branch/head SHA, tests, BEFORE/AFTER event payload evidence;
6. stop for coordinator review.

No Production deploy from Codex.

## Fixed boundaries

```
OWNER_LOCAL_DEPLOY=YES
GITHUB_ACTIONS_DEPLOY=NO
CI_DEPLOY=NO
PRODUCTION_HOTFIX=HOLD
8501_RUNTIME_RESTART=NO
COLLECTOR=NO_CHANGE
PUBLISHER=NO_CHANGE
D1=NO_CHANGE
API_WORKER=NO_CHANGE
PTT_STATIC_ASSETS=NO_CHANGE
```

Coordinator should independently review Codex evidence before merge or Owner-local rollout.
