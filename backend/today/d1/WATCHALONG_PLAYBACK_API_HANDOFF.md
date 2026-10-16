# #47 → #45 Public Watchalong Playback Package API handoff (source contract)

Status: **proposed interface; not implemented, merged, or deployed**.
Owner priority: wire up complete Public Watchalong user flow first; the C7/4174-processed data may be imported later.
Ownership: #47 supplies source format, export/validator and acceptance; #45 implements API/D1/import and production integration; #68 connects frontend. Do not modify Public frontend or Cloudflare under #47.

## Verified current implementation gap
`backend/today/d1/experience-read.mjs` already exposes:
- `GET /v1/watchalong/recent?days=30&limit=60`
- `GET /v1/watchalong/history?day=YYYY-MM-DD&limit=60&offset=0`
- `GET /v1/watchalong/events/:event_id`

Every returned Watchalong event currently has `source_mapping:null` and `capabilities:{source_mapping:false,translation:false,telemetry:false}`. No API exists for approved C7 Playlist-to-Watchalong alignment, episodes, translations, or package version. `public_watchalong_events` and `public_watchalong_streams` contain only catalog data. This is a genuine P0 end-to-end playback wiring gap, **not** missing source records.

## Proposed read interface for #45 approval

`GET /v1/watchalong/events/:event_id/playback`

Existing event id stays the canonical referent. The route must never trigger transcript retrieval, Gemini/AI jobs, scraping, playlist resolution, or write operations. Return a stable envelope even if no package exists:

```json
{
  "schema_version":"public-watchalong-playback-v1",
  "event_id":"watch:example",
  "status":"unavailable",
  "package":null,
  "capabilities":{"synchronized_playlist":false,"translation":false},
  "reason":"not_published"
}
```

Use **HTTP 200** only for known catalog events with no published package, so frontend can show a normal basic YouTube host player. Use **404** for unknown event id; **503** only for actual backend errors or disabled event service. Distinguish missing data from server failure. CORS/cache policy should match existing read API. If published, `status:"ready"` and immutable/versioned `package` with fields:

```json
{
  "package_id":"sha256-derived immutable identifier",
  "revision":1,
  "published_at":"2026-10-16T00:00:00Z",
  "watchalong_video_id":"AAAAAAAAAAA",
  "playlist":{"playlist_id":"PL...","start_index":0,"count":2,
    "items":[{"index":0,"video_id":"BBBBBBBBBBB"},{"index":1,"video_id":"CCCCCCCCCCC"}]},
  "alignment":{"timebase":"media_ms","segments":[
    {"watchalong_start_ms":10000,"watchalong_end_ms":70000,
     "item_index":0,"source_start_ms":0,"source_end_ms":60000},
    {"watchalong_start_ms":70000,"watchalong_end_ms":130000,
     "item_index":1,"source_start_ms":0,"source_end_ms":60000}
  ]},
  "subtitles":{"status":"ready","language":"zh-TW",
    "cues":[{"start_ms":10000,"end_ms":15000,"text":"公開授權的校對譯文"}]},
  "review":{"approved":true,"rights_cleared":true}
}
```

The example is a **shape**, not real/source-derived data. A package can have `subtitles.status:"unavailable"`, `cues:[]` and capabilities.translation=false while synchronized playback is ready. Likewise when no alignment exists, standard host video remains playable. A translation-only package MUST NOT imply synchronized playlist capability.

## Data validation / import preflight
1. C7/4174 source authority must be examined; NEVER infer alignment points from YouTube IDs alone.
2. Source playlist video IDs and Watchalong host video ID must satisfy `^[A-Za-z0-9_-]{11}$`; playlist id must be a validated YouTube playlist identifier; start index nonnegative, count bounded, items distinct by position, contiguous indexes and length=count.
3. Segments ordered, non-overlapping in host time; `watchalong_start_ms < watchalong_end_ms`, `source_start_ms < source_end_ms`; references to existing item indexes only; no fabricated timestamp, discontinuity must remain explicit rather than auto-filled.
4. Caption cues non-overlapping within each track, valid start/end and language; publish approved, rights-cleared content only. Do not expose raw transcript, A/B drafts, source prompts, AI keys, telemetry, or private source mappings.
5. Only owner-approved packages become public; import idempotent with immutable package_id and monotonic revision, atomically switches published pointer after readback. Editing an existing package without revision is rejected.
6. Never attempt to bypass YouTube access restrictions, age/member/private video gates, visible-player/embedded playback rules. A vanished video is a graceful unavailable state, not fabricated footage.
7. Outbound public data is minimal: video IDs + approved timing + approved translation, not the original internal C7 schema.

## Minimum #45 integration acceptance (even with zero packages)
- Existing recent/history/detail routes still work; every known event can be opened.
- Playback route resolves existing event and yields 200 `status=unavailable`, `package=null` when unpublished, without D1 schema/runtime errors.
- Invalid event id -> 400; unknown id -> 404.
- No package causes **zero** translation/AI/scraping/network side jobs and no D1 writes.
- A fixture package exercises ready status, multi-video episode boundaries, alignment and subtitle capabilities in **offline tests only**, while absent captions remain supported.
- Fallback host playback does not depend on package publication.
- #45 must obtain authorized D1 migration and release approval before production; #68 can bind stable route independently once accepted.
- Do not replace the existing catalog source exporter or remove current `capabilities` until consumer cutover is approved.

## Additional nonblocking upstream work
#47 later investigates exactly where C7/4174 persists source playlist selection, transcript-derived alignment and human-reviewed translations, then builds a verified local read-only export. The 177-events / 190-streams catalog candidate is separate and must pass hash/privacy check. #45 owns schema/endpoint/import; source data may arrive in subsequent release.
