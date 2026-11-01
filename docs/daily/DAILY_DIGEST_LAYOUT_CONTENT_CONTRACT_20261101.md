# Daily Digest Layout + Content Contract — Owner Review 2026-11-01

Status: **development contract / not production authority yet**

This document captures the Owner-reviewed relationship between Daily Digest content generation and frontend layout fitting.

## 1. Core rule

The frontend must preserve artifact order and must not re-rank editorial importance.

Layout fitting may use declared producer fields. During the development Layout Lab only, deterministic title-length fitting is allowed so the Owner can compare templates against the same artifact.

Production target:

```
Gemini / producer decides editorial structure
→ artifact declares layout intent + bounded copy
→ frontend renders deterministically
```

Do not make the production browser infer editorial importance from viewer count, title wording, or time.

## 2. "今天發生什麼" content shape

The producer should generate a bounded overview intended for a visual editorial surface.

### Overview intro

Target:
- **3–4 semantic paragraphs / beats**
- each beat should cover one distinct major axis of the day
- total recommended length: **260–520 CJK characters**
- avoid one giant paragraph containing every event
- paragraph 1 should establish the day's overall center of gravity
- paragraphs 2–3 should cover the next major cross-channel / project clusters
- paragraph 4 is optional for notable independent events that do not fit the top clusters

The frontend may visually clamp this for compact surfaces, but the durable artifact should keep the complete public-facing copy.

### Highlight cards

Recommended count: **3–5**.

Each highlight should provide:
- `title` / preferably `short_title`
- short public summary
- related `video_ids`
- optional `layout_template`

Recommended copy bounds:
- `short_title`: **12–32 CJK characters**
- acceptable hard range: **8–42 CJK characters**
- highlight summary: **45–110 CJK characters**
- avoid punctuation-heavy title chains that attempt to encode the entire story in the title

If a meaningful title cannot fit within ~42 CJK characters, the producer should either:
1. emit a shorter `short_title`, or
2. mark the card for a larger template.

## 3. Supported overview templates

Development Layout Lab currently demonstrates:

- `compact` — two-column small cards; best for short titles
- `adaptive` — mixed grid; long-title cards expand to full width
- `rail` — large Home-style horizontal scroll cards
- `lead` — first card is large editorial lead; remaining cards stay compact

Preferred future artifact field:

```json
{
  "overview_layout": "adaptive",
  "highlights": [
    {
      "short_title": "...",
      "summary": "...",
      "layout_template": "compact"
    }
  ]
}
```

The exact artifact migration should be coordinated with the producer schema authority before production.

## 4. Fit guidance

Suggested producer-side fit intent:

- short title <= 32 CJK + short summary → `compact`
- title 33–42 CJK or denser summary → `wide` / full-row card
- very important first story with strong thumbnail → `lead`
- several medium/long titles in one day → `rail`
- mixed title lengths → `adaptive`

These are layout-fit rules, not editorial ranking rules.

## 5. Thumbnail contract

Related video IDs should be ordered by editorial suitability.

Frontend thumbnail resolution preference:

```
maxresdefault
→ sddefault
→ hqdefault
→ mqdefault
```

All overview/story visual cards should preserve 16:9 media where possible.

## 6. Development-only Layout Lab

Enable with:

```
/daily/?date=YYYY-MM-DD&layoutlab=1
```

Tabs:
- Auto Fit
- Compact Grid
- Wide Rail
- Lead + Grid

The lab must never appear without `layoutlab=1`.

## 7. Production gate

Before production:
- producer prompt/schema authority identified
- content bounds enforced or validated producer-side
- layout field names finalized
- browser fallback remains deterministic
- no client-side Gemini call
- no browser editorial scoring/re-ranking
- Owner reviews desktop + mobile examples for short, medium and long-title days
