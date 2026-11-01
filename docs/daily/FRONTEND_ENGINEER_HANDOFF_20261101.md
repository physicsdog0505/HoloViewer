# HoloViewer Frontend Engineer Handoff — 2026-11-01

## Purpose

Durable handoff for the **HoloViewer / Holodocchi frontend engineering role** and the current **Daily Digest V1 / producer-v2 transition**.

The next engineer should read this file first and continue from the exact state documented here. Do not reconstruct the project from chat history.

## 1. Repository / current working line

Repository:

```
physicsdog0505/HoloViewer
```

Current Daily Digest review branch:

```
feat/270-daily-layout-v3-owner-review-20261031
```

Current draft PR:

```
#309 — feat(daily): owner-review v3 layout on daily layout lab
```

Owner-tested V1 freeze candidate:

```
e139c4886146f025bbc941f7bff46e282c0f33e9
```

Owner-local test result at that exact HEAD:

```
python3 -m unittest \
  test_public_smoke.py \
  test_public_frontend_release_gate.py

Ran 35 tests in 0.382s
OK
```

PR #309 stays **draft** until separately authorized.

Next-phase issue:

```
#310 — Daily Digest producer v2: align Gemini output with frozen V1 layout and validate multi-day variation
```

## 2. Role: frontend engineer

This role is broader than one issue.

Responsibilities:

- maintain the public HoloViewer / Holodocchi frontend UI and visual contracts;
- implement Owner-reviewed layout changes without unrelated backend/runtime changes;
- keep frontend rendering deterministic and data-driven;
- preserve static-asset worker boundaries;
- run Owner-local release / acceptance gates with exact SHA evidence;
- distinguish local candidate acceptance from Production acceptance;
- protect accepted visual behavior while refactoring CSS / JS;
- maintain responsive desktop / tablet / mobile behavior;
- coordinate frontend schema expectations with producer / normalizer output;
- keep durable GitHub evidence for review, handoff, release, and rollback.

Frontend work must not casually mutate Collector, Publisher, D1, API behavior, translation runtime, or specialized static workers.

## 3. Owner operating preferences

### Deployment

Owner-local deploy only.

Do not use GitHub Actions / CI as the production release mechanism.

A green CI result is **not** Production acceptance.

Production/release decisions must be grounded in:

- exact source SHA;
- exact candidate/live state;
- dedicated target health/readback;
- boundary verification;
- Owner authorization.

### Local ports

```
8501 = main local Streamlit
8502 = collab review
8503 = translation
4174 = old UI parity
8788 = Daily Digest frontend review preview
```

For the current Daily Digest work, use **8788 only**.

Do not restart or touch 8501 / Collector / Publisher unless separately authorized.

### 8501 restart rule

If a future task explicitly authorizes 8501 restart:

- confirm current PID first;
- confirm checkpoint/source SHA first;
- only restart Streamlit 8501;
- do not restart Collector or Publisher;
- Owner approval is required.

## 4. Static asset / worker boundaries

Public frontend worker publishes site assets only.

Dedicated asset ownership:

```
/youtube/v1/**       -> YouTube static worker
/ptt/v1/**           -> PTT static worker
/data/watchalong/**  -> Watchalong static worker
/data/subtitles/**   -> VOD subtitle static worker
```

Frontend work must not republish or take ownership of those paths.

Public domain:

```
https://holodocchi.com
```

Public API authority:

```
https://holoviewer-public-api.singlebagel.workers.dev
```

Do not create a second frontend worker as a shortcut.

## 5. Daily Digest V1 — frozen visual direction

The current V1 visual direction is accepted as the next stable baseline.

This is **not** permission to merge/deploy.

Read:

```
docs/daily/DAILY_DIGEST_LAYOUT_CONTENT_CONTRACT_20261101.md
```

Core production target:

```
Gemini / producer decides editorial structure
-> artifact declares layout intent + bounded copy
-> frontend renders deterministically
```

The browser must not independently infer editorial importance from viewer count, title wording, time, or similar heuristics.

### Overview

Accepted direction:

- bounded editorial overview;
- 3–5 highlight cards;
- one overview template for the whole block;
- production-shape templates:
  - `compact`
  - `rail`
  - `lead`

Development `Auto Fit` is a selector, not a fourth production template.

Layout Lab:

```
/daily/?date=YYYY-MM-DD&layoutlab=1
```

Overview producer target:

- 3–4 semantic beats / paragraphs;
- about 260–520 CJK characters total;
- avoid one giant paragraph;
- first beat establishes the day’s center of gravity.

Highlight target:

- 3–5 items;
- `short_title` target 12–32 CJK;
- hard range 8–42 CJK;
- summary target 45–110 CJK;
- keep supporting `video_ids`.

### Detailed stories

Detailed story cards preserve the full story title.

Do not frontend-ellipsize detailed editorial titles.

Detailed reading surfaces should use available width unless the artifact explicitly says otherwise.

### Story media invariant

For 1–2 stream feature images:

- horizontal 16:9;
- no portrait/tall feature framing;
- preserve the full YouTube thumbnail;
- `object-fit: contain`;
- letterboxing is acceptable;
- layout may vary placement/width, not thumbnail ratio.

### Hero-full

Large hero was reduced from overly dominant full width.

Current desktop hero is centered at 10/12 columns.

Hero caption overlay was removed.

### Announcement cards

Current contract:

```
ANNOUNCEMENT_TITLE=FULL_TEXT
ANNOUNCEMENT_SUMMARY=FULL_TEXT
TITLE_CLAMP=REMOVED
SUMMARY_CLAMP=REMOVED
CARD_HEIGHT=NATURAL
```

### Category section

Accepted behavior:

- list/accordion only;
- no duplicate category chips;
- hidden horizontal scrollbar;
- overlay left/right arrows;
- clicking any stream card toggles the whole category group open/closed;
- category stream cards and story-detail cards share sizing/typography.

### Shared stream-card typography

```
channel / primary = 14px
secondary title   = 13px
detail paragraph  = 14px
topic chips       = 12px
YouTube link      = 13px
```

Desktop rail target: 3 visible cards.

Tablet: 2.

Mobile: 86vw.

The old story-only `Owner review V3.16` typography layer was intentionally retired.

## 6. Exact tested state

Owner-tested exact HEAD:

```
e139c4886146f025bbc941f7bff46e282c0f33e9
```

Owner-local evidence:

```
HEAD=e139c4886146f025bbc941f7bff46e282c0f33e9
...................................
Ran 35 tests in 0.382s
OK
```

This exact-head evidence is recorded on PR #309.

Do not claim a later HEAD is accepted without a new Owner-local test result.

Do not claim visual acceptance based on tests alone.

Manual screenshot/browser review is the real visual gate.

## 7. Artwork experiment — NOT part of V1

A local-only experiment inserted Owner artwork into Daily Digest empty spaces/section breaks.

Result:

- beside announcement cards: visually unbalanced;
- full-height portrait art dominated the editorial hierarchy;
- section-break art still felt visually strange;
- Owner decided not to include artwork in V1.

Rules:

- experiment is local-only;
- do not commit it;
- do not revive it unless Owner explicitly reopens the design question.

If local 8788 still has artwork residue:

```bash
cd /tmp/daily-layout-v3-correct-wt

git restore \
  site/assets/daily-digest.js \
  site/assets/daily-digest.css

rm -rf site/assets/artwork-pilot

git status --short
git rev-parse HEAD
```

Expected baseline HEAD:

```
e139c4886146f025bbc941f7bff46e282c0f33e9
```

## 8. 8788 preview workflow

Preferred clean worktree:

```
/tmp/daily-layout-v3-correct-wt
```

Refresh:

```bash
cd /tmp/daily-layout-v3-correct-wt

git fetch origin feat/270-daily-layout-v3-owner-review-20261031
git checkout --detach origin/feat/270-daily-layout-v3-owner-review-20261031

echo "HEAD=$(git rev-parse HEAD)"
```

Tests:

```bash
python3 -m unittest \
  test_public_smoke.py \
  test_public_frontend_release_gate.py
```

Restart **8788 only**:

```bash
lsof -ti tcp:8788 2>/dev/null | xargs kill 2>/dev/null || true

HOLOVIEWER_PUBLIC_LOCAL_PORT=8788 \
sh scripts/start_public_local.sh
```

Review:

```
http://127.0.0.1:8788/daily/?date=2026-10-25&layoutlab=1
```

## 9. Next phase — Issue #310

The next engineering line is **producer/schema alignment**, not further V1 visual redesign.

Issue:

```
#310
Daily Digest producer v2: align Gemini output with frozen V1 layout and validate multi-day variation
```

Current Google Drive Gemini input sampled:

```
2026-10-25-holodocchi-gemini-input.md
SCHEMA_VERSION=holodocchi.gemini.daily_digest.v1
```

Current Gemini instruction correctly says Gemini does not own authoritative hero/secondary/frontend layout.

Keep that principle.

Current 2026-10-25 public artifact gaps:

- `overview.highlights` is still an array of long strings;
- no explicit validated `overview_layout`;
- overview summary is one oversized paragraph;
- highlight items do not expose structured `short_title + summary + video_ids`;
- story presentation intent is not normalized into a durable public contract.

Target split:

```
Gemini research / synthesis
  -> semantic editorial signals
  -> bounded public copy
  -> non-authoritative presentation hints

Normalizer / producer
  -> validate schema + copy bounds
  -> resolve authoritative public artifact layout fields
  -> preserve order and evidence video_ids

Frontend
  -> deterministic rendering only
  -> no editorial re-ranking
  -> no client-side Gemini
```

Proposed Gemini overview shape:

```json
{
  "overview": {
    "public_summary": "...",
    "presentation_hint": "compact | rail | lead",
    "highlights": [
      {
        "title": "...",
        "short_title": "...",
        "summary": "...",
        "video_ids": ["..."],
        "recommended_role": "lead_candidate | secondary_candidate | normal"
      }
    ]
  }
}
```

Gemini hints stay non-authoritative.

Normalizer v2 should provide:

- authoritative `overview_layout = compact | rail | lead`;
- structured highlight objects;
- deterministic fallback for missing/invalid hints;
- preserved evidence and `video_ids`;
- public-copy bound validation;
- durable source copy preservation;
- idempotent rebuild;
- legacy v1 compatibility.

Frontend V1 from PR #309 is protected. Only minimal reader/schema compatibility changes if necessary.

## 10. Google Drive / Gemini workflow

Owner wants this line executed here first; **do not hand #310 to Codex for design/implementation yet**.

Desired sequence:

```
1. implement producer/schema changes locally
2. run local tests
3. prepare revised Gemini input/template
4. sync revised instructions to Google Drive
5. verify Drive readback
6. run Gemini for selected historical days
7. normalize generated artifacts
8. render all days on the same frontend
9. Owner visually reviews layout variation
10. only after acceptance, hand verified changes to Codex for durable push/cleanup
```

Do not run Gemini before revised Drive input/template exists and readback passes.

Do not silently overwrite historical input files.

Use versioned/new validation inputs.

## 11. Multi-day validation

Goal:

Prove the same deterministic frontend can render **different valid layouts for different daily source shapes**.

Known Drive inputs:

```
2026-10-25-holodocchi-gemini-input.md
2026-10-27-holodocchi-gemini-input.md
```

Recommended set:

- 2026-10-25 — dense day, 53 streams, multiple major clusters;
- 2026-10-27 — structurally different;
- one additional prior day such as 2026-10-24 or 2026-10-26.

For each day record:

- generated Gemini JSON + MD;
- normalized public artifact;
- resolved `overview_layout`;
- story/highlight count;
- title-length distribution;
- desktop visual result;
- proof layout differences come from artifact content/intent, not browser heuristics.

The goal is not to force every day to look different. Variation should occur only when content warrants it.

## 12. Codex handoff rule

Current Owner instruction:

> finish and validate this line ourselves first; only then ask Codex to push / durable-ize the verified implementation.

Therefore:

- do not send #310 to Codex yet;
- do not let Codex redesign the schema;
- do not let Codex reinterpret the frozen V1 layout;
- after Owner acceptance, Codex may package/push the already-verified result.

## 13. GitHub / CI / release boundaries

```
GITHUB_ACTIONS_USED=NO
MERGE=NO
PRODUCTION_DEPLOY=NO
CLIENT_SIDE_GEMINI=NO
COLLECTOR_CHANGED=NO
PUBLISHER_CHANGED=NO
API_CHANGED=NO
D1_CHANGED=NO
PTT_STATIC_CHANGED=NO
YOUTUBE_STATIC_CHANGED=NO
WATCHALONG_STATIC_CHANGED=NO
VOD_SUBTITLE_STATIC_CHANGED=NO
```

If Production release is later authorized, do Owner-local exact-SHA release verification and live readback.

## 14. Visual-engineering rule

Do not add endless CSS override layers to solve regressions.

When cleaning up:

- preserve accepted visual behavior as a protected contract;
- remove stale/dead rules;
- update stale tests instead of reintroducing retired CSS;
- do not blame Owner requirements for implementation complexity;
- do not roll back accepted layouts to make cleanup easier.

Never claim visual acceptance solely from unit tests.

## 15. Immediate next action

Next conversation should:

1. read this handoff;
2. read Issue #310;
3. read `docs/daily/DAILY_DIGEST_LAYOUT_CONTENT_CONTRACT_20261101.md`;
4. verify branch / PR #309 exact state;
5. restore 8788 if artwork pilot residue remains;
6. begin #310 local producer/schema implementation and tests;
7. stop before merge/deploy;
8. later sync revised Gemini instructions to Drive and perform multi-day validation.

Do not redesign V1 unless Owner reports a specific regression.

## 16. Current acceptance summary

```
FRONTEND_ROLE_HANDOFF=COMPLETE
DAILY_V1_LAYOUT_DIRECTION=FROZEN
OWNER_TESTED_HEAD=e139c4886146f025bbc941f7bff46e282c0f33e9
OWNER_TESTS=35/35 PASS
PR_309=DRAFT
ARTWORK_IN_V1=NO
NEXT_ISSUE=310
NEXT_PHASE=GEMINI_PRODUCER_NORMALIZER_ALIGNMENT
MULTI_DAY_VALIDATION=PENDING
DRIVE_SYNC=PENDING
CODEX_HANDOFF=PENDING_AFTER_OWNER_ACCEPTANCE
MERGE=NO
PRODUCTION_DEPLOY=NO
```
