# #47 — All hololive production channel roster: source audit (work in progress)

This is a **research ledger**, NOT an enabled production subscription list. The pre-existing 66-channel prototype must be preserved byte-for-byte in the eventual union. Never infer a canonical channel ID from a handle or channel name. A channel may be in the inventory while its live/WebSub subscription remains disabled.

## Verified baseline

- Private canonical reference: `physicsdog0505/Hololive-PTT-Viewer/hololive_channels.prototype.json`, blob SHA `90b6648ca025c66eb30daa3e14afecf04a216a4f`.
- Current private main has **66 IDs and 66 unique IDs**; the 4174 reference at `checkpoint/4174-viewing-accepted-20261013` also has **66 IDs and 66 unique IDs**. Exact set comparison remains to be run and is **NOT certified**.
- Prototype contains **only strings**, no names, affiliation/status, or verification trail. It expressly excludes group/official channels, HOLOSTARS, alumni and retired channels. Therefore it cannot be used as a full-production ownership roster.

## Organization and project channel discovery

The following are confirmed as **officially linked channels/handles**, not yet confirmed canonical UC... IDs for every entry. Resolve with authenticated YouTube `channels.list` or another reliable canonical-ID observation before inclusion in a deployable roster.

| Brand | Name | Official evidence | Channel link | Canonical-ID status |
|---|---|---|---|---|
| hololive JP | hololive main | https://hololive.hololivepro.com/en/about | https://www.youtube.com/@hololive | pending ID verification |
| hololive EN | hololive English | https://hololive.hololivepro.com/en/about | https://www.youtube.com/@hololiveEnglish | pending ID verification |
| hololive ID | hololive Indonesia | https://hololive.hololivepro.com/en/about | https://www.youtube.com/@hololiveIndonesia | pending ID verification |
| DEV_IS | ReGLOSS | https://hololive.hololivepro.com/en/about | https://www.youtube.com/@DEV_IS_ReGLOSS | pending ID verification |
| DEV_IS | FLOW GLOW | https://hololive.hololivepro.com/en/news/20241107-01-108/ | https://www.youtube.com/@DEV_IS_FLOWGLOW | pending ID verification |
| project | ASOBI★MAWARI-TAI! | https://hololive.hololivepro.com/en/about | https://www.youtube.com/@hololive_ASOBIMAWARITAI | pending ID verification |
| HOLOSTARS EN | HOLOSTARS English official | https://holostars.hololivepro.com/en/news/20250801-01-27/ | https://www.youtube.com/@HOLOSTARSenglish | pending ID verification |
| hololive game | hololive Dreams | https://hololivepro.com/news_en/20260723-01-259/ | https://www.youtube.com/@hololivedreams | pending ID verification |

**Additional completeness targets:** HOLOSTARS JP main; all current JP/EN/ID/DEV_IS/HOLOSTARS JP+EN talents and their official linked channels; graduates/retired talents as historical entries; additional group/project/affiliated channels. Official talent-directory pages are required for completeness and individual source evidence. Watch out for project-name changes and multiple channels per project.

## Proposed versioned inventory contract

Each record:
`{ channel_id, display_name, branch, unit, kind, activity_status, official_url, verified_at, verification_method, live_enabled }`

- `channel_id`: canonical UC... (22-character ID including 'UC' prefix, 24 characters total), *required only for verified records*. Pending handle records belong in a separate discovery ledger.
- `kind`: `talent | organization | group | project`.
- `activity_status`: `active | graduated | retired | unknown`, distinct from `live_enabled`.
- `live_enabled`: explicit monitoring policy, **false by default for newly added records**, independently of listing.
- Never hard-code 66 as the roster cap. Dedupe by canonical ID; preserve legacy 66 and deterministic ordering.
- Only verified IDs are eligible for #47 Today ingestion. The owner will separately approve actual WebSub subscriptions, secrets, Cron and D1 writer activation.

## Remaining acceptance checks

1. Machine-compare the exact 66 ID strings and order against frozen 4174 and main and report set deltas (both counts being 66 does not prove equality).
2. Resolve all official handles to canonical channel IDs using YouTube `channels.list`, with verification evidence and date.
3. Enumerate and compare each official talent directory and graduated/historical rosters; ensure HOLOSTARS JP+EN and newer DEV_IS/project releases are not omitted.
4. Produce immutable ready-to-consume roster JSON + validator (legacy inclusion, uniqueness, schema, source proof, no unverified enabled channels) and focused CI.
5. Hand exact HEAD and approved channel-diff to #47. Do not enable cloud polling/subscriptions by merging this research ledger.
