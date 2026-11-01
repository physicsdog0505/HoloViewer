# Daily Digest Gemini Producer Contract v2

Status: local candidate for Issue #310; not production authority and not deployed.

## Responsibility split

```
Gemini research/synthesis
  -> semantic editorial order
  -> bounded public copy
  -> evidence video_ids
  -> non-authoritative presentation_hint / recommended_role

Normalizer v2
  -> validates copy/evidence
  -> resolves authoritative overview_layout
  -> preserves order and source provenance
  -> produces deterministic public artifact

Frontend
  -> renders artifact order deterministically
  -> does not re-rank by viewers/title/time
  -> does not call Gemini
```

Gemini does **not** own arbitrary CSS, hero placement, browser heuristics, or production template implementation.

## Schema identity

Validation inputs produced under this contract must declare:

```text
SCHEMA_VERSION=holodocchi.gemini.daily_digest.v2
```

Canonical JSON identity is:

```json
{"meta":{"schema_version":"holodocchi.gemini.daily_digest.v2"}}
```

The normalizer also accepts earlier top-level schema markers during migration, but new Gemini v2 output should use `meta.schema_version`.

## Overview

Required shape:

```json
{
  "overview": {
    "public_summary": "...",
    "presentation_hint": "compact | rail | lead",
    "highlights": [
      {
        "title": "完整編輯標題",
        "short_title": "卡片用短標題",
        "summary": "卡片摘要",
        "video_ids": ["..."],
        "recommended_role": "lead_candidate | secondary_candidate | normal"
      }
    ]
  }
}
```

Rules:

- `public_summary`: 3-4 semantic beats; target 260-520 CJK characters total.
- `highlights`: 3-5, in editorial order.
- `short_title`: target 12-32 CJK; hard range 8-42.
- highlight `summary`: target 45-110 CJK.
- every highlight keeps supporting ordered `video_ids`.
- `presentation_hint` is a recommendation. The normalizer writes authoritative `overview_layout`.
- `recommended_role` is semantic evidence, not permission for browser-side ranking.

## Stories

Every story keeps:

- full `title`;
- optional bounded `short_title`;
- `editorial_summary`: the primary detailed-reader copy, synthesized by Gemini from the supporting streams;
- optional compact `public_summary` (or legacy `summary`) as shorter source copy / migration fallback;
- `reader_mode`: `inline | summary_with_details`;
- ordered `video_ids`;
- optional `recurring_program_id`, `program_type`, and `summary_depth` editorial metadata;
- existing `editorial_signals` / source evidence;
- optional non-authoritative `presentation_hint`.

Story copy rules:

- `editorial_summary` should preserve the useful depth already discovered during Gemini research instead of collapsing a multi-stream story into a thin card caption.
- Standard stories target roughly 320-760 CJK characters. Stories marked `summary_depth=deep` may use roughly 500-1200 CJK characters and 3-7 semantic beats when the source genuinely supports that depth. Shorter is acceptable when the event is simple.
- Prefer concrete cross-stream facts, outcomes, announcements and relationships over filler prose.
- Do not duplicate every per-stream summary verbatim; synthesize the story as an editorial unit.
- The normalizer preserves an explicit `editorial_summary` unchanged within the public bound.
- During migration, when `editorial_summary` is absent, the normalizer must preserve and reuse the existing story `public_summary` / legacy `summary` only. It must not synthesize a second prose version from `streams[].summary`; richer story prose must come from Gemini as an explicit `editorial_summary`.
- Use `reader_mode=inline` when the story body can absorb the useful supporting-stream details without losing clarity; the detailed frontend should then omit redundant per-stream detail cards.
- Use `reader_mode=summary_with_details` only when individual supporting streams contain materially distinct details, POVs, chronology, or evidence that remain useful after the story synthesis.
- Do not choose `summary_with_details` merely because a story has multiple `video_ids`; the decision is editorial, not a video-count heuristic.

The detailed frontend must show the full story title and prefer `editorial_summary` for the story body. It must not truncate that body merely to satisfy a visual template. Recurring news / recurring zatsudan / recurring radio stories marked `summary_depth=deep` may carry materially longer editorial copy than standard stories.

Story visual layout is structural, not editorial ranking. The frontend may use stable count-based media grids (for example 1, 2, 3, 4, 5, or 6+ supporting videos), but must not select visual prominence from story index, title length, summary length, viewers, or timing.

## Recurring program deep treatment

Known recurring news / zatsudan / radio series may be tagged by Gemini with:

- `recurring_program_id`
- `program_type`: `regular_news | recurring_zatsudan | recurring_radio | zatsudan | game | music | event | other`
- `summary_depth`: `deep | standard | brief`

For recurring weekly/news-style programs, `deep` means the editorial copy should preserve useful weekly/member updates, work or activity behind-the-scenes, notable member interactions, announcements, dated follow-ups, and the program's recurring information segments. A single-video story must not be made shallow merely because it has one evidence video.

Known aliases currently include `#朝こよ`, `#朝ミオ`, おはスバ / おはすば, `#朝ガオ`, `#ねるまえらじお`, アキちょこナイトパレット, and holoAN / `#昼ホロ` when those streams are present in the authoritative daily universe.

## Birthday / anniversary special-event priority

Birthday lives, anniversary lives, anniversary commemorations, and comparable special 3D lives are high-priority editorial units.

Recommended metadata:
- `program_type=special_event`
- `summary_depth=deep`
- `special_event_type=birthday_live | anniversary_live | special_3d_live | memorial_event | other`
- optional `guests`, `event_merchandise`, `sales_window`, `deadline_text`, `setlist_status`, `setlist`.

These events should normally become standalone stories and should be strongly considered for overview highlights / lead or secondary placement. Their editorial body should preserve performance theme, verified setlist, guests, first reveals, live announcements, merchandise, sales deadlines, ticketing/purchase details, and dated follow-ups when the sources support them.

Do not split one event into several thin overlapping stories for performance / announcement / merchandise. Prefer one complete special-event story plus structured actionable announcements where useful.

## Major announcements and music setlists

Major announcements may carry `summary_depth=deep` when verified source content contains actionable detail. Preserve dates, participants, venue/platform, ticketing/purchase method, versions/benefits, deadlines, and follow-up dates when explicitly stated; do not compress these away for layout.

Music / karaoke / mini-live streams may carry structured setlist metadata when verified:
- `program_type=music`
- `setlist_status=complete | partial | unavailable`
- ordered `setlist[]` entries with `order`, `title`, and optional `artist_or_source`, `performers`, `note`, `timestamp_text`.

Partial verified setlists are preferable to omission. Never guess unknown songs. Structured setlists supplement, not replace, the editorial summary.

## Announcements and categories

Announcements keep full title + full summary. Categories keep stable `key`, human `label`, and ordered `video_ids`. Neither section is destructively truncated by this contract.

## Authoritative public artifact

The normalizer emits the existing public identity for frontend compatibility:

```json
{
  "schema_version": 1,
  "kind": "holodocchi.daily_digest",
  "overview_layout": "compact | rail | lead"
}
```

`overview_layout` is authoritative. For valid v2 `presentation_hint`, the normalizer accepts the requested supported value. Missing/invalid hints use a deterministic producer-side fit fallback based only on bounded highlight title lengths; it never changes editorial order.

The public artifact includes `producer_v2.source_sha256` so identical source input can be proven to rebuild identically. Raw source is **not** embedded into the public artifact; the workflow may write a separate canonical source-copy file beside validation evidence.

## Legacy v1 compatibility

The normalizer accepts the existing v1 artifact shape where `overview.highlights` is an array of strings. It migrates those strings into structured highlight objects, preserving story order and taking evidence `video_ids` from the corresponding story when available.

Legacy compatibility is a migration path, not permission for new Gemini v2 output to omit required structured fields.

## Source authority and local-summary QA

The Gemini Drive input continues the original Issue #477 source model: the Stream List identifies the complete daily universe, and Gemini researches the supplied YouTube URLs directly. Holodocchi local Daily Summary Markdown is not embedded as the primary Gemini source in v2.

The independently generated local Daily Summary remains useful after Gemini generation as QA evidence for coverage, omissions, factual drift, and quality comparison. If a future revision uses local summaries as supplementary evidence, that must be an explicit versioned contract change rather than a silent source substitution.

Gemini JSON is not served directly to the frontend. The normalizer remains the deterministic assembly boundary that validates schema/copy/evidence and resolves authoritative artifact layout fields.

## Drive validation rule

Do not overwrite historical Drive inputs silently. Create versioned v2 validation inputs, verify Drive readback, then run Gemini. No Gemini generation is accepted as v2 evidence unless the input readback shows this contract/schema version.
