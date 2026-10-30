# General VOD subtitle Static Assets

General Viewer subtitles are an independent publication surface:

```text
validated Translation Workspace attempt
→ immutable Transcript Corpus TranslationArtifact
→ vod-subtitles-static/data/subtitles/videos/<video_id>.json
→ vod-subtitles-static/data/subtitles/manifests/<YYYY-MM>.json
→ holoviewer-vod-subtitles-static-assets
→ General Viewer Holodocchi subtitle source
```

This is not Watchalong. Nothing in this route writes
`watchalong-static/data/watchalong/**`, changes Watchalong event semantics, or
deploys `holoviewer-watchalong-static-assets`.

The private offline exporter supplies canonical assets. A video asset binds the
YouTube ID, exact source transcript ID/content hash, exact Corpus translation
artifact ID/identity, segment count, ordered millisecond timestamps and zh-TW
cues. Month manifests bind each video path and SHA-256, carry an explicit
`complete` flag, and preserve prior months. An incomplete month may accumulate
accepted videos without requiring a deployment after every item.

The Viewer resolves a General VOD asset directly by canonical video ID only after
the stream is known to be an ended/archive VOD. A missing asset or unavailable
subtitle origin leaves the existing no-subtitle behavior unchanged. Live, PTT,
and Watchalong flows do not use this reader.

Future Watchalong integration point: its reader may eventually consume the same
per-video subtitle authority, but that requires a separate reviewed change. It
must not duplicate translation truth or change event semantics here.

`scripts/deploy_vod_subtitle_static_assets_owner_local.sh prepare` is a read-only
candidate gate. `deploy` remains an explicit Owner-approved action; this change
does not run it.
