# Canonical Channel / Member Profile Authority

Status: source-only review. No production migration/deploy authorized.

## Goal

Every public surface that renders channel/member identity uses `channel_id` as
the only identity key and obtains display metadata through one canonical profile
projection.

Canonical schema:

`holoviewer-channel-profile-v1`

Fields:

- `channel_id`
- `channel_name`
- `display_name`
- `avatar_url`
- `group`
- `member_accent`
- `member_accent_dual`
- `support_mode`
- `support_color_source`
- `profile_revision`
- `updated_at`

Unknown fields remain null. Unknown support color remains
`support_mode=neutral`. No title/label/name heuristic may manufacture member
identity.

## Authority storage

Additive migration:

`ptt_offline/worker_host/today/0005_channel_profiles.sql`

Table:

`public_channel_profiles`

Primary key:

`channel_id`

The table is not Today-specific. Today, History, metadata, Collab and Watchalong
all consume the same projection.

## Shared projection

`channel-profile.mjs` owns:
- profile normalization;
- avatar URL allowlist validation;
- dual/solid/neutral support-color normalization;
- batch reads;
- neutral/null fallback;
- transitional consumption of the already-reviewed pinned support-color export.

Endpoint modules must not independently derive avatars or support colors.

A controlled server-side writer seam exists in:
`channel-profile-write.mjs`

It is not exposed as a public route.

## Direct API

`GET /v1/channels/:channel_id/profile`

returns:

```json
{
  "schema_version": "holoviewer-channel-profile-v1",
  "profile": {
    "channel_id": "UC...",
    "channel_name": null,
    "display_name": null,
    "avatar_url": null,
    "group": null,
    "member_accent": null,
    "member_accent_dual": null,
    "support_mode": "neutral",
    "support_color_source": null,
    "profile_revision": null,
    "updated_at": null
  }
}
```

A valid but unknown channel still returns a neutral/null profile keyed by its
stable channel_id.

## Endpoint projection matrix

The shared profile is additive to:

- `/v1/catalog/today`
- `/v1/history`
- `/v1/videos/:video_id/metadata`
- `/v1/collab/live`
- `/v1/collab/history`
- `/v1/collab/events/:event_id`
- `/v1/watchalong/recent`
- `/v1/watchalong/history`
- `/v1/watchalong/events/:event_id`

Video rows keep top-level compatibility fields and also carry nested
`channel`.

Collab `streams[]` therefore carry:
- stable `channel_id`;
- nested `channel` profile.

Watchalong `hosts[]` carry:
- `label` only as presentation/source text;
- `video_id`;
- `channel_id` resolved from stable video identity;
- nested `channel` profile.

Watchalong resolution order is:
1. Today canonical video identity;
2. History video identity;
3. legacy catalog video identity;
4. metadata cache video identity.

It never reads `label` or title to infer channel/member identity.

## Migration / population policy

Migration creates the authority table only. A reviewed server-owned producer
must populate rows from authoritative channel/member sources.

The current pinned support-color export is consumed centrally during transition
so endpoint-specific color parsers can be removed without losing existing
reviewed color behavior.

Avatar/name/group/profile revisions must ultimately be persisted by the canonical
profile producer. Missing values remain null rather than being inferred from
titles.

## Frontend transition

Do not remove frontend fallbacks until:
1. migration is applied;
2. canonical profiles are populated/read back;
3. every listed endpoint proves profile projection;
4. browser smoke confirms Today/History/Collab/Watchalong/Viewer;
5. then remove name-based color fallback and Today-as-History-profile fallback in
   a separate frontend change.

This prevents a backend rollout gap from causing a simultaneous UI regression.

## Release boundary

This PR does not authorize:
- D1 migration;
- profile backfill;
- Worker deploy;
- frontend deploy;
- schedule changes;
- production writes.

Deployment must be migration-first and include endpoint readback across all listed
surfaces.
