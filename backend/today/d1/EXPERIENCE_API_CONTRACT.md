# Public Experience API contract — Collab + Watchalong

This backend-only contract preserves accepted 4174 product semantics while removing local/private runtime dependencies.

## Collab

Routes:
- `GET /v1/collab/live`
- `GET /v1/collab/history?day=YYYY-MM-DD&limit=50&offset=0`
- `GET /v1/collab/events/:event_id[?day=YYYY-MM-DD]`

Rules preserved from accepted 4174:
- groups remain **candidates**, never proof of a real-world collab;
- explicit Hololive ARK groups use the existing title/source evidence and 06:00 Asia/Taipei event-day rollover;
- generic shared-topic groups require distinct channels, start times within 20 minutes, and shared non-stopword title/source tokens;
- automatic historical clock sync is exposed only when every POV is `ended` and has verified YouTube `actual_start` + `actual_end`;
- `sync_offset_ms` is relative to the first/earliest accepted candidate POV;
- manual Custom View selections are not silently reclassified as collabs.

Data sources:
- current candidates: existing `public_today_canonical` read projection;
- historical candidates: existing `public_history`; no new Collab table is required.

## Watchalong

Routes:
- `GET /v1/watchalong/recent?days=30&limit=60`
- `GET /v1/watchalong/history?day=YYYY-MM-DD&limit=60&offset=0`
- `GET /v1/watchalong/events/:event_id`

Feature gate:
- all Watchalong data routes require `WATCHALONG_EVENTS_ENABLED=true`;
- keep the flag off until the additive schema is applied and event rows are read back.

Public derived data only:
- event id, date/time, description, members-only marker;
- PTT provenance metadata (AID/title/source URL/article time);
- host labels and YouTube video IDs.

Explicitly NOT published or required:
- PTT article body;
- transcript or A/B translation data;
- playback telemetry;
- local Watchalong archive/session records;
- local/private source mappings;
- inferred watched-source association.

Therefore `source_mapping` is currently `null`, with capabilities explicitly false. The 4174 manual Watchalong builder remains usable independently.

## Additive Watchalong data model

Migration proposal:
`backend/today/d1/experience-read.PROPOSED.sql`

Tables:
- `public_watchalong_events`
- `public_watchalong_streams`

They are independent of Today/PTT publisher tables and never require replaying prior migrations.

Initial/backfill export:
`backend/today/d1/export-watchalong-events.py`

The exporter reads the existing complete PTT Web DB through the accepted
`watchalong_ptt_catalog.load_recent_events()` parser. It emits only the derived minimal event rows.
Same host-video sets dedupe to one stable `watch:<sha256[:20]>` event id; stale imports cannot replace newer article provenance.

## Rollout boundary

Source/API changes alone do not authorize Cloudflare mutation.

Integration order:
1. review/merge API source;
2. apply only the additive Watchalong schema;
3. generate/review/import derived Watchalong SQL from the owner Mac;
4. read back event/stream counts and spot-check provenance/video IDs;
5. set `WATCHALONG_EVENTS_ENABLED=true`;
6. deploy existing `holoviewer-public-api` with these routes;
7. verify HTTP/CORS contract;
8. only then switch the 8788/4174 consumer binding to the new Collab/Watchalong API adapters.

Rollback:
- disable `WATCHALONG_EVENTS_ENABLED` and/or revert the API Worker;
- leave additive derived tables intact for diagnosis;
- do not alter Today canonical, History, PTT publisher data, or accepted frontend UI.
