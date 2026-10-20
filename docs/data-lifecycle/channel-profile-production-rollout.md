# PR #155 Canonical Channel Profile — Production Rollout Package

Status: REVIEW PACKAGE. No Production mutation is authorized by this document.

## Frozen identity

- Worker: `holoviewer-public-api`
- Worker API: `https://holoviewer-public-api.singlebagel.workers.dev`
- Production D1: `holoviewer-public-v1`
- D1 ID: `64e1a0ee-1455-4377-9640-3922e8f4d061`
- D1 binding: `DB`
- compatibility date: `2026-10-14`
- canonical migration: `ptt_offline/worker_host/today/0005_channel_profiles.sql`
- Production rollout config: `ptt_offline/channel-profile-rollout.wrangler.json`
- local-only importer config: `ptt_offline/channel-profile-import-local.wrangler.json`
- importer: `ptt_offline/worker_host/today/channel-profile-import-local.mjs`
- deterministic exporter: `ptt_offline/export_canonical_channel_profiles.py`
- artifact path: `/tmp/hv47-canonical-channel-profiles-85.json`
- reviewed roster: `today85-20261016-d0e326c0496b`
- expected profile count: **85**
- last known deployed Worker version before this rollout:
  `f95019e8-7c5c-42d6-bef4-0845ff6eccb7`

Execution preflight MUST re-read the current active deployment and abort if an
unreviewed later deployment is active.

The profile artifact is derived READ-ONLY from the already-live approved roster
and verified legacy profile table. It contains no credentials, request headers,
cookies, PTT body, transcript or telemetry.

## A. Migration package

### 1. Preflight READ-ONLY

```bash
cd "$HOME/Downloads/HoloViewer"
git fetch origin issue47/canonical-channel-profile-authority
git switch issue47/canonical-channel-profile-authority
git pull --ff-only origin issue47/canonical-channel-profile-authority
git rev-parse HEAD

npx wrangler deployments list \
  --name holoviewer-public-api \
  --config ptt_offline/channel-profile-rollout.wrangler.json

npx wrangler d1 execute holoviewer-public-v1 \
  --remote \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --command "SELECT name,type,sql FROM sqlite_master WHERE name IN ('public_channel_profiles','public_channel_profiles_group','public_channel_profiles_updated') ORDER BY type,name;"

npx wrangler d1 execute holoviewer-public-v1 \
  --remote \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --command "SELECT 'public_history' AS object_name,COUNT(*) AS n FROM public_history
             UNION ALL SELECT 'public_today_canonical',COUNT(*) FROM public_today_canonical
             UNION ALL SELECT 'public_watchalong_events',COUNT(*) FROM public_watchalong_events
             UNION ALL SELECT 'public_watchalong_streams',COUNT(*) FROM public_watchalong_streams;"
```

Expected before first rollout: canonical table/indexes absent.

**ABORT before mutation** if the Worker/D1 identity differs, an unknown later
Worker deployment is active, or canonical schema already exists with unexpected
shape.

### 2. Exact migration mutation

```bash
npx wrangler d1 execute holoviewer-public-v1 \
  --remote \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --file ptt_offline/worker_host/today/0005_channel_profiles.sql
```

Expected objects:
- `public_channel_profiles`
- `public_channel_profiles_group`
- `public_channel_profiles_updated`

No business rows are inserted by the migration.

**ABORT after any remote ambiguity/failure. Do not blindly retry.**

### 3. Post-migration READ-ONLY

```bash
npx wrangler d1 execute holoviewer-public-v1 \
  --remote \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --command "SELECT name,type,sql FROM sqlite_master WHERE name IN ('public_channel_profiles','public_channel_profiles_group','public_channel_profiles_updated') ORDER BY type,name;
             SELECT COUNT(*) AS profile_rows FROM public_channel_profiles;"
```

Expected `profile_rows=0`. Repeat the unrelated baseline query; values must be
unchanged.

## B. Canonical population package

### 4. Deterministic input artifact — READ-ONLY

```bash
python3 -B ptt_offline/export_canonical_channel_profiles.py \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --output /tmp/hv47-canonical-channel-profiles-85.json

ARTIFACT=/tmp/hv47-canonical-channel-profiles-85.json
ARTIFACT_SHA="$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')"
test "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["profile_count"])' "$ARTIFACT")" = 85
printf 'ARTIFACT_SHA=%s\n' "$ARTIFACT_SHA"
```

Exporter acceptance:
- roster exactly `today85-20261016-d0e326c0496b`;
- 85 approved unique channel IDs;
- 85 trusted YouTube avatars;
- valid group on every row;
- deterministic canonical JSON;
- no secret/provider key;
- `production_mutation=false`.

The exact SHA printed here is the only approved identity for validate/apply.
Never edit/reformat the artifact afterward.

### Local-only importer execution model

The importer file is not mounted by the Production API router. Run it locally
with D1 `remote:true`; Worker code stays on the owner machine and only the D1
binding is remote.

```bash
npx wrangler dev \
  --ip 127.0.0.1 \
  --port 8791 \
  --config ptt_offline/channel-profile-import-local.wrangler.json \
  > /tmp/hv47-profile-importer.log 2>&1 &
IMPORT_PID=$!
```

### 5. Population dry-run

```bash
curl --fail-with-body -sS \
  -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=validate' \
  | tee /tmp/hv47-profile-dry-run.json
```

Expected:
- `status=VALIDATED`
- `production_mutation=false`
- `profile_count=85`
- `batch_size=25`
- no same-timestamp conflict.

**ABORT before apply on any mismatch.**

### 6. Population execute

```bash
curl --fail-with-body -sS \
  -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=apply' \
  | tee /tmp/hv47-profile-apply.json
```

Expected on an empty canonical table:
- `status=APPLIED`
- `profile_count=85`
- `profiles_written=85`
- four bounded writer batches: 25/25/25/10.

Only `public_channel_profiles` may be mutated, through the already-reviewed
`upsertChannelProfiles()`.

If apply reports ambiguity/partial mutation, stop and inspect D1; do not blindly
retry.

## C. Population validation + replay

```bash
npx wrangler d1 execute holoviewer-public-v1 \
  --remote \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --command "SELECT COUNT(*) AS total_profiles,COUNT(DISTINCT channel_id) AS distinct_channels FROM public_channel_profiles;
             SELECT channel_id,COUNT(*) AS n FROM public_channel_profiles GROUP BY channel_id HAVING COUNT(*)>1;
             SELECT channel_id FROM public_channel_profiles
               WHERE channel_group NOT IN ('hololive','holostars','mekpark','other')
                  OR support_mode NOT IN ('neutral','solid','dual_color')
                  OR profile_revision IS NULL OR profile_revision=''
                  OR updated_at IS NULL
               ORDER BY channel_id LIMIT 20;
             SELECT channel_id,avatar_url FROM public_channel_profiles
               WHERE avatar_url IS NOT NULL
                 AND avatar_url NOT LIKE 'https://yt3.ggpht.com/%'
                 AND avatar_url NOT LIKE 'https://yt3.googleusercontent.com/%'
                 AND avatar_url NOT LIKE 'https://yt3.google.com/%'
               ORDER BY channel_id LIMIT 20;"
```

Acceptance:
- total=85;
- distinct=85;
- duplicates=0;
- invalid enums/revision/time=0;
- invalid avatar hosts=0.

Replay exact bytes:

```bash
curl --fail-with-body -sS \
  -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=apply' \
  | tee /tmp/hv47-profile-replay.json
```

Required: `profiles_written=0`.

Then stop local importer:

```bash
kill "$IMPORT_PID"
wait "$IMPORT_PID" 2>/dev/null || true
```

## D. Worker deploy package

Do not use frontend `cloudflare/wrangler.json`.

The API rollout config uses `keep_vars=true` and existing D1 identity.
Use Workers Versions; do not call `wrangler triggers deploy`, so current
routes/domains/Cron are not changed by this package.

### Record rollback target

```bash
npx wrangler deployments list \
  --name holoviewer-public-api \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  | tee /tmp/hv47-profile-deployments-before.txt
```

Expected previously accepted version:
`f95019e8-7c5c-42d6-bef4-0845ff6eccb7`.

If the active version is newer and not reviewed here, ABORT.

### Upload reviewed version without activating traffic

```bash
npx wrangler versions upload ptt_offline/worker_host/index.mjs \
  --name holoviewer-public-api \
  --config ptt_offline/channel-profile-rollout.wrangler.json \
  --message "PR155 canonical-channel-profile authority $(git rev-parse HEAD)" \
  | tee /tmp/hv47-profile-version-upload.txt
```

Capture `NEW_VERSION_ID`.

### Activate at 100%

```bash
NEW_VERSION_ID='<captured-version-id>'
npx wrangler versions deploy "${NEW_VERSION_ID}@100%" -y \
  --name holoviewer-public-api \
  --config ptt_offline/channel-profile-rollout.wrangler.json
```

### Rollback

```bash
OLD_VERSION_ID='f95019e8-7c5c-42d6-bef4-0845ff6eccb7'
npx wrangler versions deploy "${OLD_VERSION_ID}@100%" -y \
  --name holoviewer-public-api \
  --config ptt_offline/channel-profile-rollout.wrangler.json
```

Never DROP/reseed the additive profile table during Worker rollback.

## E. Production endpoint readback matrix

Fixed real anchors:
- Roboco channel: `UCDqI2jOz0weumE8s7paEk6g`
- real WebSub video: `oTYyghN5fxU`
- recorded channel for that video: `UC727SQYUvx5pDDGQpTICNWg`
- Watchalong/History/Collab calibration day: `2026-10-15`

```bash
API='https://holoviewer-public-api.singlebagel.workers.dev'
ROBOCO='UCDqI2jOz0weumE8s7paEk6g'
VIDEO='oTYyghN5fxU'
DAY='2026-10-15'

curl -fsS "$API/v1/channels/$ROBOCO/profile" | jq .
curl -fsS "$API/v1/catalog/today?limit=200&offset=0" | jq .
curl -fsS "$API/v1/history?day=$DAY&limit=50&offset=0" | jq .
curl -fsS "$API/v1/videos/$VIDEO/metadata" | jq .
curl -fsS "$API/v1/collab/live" | jq .
curl -fsS "$API/v1/collab/history?day=$DAY&limit=100&offset=0" | jq .
curl -fsS "$API/v1/watchalong/recent?days=30&limit=60" | jq .
curl -fsS "$API/v1/watchalong/history?day=$DAY&limit=60&offset=0" | jq .

COLLAB_EVENT_ID="$(curl -fsS "$API/v1/collab/history?day=$DAY&limit=100&offset=0" | jq -r '.events[0].event_id // empty')"
WATCH_EVENT_ID="$(curl -fsS "$API/v1/watchalong/history?day=$DAY&limit=60&offset=0" | jq -r '.events[0].event_id // empty')"
test -z "$COLLAB_EVENT_ID" || curl -fsS "$API/v1/collab/events/$COLLAB_EVENT_ID" | jq .
test -z "$WATCH_EVENT_ID" || curl -fsS "$API/v1/watchalong/events/$WATCH_EVENT_ID" | jq .
```

Compare wherever a sampled channel exists:
- channel_id
- channel_name
- display_name
- avatar_url
- group
- member_accent
- member_accent_dual
- support_mode
- support_color_source
- profile_revision/profile_updated_at

Unknown-channel control:

```bash
curl -fsS "$API/v1/channels/UCAAAAAAAAAAAAAAAAAAAAAA/profile" | jq .
```

Expected: null/neutral profile, no identity inference.

Acceptance:
- same channel => same canonical profile everywhere;
- canonical values override transitional values;
- Watchalong label/title never manufactures channel identity.

Frontend fallback removal remains a separate later change.

## F. D1 Rows Read observation

Before activation record:
- timestamp;
- active Worker version;
- Cloudflare D1 Usage Rows Read;
- no concurrent polling/index/read optimization rollout.

After activation:
1. run only the bounded readback matrix above;
2. record Rows Read;
3. observe one fixed 15-minute normal-traffic interval without frontend polling changes;
4. record Rows Read again.

Reviewed resolver invariant:
- one-channel and twenty-channel resolution use the same **7** source-class batch
  prepares;
- no per-channel N+1 growth.

Abort/rollback investigation trigger:
- material unexplained Rows Read step-up;
- read growth proportional to channel count;
- repeated identical reads causing unexpected amplification.

## G. Exact execution order

1. preflight READ-ONLY checks
2. deterministic artifact export/hash READ-ONLY
3. migration
4. post-migration checks
5. population dry-run
6. population execute
7. population validation
8. replay/idempotency check
9. Worker version upload
10. Worker version deploy
11. endpoint readback matrix
12. D1 Rows Read observation
13. final PASS / rollback decision

Abort boundary exists before every subsequent mutation.

## H. Final receipt

```text
branch=issue47/canonical-channel-profile-authority
head=<exact reviewed HEAD>
migration_result=<PASS|FAIL|NOT_RUN>
artifact=/tmp/hv47-canonical-channel-profiles-85.json
artifact_sha256=<exact SHA-256>
profile_count=85
population_dry_run=<PASS|FAIL|NOT_RUN>
profiles_written_first=<85|...>
profiles_written_replay=<0|...>
previous_worker_version=<exact ID>
new_worker_version=<exact ID>
endpoint_readback=<PASS|FAIL|NOT_RUN>
d1_rows_read_before=<value>
d1_rows_read_after_bounded_readback=<value>
d1_rows_read_after_15m=<value>
frontend_changed=false
remaining_p0_p1=<none|description>
final=<READY FOR OWNER PRODUCTION EXECUTION|NOT READY — reason>
```

This package itself performs no Production mutation.
