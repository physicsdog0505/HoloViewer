# Public Watchalong three-session asset handoff — 2026-10-20

Issue: [#148](https://github.com/physicsdog0505/HoloViewer/issues/148)

Status: **READY FOR #45 REVIEW / READY FOR PUBLIC DEPLOY** (not deployed)

## Scope and delivery architecture

This change extends the existing Public standalone Watchalong data seam. It does not add a Worker, D1 table, writer, collector, scheduler, or provider call. The browser first reads `/data/watchalong/manifest.json`, verifies the selected event payload with SHA-256, validates identity and cue coverage, and then passes its existing `segments` and `subtitles` shapes to the current player. Unknown events retain the existing read-only API fallback.

Subtitle cues use the Hololive/master clock, matching the accepted 8501 behavior. The player implementation and synchronization controls are otherwise unchanged.

## Inventory and source-to-Public mapping

| Session day | Master | Source episodes | Transcript | Translation | Sync | Public asset |
|---|---|---:|---|---|---|---|
| 2026-10-01 | `eFYByyw5AJc` | 1–6 | PRESENT, 838 cues, `e97ae66a…` | PRESENT, 838/838 initial checkpoint, `62b0a69f…` | REPAIRED | `/data/watchalong/events/eFYByyw5AJc.json` |
| 2026-10-08 | `U2o13h1Oib4` | 7–12 | PRESENT, 1,438 cues, `747b93b5…` | PRESENT, 1,438/1,438 quality-v2, `e99ab40e…` | PRESENT | `/data/watchalong/events/U2o13h1Oib4.json` |
| 2026-10-15 | `8pF4qHcshDc` | 13–18 | PRESENT, 1,461 cues, `c7a36360…` | PRESENT, 1,461/1,461 quality-v2, `5084c85a…` | PRESENT | `/data/watchalong/events/8pF4qHcshDc.json` |

The source mapping is read from `data/watchalong/watchalong_archive.sqlite3` using SQLite immutable read-only mode. Transcript and final translation identities are validated against the pinned TranscriptCorpus metadata. Only relative, sanitized provenance is included in browser assets.

## Verified gap conclusion

The remembered 2026-10-15 gap is **not present** in the authoritative local artifacts. The stream catalog records `8pF4qHcshDc` starting at `2026-10-15T12:00:16+00:00`; its selected public-caption transcript has 1,461 cues and its quality-v2 artifact has 1,461 non-empty translations tied to transcript hash `c7a36360…`.

The actual repair is in the 2026-10-01 source boundary. The stored 8501 mapping contains a seventh source, `Vr0pc63j7jw`, which is also the first source of the 2026-10-08 session. The first master has six cadence-consistent episode starts; a seventh inferred cue occurs only 79 seconds after the preceding cue. The Public package therefore exports the six supported episode starts and does not mix the adjacent session's episode 7 into the first event. No 8501 data was changed.

## Translation stage evidence

- `eFYByyw5AJc`: the resumable initial checkpoint identity recomputes exactly to `62b0a69f…`; all 42 batches cover cue indexes 0–838 without gaps. No QE/post-edit artifact exists, so the manifest labels quality `initial-complete` rather than quality-v2.
- `U2o13h1Oib4`: initial, QE, and selective post-edit completed; final immutable quality-v2 artifact `e99ab40e…` covers 1,438/1,438 cues.
- `8pF4qHcshDc`: existing initial work was reused; QE and selective post-edit completed; final immutable quality-v2 artifact `5084c85a…` covers 1,461/1,461 cues.

No Gemini/OpenAI request was made for this delivery. Missing provider cue count: **0**. Expected provider requests and budget: **0**.

## Manifest SHA-256

The authoritative full values are in `site/data/watchalong/manifest.json`:

- `eFYByyw5AJc.json`: `5caf7da5d8795d95303cf9e31aaad31fb3ef5dd7f3dfe7d4b85eee09c29074fa`
- `U2o13h1Oib4.json`: `874f6a3a722a2af5cd21ba6d1dc4a13147de35470445122291e5dc134c091ba4`
- `8pF4qHcshDc.json`: `f92fc25f2935fbd2cc1291431bea2f84c3e557c046d05492322efdb10efa9d83`

Regenerate or verify against the private source without any provider call:

```sh
python3 scripts/export_watchalong_assets.py --source-root /path/to/Hololive-PTT-Viewer
python3 scripts/export_watchalong_assets.py --source-root /path/to/Hololive-PTT-Viewer --check
```

## Review and deployment boundary

Review must confirm the approved right to publish the three transcript/translation payloads because they contain full browser-facing subtitle text. No API, D1, Worker script, PTT database, 8501 runtime, or 4174 behavior changes are required.

After merge to a reviewed `main` SHA and after the required Cloudflare baseline/rollback check, the existing production-control action is the proposed deployment path:

```sh
gh workflow run deploy-cloudflare-production.yml --repo physicsdog0505/HoloViewer --ref main -f confirm=DEPLOY -f release_sha=<reviewed-40-character-main-sha> -f baseline_confirmed=BASELINE-CHECKED
```

This command is a handoff only. It was not run.
