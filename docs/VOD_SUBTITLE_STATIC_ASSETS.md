# General VOD subtitle Static Assets

General Viewer subtitles are an independent publication surface. The #298
publisher keeps publication evidence private and builds one complete public
candidate before any future Owner-approved deployment:

```text
accepted TranslationArtifact
→ validated /data/subtitles/videos/<video_id>.json
→ immutable private publish receipt
→ derive VOD month from the existing YouTube VOD catalog
→ rebuild complete public candidate
   /data/subtitles/videos/<video_id>.json
   /data/subtitles/index.json
   /data/subtitles/manifests/by-vod-month/<YYYY-MM>.json
→ validate candidate against receipts + existing VOD catalog
→ holoviewer-vod-subtitles-static-assets
```

This is not Watchalong. Nothing in this route writes
`watchalong-static/data/watchalong/**`, changes Watchalong event semantics, or
deploys `holoviewer-watchalong-static-assets`. Live and PTT are also outside
this pipeline.

## Authority and receipts

The per-video subtitle payload remains the public subtitle authority. Existing
YouTube/VOD Static Assets remain the only authority for VOD month and metadata.
The publisher never copies title, member/channel, or thumbnail into subtitle
availability indexes.

Private immutable receipts bind:

```text
video_id
asset_path
asset_sha256
translation_artifact_id
source_transcript_id
source_content_hash
staged_at
```

Receipts are durable validation evidence only and MUST remain outside
`vod-subtitles-static/**`. They are the rebuild authority together with the
existing VOD catalog. No second mutable subtitle registry is required.

## Public index contract

Global availability:

```text
/data/subtitles/index.json
```

Shape:

```json
{"schema_version":1,"video_count":1,"videos":[{"video_id":"VIDEO_ID","staged_at":"..."}]}
```

By-VOD-month availability:

```text
/data/subtitles/manifests/by-vod-month/<YYYY-MM>.json
```

The month is the video's own month in the existing VOD catalog, not translation
execution/publication time. The old pre-Production
`/data/subtitles/manifests/<YYYY-MM>.json` contract is rejected.

## Local staging flow

The private exporter first places a validated General VOD asset in a staging
asset root. Create one immutable receipt:

```sh
python3 -B vod_subtitle_publisher.py receipt \
  --asset-root /absolute/staging-root \
  --receipts-root /absolute/private-receipts \
  --video-id VIDEO_ID \
  --staged-at 2026-10-31T01:00:00Z
```

Then rebuild the complete candidate from all private receipts:

```sh
python3 -B vod_subtitle_publisher.py build \
  --asset-root /absolute/staging-root \
  --receipts-root /absolute/private-receipts \
  --catalog-root /absolute/youtube-static-root \
  --candidate-root /absolute/HoloViewer/vod-subtitles-static
```

Validation is deterministic and read-only:

```sh
python3 -B vod_subtitle_publisher.py validate \
  --receipts-root /absolute/private-receipts \
  --catalog-root /absolute/youtube-static-root \
  --candidate-root /absolute/HoloViewer/vod-subtitles-static
```

Identical rebuilds produce the same candidate tree hash. Missing/invalid
receipts, asset hash mismatch, missing VOD catalog membership, public receipt
exposure, extra assets, or the retired month path fail closed before any
Production action.

`scripts/deploy_vod_subtitle_static_assets_owner_local.sh prepare` is the
separate release gate. `deploy` remains an explicit Owner-approved future
action. #298 does not run it.

Future Watchalong integration may consume the same per-video subtitle authority,
but that requires a separate reviewed change.
