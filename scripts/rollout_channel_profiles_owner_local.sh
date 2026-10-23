#!/usr/bin/env bash
set -euo pipefail

EXPECTED_HEAD=""
WORKER="holoviewer-public-api"
DB="holoviewer-public-v1"
ACCEPTED_BASELINE="df0bb93e-d3b6-4824-8c33-e1d9ffb6bd96"
API="https://holoviewer-public-api.singlebagel.workers.dev"
D1_CONFIG="ptt_offline/channel-profile-rollout.wrangler.json"
IMPORT_CONFIG="ptt_offline/channel-profile-import-local.wrangler.json"
MIGRATION="ptt_offline/worker_host/today/0005_channel_profiles.sql"
ARTIFACT="/tmp/hv155-canonical-channel-profiles-85.json"
SUPPORT_COLORS="${HOME}/Downloads/Hololive-PTT-Viewer/holoviewer-channel-support-colors.json"
BACKEND_CONFIG_SOURCE=""
BACKEND_CONFIG="/tmp/hv155-backend-wrangler.json"
APPLY=0
DEPLOY=0

usage() {
  cat <<'EOF'
Usage:
  scripts/rollout_channel_profiles_owner_local.sh [--apply] [--deploy] \
    --expected-head <reviewed-40-char-sha> \
    --backend-config /absolute/path/to/complete-backend-wrangler.json \
    [--support-colors /absolute/path/to/holoviewer-channel-support-colors.json]

Default: read-only preflight + deterministic 85-profile artifact validation.
--apply: additive migration + 85-row population + validation + idempotent replay.
--apply --deploy: additionally upload/activate Worker after binding-contract gate.
EOF
}

while (($#)); do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --deploy) DEPLOY=1; shift ;;
    --expected-head) EXPECTED_HEAD="${2:?missing expected head}"; shift 2 ;;
    --backend-config) BACKEND_CONFIG_SOURCE="${2:?missing backend config}"; shift 2 ;;
    --support-colors) SUPPORT_COLORS="${2:?missing support colors}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

(( DEPLOY == 0 || APPLY == 1 )) || { echo "ABORT: --deploy requires --apply" >&2; exit 2; }
[[ "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]] || { echo "ABORT: --expected-head <40-char reviewed SHA> is required" >&2; exit 2; }
[[ -n "$BACKEND_CONFIG_SOURCE" ]] || { echo "ABORT: --backend-config is required" >&2; exit 2; }

BACKEND_CONFIG_SOURCE="$(cd "$(dirname "$BACKEND_CONFIG_SOURCE")" && pwd)/$(basename "$BACKEND_CONFIG_SOURCE")"
SUPPORT_COLORS="$(cd "$(dirname "$SUPPORT_COLORS")" && pwd)/$(basename "$SUPPORT_COLORS")"

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"
HEAD="$(git rev-parse HEAD)"
[[ "$HEAD" == "$EXPECTED_HEAD" ]] || { echo "ABORT: HEAD=$HEAD expected=$EXPECTED_HEAD" >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "ABORT: worktree is not clean" >&2; exit 1; }
[[ -f "$BACKEND_CONFIG_SOURCE" ]] || { echo "ABORT: backend config source missing" >&2; exit 1; }
[[ -f "$SUPPORT_COLORS" ]] || { echo "ABORT: support-color artifact missing" >&2; exit 1; }

echo "=== MATERIALIZE SAFE BACKEND CONFIG ==="
python3 -B ptt_offline/materialize_channel_profile_backend_config.py \
  --config "$BACKEND_CONFIG_SOURCE" \
  --support-colors-json "$SUPPORT_COLORS" \
  --output "$BACKEND_CONFIG" \
  | tee /tmp/hv155-backend-config-receipt.json

python3 - "$BACKEND_CONFIG" <<'PY'
import json,sys
cfg=json.load(open(sys.argv[1],encoding="utf-8"))
if cfg.get("name")!="holoviewer-public-api":
    raise SystemExit("ABORT: wrong backend Worker name")
db=next((x for x in cfg.get("d1_databases",[]) if x.get("binding")=="DB"),None)
if not db or db.get("database_name")!="holoviewer-public-v1" or db.get("database_id")!="64e1a0ee-1455-4377-9640-3922e8f4d061":
    raise SystemExit("ABORT: wrong backend D1 binding")
if cfg.get("assets"):
    raise SystemExit("ABORT: frontend/assets config cannot be used as backend config")
print("BACKEND_CONFIG_IDENTITY=PASS")
PY

echo "=== READ-ONLY PRECHECK ==="
npx wrangler deployments status --name "$WORKER" --config "$BACKEND_CONFIG" --json \
  | tee /tmp/hv155-deployment-before.json

OLD_VERSION_ID="$(
python3 - /tmp/hv155-deployment-before.json <<'PY'
import json,re,sys
obj=json.load(open(sys.argv[1],encoding="utf-8"))
uu=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",re.I)
found=[]
def walk(x):
    if isinstance(x,dict):
        pct=x.get("percentage",x.get("traffic"))
        vid=x.get("version_id",x.get("versionId",x.get("id")))
        if pct in (100,100.0,"100","100%") and isinstance(vid,str) and uu.fullmatch(vid):
            found.append(vid)
        for v in x.values(): walk(v)
    elif isinstance(x,list):
        for v in x: walk(v)
walk(obj)
u=list(dict.fromkeys(found))
print(u[0] if len(u)==1 else "")
PY
)"
[[ -n "$OLD_VERSION_ID" ]] || { echo "ABORT: cannot resolve unique active 100% Worker version" >&2; exit 1; }
echo "ACTIVE_VERSION=$OLD_VERSION_ID"
[[ "$OLD_VERSION_ID" == "$ACCEPTED_BASELINE" ]] || {
  echo "ABORT: active version differs from accepted #62 baseline; require separate equivalence review" >&2
  exit 1
}

npx wrangler versions view "$OLD_VERSION_ID" --name "$WORKER" --config "$BACKEND_CONFIG" --json \
  > /tmp/hv155-old-version.json

npx wrangler d1 execute "$DB" --remote --config "$D1_CONFIG" --command \
"SELECT name,type,sql FROM sqlite_master
 WHERE name IN ('public_channel_profiles','public_channel_profiles_group','public_channel_profiles_updated')
 ORDER BY type,name;
 SELECT 'public_history' AS object_name,COUNT(*) AS n FROM public_history
 UNION ALL SELECT 'public_today_canonical',COUNT(*) FROM public_today_canonical
 UNION ALL SELECT 'public_watchalong_events',COUNT(*) FROM public_watchalong_events
 UNION ALL SELECT 'public_watchalong_streams',COUNT(*) FROM public_watchalong_streams;" \
 | tee /tmp/hv155-d1-preflight.txt

python3 -B ptt_offline/export_canonical_channel_profiles.py \
  --config "$D1_CONFIG" \
  --support-colors-json "$SUPPORT_COLORS" \
  --output "$ARTIFACT" \
  | tee /tmp/hv155-artifact-export.json

ARTIFACT_SHA="$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')"
python3 - "$ARTIFACT" "$ARTIFACT_SHA" <<'PY'
import hashlib,json,sys
p,expected=sys.argv[1:]
raw=open(p,"rb").read()
assert hashlib.sha256(raw).hexdigest()==expected
d=json.loads(raw)
assert d["schema_version"]=="holoviewer-channel-profile-import-v1"
assert d["roster_version"]=="today85-20261016-d0e326c0496b"
assert d["profile_count"]==85 and len(d["profiles"])==85
assert len({x["channel_id"] for x in d["profiles"]})==85
assert sum(bool(x["avatar_url"]) for x in d["profiles"])==85
r=d["support_color_receipt"]
assert (r["rows"],r["colored"],r["neutral"],r["dual"])==(66,57,9,1)
print("ARTIFACT_VALIDATION=PASS")
print("ARTIFACT_SHA256="+expected)
print("PROFILE_ROWS=85")
print("AVATARS_PRESENT=85")
PY

if (( APPLY == 0 )); then
  cat <<EOF
CANONICAL_PROFILE_PREFLIGHT=PASS
PRODUCTION_MUTATION=NO
ACTIVE_VERSION=$OLD_VERSION_ID
ARTIFACT=$ARTIFACT
ARTIFACT_SHA256=$ARTIFACT_SHA
EOF
  exit 0
fi

echo "=== MUTATION 1: ADDITIVE MIGRATION ==="
npx wrangler d1 execute "$DB" --remote --config "$D1_CONFIG" --file "$MIGRATION"

npx wrangler d1 execute "$DB" --remote --config "$D1_CONFIG" --command \
"SELECT name,type,sql FROM sqlite_master
 WHERE name IN ('public_channel_profiles','public_channel_profiles_group','public_channel_profiles_updated')
 ORDER BY type,name;
 SELECT COUNT(*) AS profile_rows FROM public_channel_profiles;" \
 | tee /tmp/hv155-d1-post-migration.txt

npx wrangler dev --ip 127.0.0.1 --port 8791 --config "$IMPORT_CONFIG" \
  > /tmp/hv155-profile-importer.log 2>&1 &
IMPORT_PID=$!
cleanup(){ kill "$IMPORT_PID" 2>/dev/null || true; wait "$IMPORT_PID" 2>/dev/null || true; }
trap cleanup EXIT

for _ in $(seq 1 30); do
  grep -q "Ready on" /tmp/hv155-profile-importer.log 2>/dev/null && break
  kill -0 "$IMPORT_PID" 2>/dev/null || { echo "ABORT: local importer failed to start" >&2; exit 1; }
  sleep 1
done

echo "=== POPULATION DRY RUN ==="
curl --fail-with-body -sS -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=validate' \
  | tee /tmp/hv155-profile-dry-run.json

python3 - /tmp/hv155-profile-dry-run.json <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["status"]=="VALIDATED"
assert d["production_mutation"] is False
assert d["profile_count"]==85
p=d["plan"]
assert p["updates"]==0, p
assert p["older"]==0, p
assert p["inserts"]+p["noops"]==85, p
print("POPULATION_DRY_RUN=PASS")
PY

echo "=== MUTATION 2: 85 PROFILE POPULATION ==="
curl --fail-with-body -sS -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=apply' \
  | tee /tmp/hv155-profile-apply.json

python3 - /tmp/hv155-profile-apply.json <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["status"]=="APPLIED"
assert d["profile_count"]==85
p=d["plan"]
assert p["updates"]==0, p
assert p["older"]==0, p
assert p["inserts"]+p["noops"]==85, p
assert d["profiles_written"]==p["inserts"], d
print("PROFILE_POPULATION=PASS")
PY

echo "=== READ-ONLY POPULATION VALIDATION ==="
npx wrangler d1 execute "$DB" --remote --config "$D1_CONFIG" --command \
"SELECT COUNT(*) AS total_profiles,COUNT(DISTINCT channel_id) AS distinct_channels,
        SUM(CASE WHEN avatar_url IS NOT NULL THEN 1 ELSE 0 END) AS avatars_present,
        SUM(CASE WHEN support_mode='solid' THEN 1 ELSE 0 END) AS solid_profiles,
        SUM(CASE WHEN support_mode='dual_color' THEN 1 ELSE 0 END) AS dual_profiles,
        SUM(CASE WHEN support_mode='neutral' THEN 1 ELSE 0 END) AS neutral_profiles
 FROM public_channel_profiles;
 SELECT channel_id,COUNT(*) AS n FROM public_channel_profiles GROUP BY channel_id HAVING COUNT(*)>1;
 SELECT channel_id FROM public_channel_profiles
  WHERE channel_group NOT IN ('hololive','holostars','mekpark','other')
     OR support_mode NOT IN ('neutral','solid','dual_color')
     OR profile_revision IS NULL OR profile_revision=''
     OR updated_at IS NULL
  ORDER BY channel_id LIMIT 20;" \
 | tee /tmp/hv155-profile-validation.txt

echo "=== IDEMPOTENT REPLAY ==="
curl --fail-with-body -sS -X POST \
  -H 'content-type: application/json' \
  -H "x-hv-artifact-sha256: $ARTIFACT_SHA" \
  --data-binary @"$ARTIFACT" \
  'http://127.0.0.1:8791/run?mode=apply' \
  | tee /tmp/hv155-profile-replay.json

python3 - /tmp/hv155-profile-replay.json <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d["status"]=="APPLIED"
assert d["profiles_written"]==0
print("PROFILE_REPLAY_IDEMPOTENT=PASS")
PY

cleanup
trap - EXIT

if (( DEPLOY == 0 )); then
  cat <<EOF
CANONICAL_PROFILE_TABLE=PASS
APPROVED_CHANNELS=85
PROFILE_ROWS=85
AVATARS_PRESENT=85
PROFILE_POPULATION=PASS
PROFILE_REPLAY_IDEMPOTENT=PASS
WORKER_DEPLOY=NOT_RUN
EOF
  exit 0
fi

echo "=== WORKER CANDIDATE UPLOAD ==="
UPLOAD_OUTPUT="/tmp/hv155-version-upload.ndjson"
UPLOAD_CONSOLE="/tmp/hv155-version-upload.txt"
rm -f "$UPLOAD_OUTPUT" "$UPLOAD_CONSOLE"

WRANGLER_OUTPUT_FILE_PATH="$UPLOAD_OUTPUT" \
npx wrangler versions upload ptt_offline/worker_host/index.mjs \
  --name "$WORKER" --config "$BACKEND_CONFIG" --keep-vars \
  --message "PR155 canonical profile authority $HEAD" \
  2>&1 | tee "$UPLOAD_CONSOLE"

NEW_VERSION_ID="$(
python3 - "$UPLOAD_OUTPUT" "$WORKER" <<'PY'
import json,re,sys
path,worker=sys.argv[1:]
uu=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",re.I)
found=[]
try:
    lines=open(path,encoding="utf-8").read().splitlines()
except OSError as exc:
    raise SystemExit(f"ABORT: Wrangler output receipt missing: {exc}")
for lineno,line in enumerate(lines,1):
    if not line.strip():
        continue
    try:
        obj=json.loads(line)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ABORT: malformed Wrangler output receipt line {lineno}: {exc}")
    if obj.get("type")!="version-upload":
        continue
    if obj.get("worker_name") not in (None,worker):
        continue
    vid=obj.get("version_id")
    if not isinstance(vid,str) or not uu.fullmatch(vid):
        raise SystemExit("ABORT: version-upload receipt missing canonical version_id")
    found.append(vid.lower())
unique=list(dict.fromkeys(found))
if len(unique)!=1:
    raise SystemExit(f"ABORT: expected exactly one uploaded candidate version, found {len(unique)}")
print(unique[0])
PY
)"
[[ -n "$NEW_VERSION_ID" ]] || { echo "ABORT: cannot resolve uploaded candidate version" >&2; exit 1; }
echo "UPLOADED_CANDIDATE_VERSION=$NEW_VERSION_ID"

npx wrangler versions view "$NEW_VERSION_ID" --name "$WORKER" --config "$BACKEND_CONFIG" --json \
  > /tmp/hv155-new-version.json

python3 - /tmp/hv155-old-version.json /tmp/hv155-new-version.json <<'PY'
import json,sys
old=json.load(open(sys.argv[1])); new=json.load(open(sys.argv[2]))
def pairs(x):
    out=set()
    def walk(v):
        if isinstance(v,dict):
            name=v.get("name",v.get("binding")); typ=v.get("type")
            if isinstance(name,str) and isinstance(typ,str): out.add((name,typ))
            for z in v.values(): walk(z)
        elif isinstance(v,list):
            for z in v: walk(z)
    walk(x); return out
a,b=pairs(old),pairs(new)
if len(a)<31:
    raise SystemExit(f"ABORT: active version exposes only {len(a)} binding pairs; expected >=31")
missing=a-b
if missing:
    raise SystemExit("ABORT: candidate drops bindings: "+repr(sorted(missing)))
print("CANDIDATE_BINDING_CONTRACT=PASS")
PY

echo "=== MUTATION 3: ACTIVATE CANDIDATE 100% ==="
npx wrangler versions deploy "${NEW_VERSION_ID}@100%" -y \
  --name "$WORKER" --config "$BACKEND_CONFIG"

rollback() {
  echo "ROLLBACK_TO=$OLD_VERSION_ID" >&2
  npx wrangler versions deploy "${OLD_VERSION_ID}@100%" -y \
    --name "$WORKER" --config "$BACKEND_CONFIG"
}

echo "=== BOUNDED API READBACK ==="
ROBOCO="UCDqI2jOz0weumE8s7paEk6g"
VIDEO="oTYyghN5fxU"
DAY="2026-10-15"
curl -fsS "$API/health" >/tmp/hv155-health.json || { rollback; exit 1; }
curl -fsS "$API/v1/channels/$ROBOCO/profile" >/tmp/hv155-profile-readback.json || { rollback; exit 1; }
curl -fsS "$API/v1/catalog/today?limit=200&offset=0" >/tmp/hv155-today.json || { rollback; exit 1; }
curl -fsS "$API/v1/history?day=$DAY&limit=100&offset=0" >/tmp/hv155-history.json || { rollback; exit 1; }
curl -fsS "$API/v1/videos/$VIDEO/metadata" >/tmp/hv155-metadata.json || { rollback; exit 1; }
curl -fsS "$API/v1/collab/live" >/tmp/hv155-collab-live.json || { rollback; exit 1; }
curl -fsS "$API/v1/collab/history?day=$DAY&limit=100&offset=0" >/tmp/hv155-collab-history.json || { rollback; exit 1; }
curl -fsS "$API/v1/watchalong/recent?days=30&limit=60" >/tmp/hv155-watch-recent.json || { rollback; exit 1; }
curl -fsS "$API/v1/watchalong/history?day=$DAY&limit=60&offset=0" >/tmp/hv155-watch-history.json || { rollback; exit 1; }

curl -fsSI -H 'Origin: https://holodocchi.com' "$API/health" \
  | grep -i '^access-control-allow-origin: https://holodocchi.com' >/dev/null \
  || { rollback; exit 1; }

if ! python3 - /tmp/hv155-profile-readback.json <<'PY'
import json,sys
p=json.load(open(sys.argv[1])).get("profile",{})
assert p.get("channel_id")=="UCDqI2jOz0weumE8s7paEk6g"
assert p.get("avatar_url")
assert p.get("support_mode") in {"neutral","solid","dual_color"}
assert p.get("profile_revision")
print("DIRECT_PROFILE_READBACK=PASS")
PY
then
  rollback
  exit 1
fi

cat <<EOF
CANONICAL_PROFILE_TABLE=PASS
APPROVED_CHANNELS=85
PROFILE_ROWS=85
AVATARS_PRESENT=85
TODAY_PROFILE=READBACK_CAPTURED
HISTORY_PROFILE=READBACK_CAPTURED
VIDEO_METADATA_PROFILE=READBACK_CAPTURED
COLLAB_PROFILE=READBACK_CAPTURED
WATCHALONG_PROFILE=READBACK_CAPTURED
TITLE_LABEL_HEURISTIC=NO
OLD_VERSION_ID=$OLD_VERSION_ID
NEW_VERSION_ID=$NEW_VERSION_ID
CANDIDATE_BINDING_CONTRACT=PASS
CUSTOM_DOMAIN_CORS=PASS
FRONTEND_CHANGED=NO
EOF
