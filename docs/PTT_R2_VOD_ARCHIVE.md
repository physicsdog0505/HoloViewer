# PTT R2 VOD Archive Contract (pilot)

## Scope

Backend-owned archive for historical PTT pushes used while watching ended VODs.
This is separate from the live D1 Publisher.

Pilot coverage target: Taipei day 2026-10-01 through the selected export day.

## Time authority

The archive stores absolute push time only.

- Source precision: PTT display minute.
- Canonical wire time: UTC ISO-8601 with seconds fixed to `:00`.
- No synthetic seconds.
- No per-video offset.
- No VOD-specific copy of PTT data.

4174 already selects archived PTT with a video's verified `actual_start` /
`actual_end`. The browser mapping is therefore:

`vod_minute = floor((push.occurred_at - video.actual_start) / 60 seconds)`

Rows outside `[actual_start, actual_end]` are ignored.

## Object layout

Hourly UTC objects:

`ptt/v1/chunks/YYYY/MM/DD/HH00.json.gz`

Example:

`ptt/v1/chunks/2026/10/17/0800.json.gz`

Each object is JSON encoded and gzip compressed:

```json
{
  "schema_version": "ptt-r2-archive-v1",
  "precision": "minute",
  "bucket_start": "2026-10-17T08:00:00Z",
  "bucket_end": "2026-10-17T09:00:00Z",
  "pushes": [
    {
      "occurred_at": "2026-10-17T08:14:00Z",
      "minute_epoch": 29867054,
      "aid": "canonical-aid",
      "source_line": 1234,
      "source_page": 12,
      "kind": "push",
      "author": "user",
      "content": "message",
      "source_url": "https://www.ptt.cc/bbs/C_Chat/M....html",
      "source_record_key": "canonical-aid:1234"
    }
  ]
}
```

## Manifest

The exporter creates a range manifest under:

`ptt/v1/manifests/FROM_THROUGH.json`

It declares:

- schema version
- source precision
- chunk size
- Taipei coverage days
- total pushes
- all object keys
- object push counts
- uncompressed SHA-256 digest
- gzip byte size

The uploader sends all chunks first and the manifest last.

## Browser fetch algorithm

Given `actual_start` and `actual_end`:

1. Convert both timestamps to UTC.
2. Floor start to UTC hour.
3. Fetch each hourly object intersecting the interval.
4. Browser automatically decodes gzip when served with `Content-Encoding: gzip`.
5. Filter rows to the exact VOD interval.
6. Compute `vod_minute` from `occurred_at - actual_start`.
7. Render/filter/sort entirely in the browser.

No D1 query is needed for historical VOD playback.

## R2 serving

Pilot:
- existing/new bucket: `holoviewer-ptt-archive`
- public read only
- GET CORS
- `r2.dev` may be used only for acceptance testing

Production:
- connect a Cloudflare custom domain
- keep hourly objects immutable
- restrict CORS origin to the Public frontend origin

## Mutation rules

- Export reads Collector SQLite in read-only mode.
- R2 chunks are deterministic by absolute hour.
- Historical finalized chunks are immutable.
- Current incomplete hour may be regenerated until finalized.
- Live D1 Publisher state, Worker secrets, D1 schema and frontend are not modified.
