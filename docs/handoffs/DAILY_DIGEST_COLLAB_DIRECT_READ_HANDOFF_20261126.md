# Daily Digest → Collab direct-read handoff — 2026-11-26

## 0. Current production status

The History subtitle channel-facet release is complete and accepted.

- Accepted Production source: `8a24d4aac503c8b8592cab1b66d0f3e418f026ba`
- Released frontend SHA: `158426519bfd4a7512bf03abe12d9a031f7494dc`
- New active Worker version: `8239a42e-a218-4d34-a307-e90dca4b8191`
- Rollback target: `8ec948a9-09d4-4dd2-8812-7c45dfd50d17`
- Wrangler uploaded exactly one asset: `/assets/app.js`
- Dual-origin readback: PASS
- Production D1 changed: NO
- Production API Worker changed: NO
- GitHub Actions deploy used: NO
- Foreign-owner static assets excluded: YES
- Final receipt: `PUBLIC_FRONTEND_RELEASE=PASS`

PR #391 contains the PREPARE + Production receipt.

Do not reopen or revalidate this release unless there is a new regression.

---

## 1. New task

Build a minimal Daily Digest-backed historical collab experience.

Owner's clarified intent:

> `/collab` should act as another presentation/entry point over Daily Digest data that already exists. It should not create and maintain a second authoritative collab archive/database in v1.

The intended mental model is:

```text
Daily Digest static data
        │
        ├── Daily Digest UI
        │
        └── /collab
              │
              └── derive Digest relationship data into the existing collab-card/viewer shape
```

When Daily Digest data is published or corrected, `/collab` should reflect that same source on the next read. No separate Owner maintenance step should be required.

Existing November Daily Digest days should therefore become available to the collab UI as soon as this feature is deployed, subject to the safe derivation rules below. This is read-time reuse of existing Daily Digest data, not a separate historical backfill product.

---

## 2. Explicit scope

### IN SCOPE

1. Read already-published Daily Digest static data.
2. Derive safe multi-person/multi-POV collab events from Daily Digest evidence.
3. Reuse the existing `collabEventCard()` UI and existing multi-VOD viewer.
4. Add a recent / historical Daily Digest collab area to `/collab`.
5. Make existing November Daily Digest days visible automatically once the frontend feature ships.

### OUT OF SCOPE FOR NOW

Do not modify:

- `/history`
- History progressive discovery
- History channel facets
- History subtitle discovery
- History collab hydration/search
- 8501 review/approval UI
- manual approve/reject/merge/split workflow
- Production Collector
- Production Publisher
- D1
- Production API worker
- existing live collab detector behavior unless strictly necessary for isolation
- multi-VOD viewer sync logic unless a direct bug prevents Digest-derived events from opening

Owner explicitly wants History left alone until the standalone collab experience is mature.

8501 review is intentionally passed for now because Owner does not want an additional maintenance queue.

---

## 3. Existing frontend collab contract

Current public frontend already has the core rendering/viewer path in `site/assets/app.js`.

Important functions:

- `collabEventStreams(event)`
- `collabEventMap(data, historyDay='')`
- `setHomeCollabEvents(data)`
- `openStandaloneCollab(event)`
- `collabEntry(event)`
- `collabEventState(event)`
- `collabEventCard(event)`
- `loadCollabHistory(day)`
- `loadCollab()`

Current route:

- `/collab`

Current live source:

- `/v1/collab/live`

Current historical source:

- `/v1/collab/history?day=YYYY-MM-DD&limit=...`

Current page markup in `site/index.html` has:

- `#collab-live`
- `#collab-upcoming`
- `#collab-ended`
- `#collab-history-picker`
- `#collab-history`

The existing card contract expects roughly:

```json
{
  "event_id": "...",
  "day": "YYYY-MM-DD",
  "label": "...",
  "confidence": "...",
  "streams": [
    {
      "video_id": "...........",
      "channel_id": "...",
      "channel_name": "...",
      "lifecycle_state": "ended",
      "actual_start": "...",
      "actual_end": "..."
    }
  ]
}
```

At least 2 valid stream video IDs are required for `collabEventCard()`.

`openStandaloneCollab(event)` already opens the existing multi-VOD Viewer and uses `event.day` / `_history_day` for `collab_day`.

Do not invent a second card implementation unless unavoidable.

---

## 4. Daily Digest source facts

Current normalizer:

- `scripts/daily_digest_normalizer_v2.py`

Current public Daily Digest contract:

- `kind = holodocchi.daily_digest`
- `schema_version = 1`

Useful evidence fields already preserved:

- `stories[].video_ids`
- `overview.highlights[].video_ids`
- `target_day`
- story/highlight title / short_title / summaries

The v2 normalizer explicitly retains evidence `video_ids`.

Important caution:

`video_ids.length >= 2` is NOT sufficient by itself to call something a collab.

A Daily Digest story may reference multiple related videos without them being the same simultaneous collab.

Therefore v1 derivation must be high precision and may skip ambiguous groups.

---

## 5. v1 derivation rule

Preferred implementation: a small pure frontend adapter, conceptually:

```js
deriveDigestCollabEvents(digest, metadata)
```

The adapter should transform Daily Digest evidence into the existing collab event shape.

Minimum structural gates:

1. source Daily Digest artifact is valid/published
2. candidate grouping has at least 2 distinct valid `video_id`
3. resolved metadata shows at least 2 distinct `channel_id`
4. stream timing is compatible with the same collab/event window
   - overlap is strongest evidence
   - a small start-time tolerance is acceptable when actual windows are incomplete
5. if the structure is ambiguous, SKIP rather than publish a weak card

Do not add another AI classifier in v1.

Do not create an Owner review queue in v1.

The design goal is high precision, lower recall.

---

## 6. Data ownership

For this first implementation, Daily Digest remains the single authority.

Do NOT create a separately maintained canonical collab archive/database for the Digest-derived area.

Do NOT require a second deploy/publisher step after every Daily Digest publish.

Expected behavior:

```text
Daily Digest publish/correction
        ↓
existing static Digest data changes
        ↓
/collab reads current Digest data
        ↓
derived collab presentation changes automatically
```

This differs from the related-clips pipeline, which needs resolver/refresh sidecars.

A later version MAY materialize a collab sidecar/archive if runtime cost, schema stability, search, or historical scale justify it. Do not pre-build that infrastructure now.

---

## 7. /collab UI direction

Keep the existing live sections:

- 現在直播中
- 稍後
- 今天已結束

Add a separate Digest-backed historical/recent section rather than replacing live detection immediately.

Recommended first UI:

```text
多人連動

現在直播中
[event] [event]

稍後
[event]

今天已結束
[event]

────────────

近期連動

11/26
[event] [event]

11/25
[event]

11/24
[event] [event]

載入更早
```

For v1:

- do not add search
- do not add member facets
- do not connect to History
- do not require Owner review
- do not redesign the card
- reuse `collabEventCard()`

The old date picker may remain temporarily during development, but the desired end state is a recent-by-day flow rather than requiring the Owner/user to know a date first.

---

## 8. Historical loading strategy

The feature should leverage already-published Daily Digest month/day data.

On first production deployment, November days that already have Daily Digest data should become available without a separate backfill job.

Preferred frontend behavior:

1. discover current/latest available Digest month/day data using the existing Daily Digest static contract/config
2. load recent available days
3. derive events
4. render grouped by day
5. 載入更早 fetches older published Digest data

Avoid one request per video.

Avoid introducing a new Production API dependency if the existing Digest static data is sufficient.

---

## 9. Event identity / provenance

Even though v1 is read-time derived, event IDs should be deterministic so Viewer URLs/debugging are stable.

Recommended identity inputs:

- Daily Digest `target_day`
- stable story/highlight index or stable normalized video-id set

Example:

`digest-2026-11-25-story-03`

or a deterministic hash over:

`target_day + sorted(video_ids)`

Keep provenance available in-memory on the event object when useful:

```json
{
  "source": {
    "kind": "daily_digest",
    "target_day": "2026-11-25",
    "story_index": 3
  }
}
```

Do not expose internal receipt paths in public UI.

---

## 10. Sync behavior

Do not invent verified VOD sync.

Existing Viewer behavior should remain authoritative.

Digest-derived events may open the multi-VOD Viewer even if `sync.available` is not verified.

Only set verified sync when the existing trusted archive-window / actual-start evidence meets the same current Viewer requirements.

The v1 objective is:

> correct grouping + convenient multi-VOD entry

not:

> create a new synchronization authority

---

## 11. Safety / deployment boundaries

Owner-local deploy only.

No GitHub Actions deployment.

Before any public frontend release:

- exact release SHA must be contained in `origin/main`
- use the repo's formal owner-local release runner
- PREPARE_ONLY first
- capture active Worker version
- execute only after Owner approval
- dual-origin byte readback
- no automatic rollback

Frontend worker owns site assets only.

Do not touch:

- PTT static workers/assets
- YouTube static worker/assets
- Watchalong static worker/assets
- Daily Digest publication authority
- D1
- Production API Worker

---

## 12. Recommended next-window implementation sequence

1. Inspect the exact current Daily Digest static month/day payload shape and config path used by `site/assets/daily-digest.js`.
2. Inspect the existing frontend metadata resolver that can turn `video_id` into channel/timing metadata.
3. Implement a pure derivation function with focused tests:
   - 2+ videos, 2+ channels, overlapping time => event
   - same channel multi-video => skip
   - unrelated/non-overlapping story => skip
   - invalid video IDs => skip
   - deterministic event ID
4. Add Digest-backed recent collab section to `/collab`.
5. Reuse `collabEventCard()` and `openStandaloneCollab()`.
6. Test against existing November Daily Digest data before any deploy.
7. Do not modify History or 8501.
8. Prepare a frontend release only after Owner reviews the local result.

---

## 13. Owner intent summary

Keep this simple.

The Owner does not want another service or another manual maintenance flow right now.

The first milestone is:

> Existing Daily Digest data should be readable as a second presentation of already-known multi-person relationships, directly inside the multi-collab page, and should open the existing multi-VOD viewer.

If this proves useful and stable, later phases may add:

- collab search
- member facets
- History integration
- a materialized archive/index
- 8501 review tools

None of those are part of v1.


---

## 14. Implementation status update — 2026-11-26

Feature branch:

`feat/daily-digest-collab-direct-read-20261126`

Current exact HEAD at handoff update:

`5c2f731520bcdac6753098459e6e7b92761a3716`

Base handoff SHA:

`fc61fe99182efb4fae30bdcae7524cf09b21f47e`

Current branch delta from base:

- `site/assets/app.js`
- `site/assets/daily-digest.js`
- `site/assets/digest-collab.js`
- `site/index.html`
- `test_digest_collab_frontend.py`
- `test_public_smoke.py`

No backend / D1 / Collector / Publisher / 8501 / Watchalong / PTT static / YouTube static files are changed.

### Implemented behavior

- Daily Digest month shards remain the grouping authority.
- `stories[].video_ids` and `overview.highlights[].video_ids` feed a pure `deriveDigestCollabEvents(digest, metadata)` adapter.
- High-precision structural gates:
  - valid published Digest
  - 2+ distinct valid video IDs
  - 2+ distinct channel IDs
  - overlapping complete actual windows, or <=20 minute start tolerance when actual windows are incomplete
  - ambiguous groups are skipped
- deterministic event IDs are based on target day + sorted video IDs.
- derived events do not invent verified sync.
- `/collab` has an independent `近期連動` section grouped by Digest day with `載入更早`.
- existing `collabEventCard()` and `openStandaloneCollab()` are reused.
- historical metadata comes from existing YouTube Static monthly data; current-day fallback may reuse existing `/v1/catalog/today`.
- avatar/profile presentation reuses the same canonical batch profile path as History:
  - frontend `loadCanonicalChannelProfiles()`
  - `GET /v1/channels/profiles?id=...`
  - shared `canonicalChannelProfileCache`
  - max 100 unique IDs per request
  - no per-card or per-video profile fan-out
- Production backend evidence for this existing batch route:
  - one `readChannelProfiles(env.DB, ids, { env })` resolver call
  - 1 ID => 7 prepares
  - 20 IDs => 7 prepares
  - 80 IDs => 7 prepares
  - invalid/empty/>100 => 0 prepares
  - no D1 writes
  - prior Production batch-profile and avatar readback PASS

### Owner/local evidence already completed

At exact earlier feature SHA `74ffd41431ac9e900116fb38238ca08fdf92aef3`:

- JS syntax PASS
- focused Digest collab tests PASS
- public direct-read contract PASS
- original collab structure contract PASS
- foreign static boundary unchanged
- local `8788 /collab` visually confirmed that published November Daily Digest days can directly produce multiplayer cards without a separate backfill or publisher.

The later avatar/profile wiring is presentation-only and was explicitly waived from additional Owner visual acceptance.

### Remaining gate

Do NOT deploy Production from this branch yet.

Before a public frontend release:

1. run exact-current-HEAD local syntax + focused tests;
2. confirm branch boundary still only touches the six files above;
3. merge/land onto `origin/main`;
4. choose exact release SHA contained in `origin/main`;
5. owner-local frontend release runner PREPARE_ONLY;
6. capture current active frontend Worker version;
7. execute only after explicit Owner approval;
8. perform normal dual-origin byte readback.

Do not revalidate the previously accepted frontend release `158426519bfd4a7512bf03abe12d9a031f7494dc`; that release is historical baseline only.
