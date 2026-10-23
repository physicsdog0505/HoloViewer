#!/bin/sh
set -eu

EXPECTED_HEAD="${1:-}"
EXPECTED_BASELINE_VERSION="${2:-}"
EXPECTED_SOURCE_MANIFEST_SHA="${3:-}"
EXPECTED_CURRENT_MONTH="${4:-}"
SOURCE_V1="${5:-$HOME/.holoviewer/youtube-static-assets/youtube/v1}"

PROD_SITE_BASE_SHA="f6e2a84a46a278e3e2a2de90561588adb6d9ebf0"
LIVE_ORIGIN="https://holodocchi.com"
WORKERS_ORIGIN="https://holoviewer-public.singlebagel.workers.dev"

fail() {
  printf 'issue437 gate4: %s\n' "$*" >&2
  exit 1
}

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    sha256sum "$1" | awk '{print $1}'
  fi
}

require_hex() {
  value="$1"
  length="$2"
  label="$3"
  [ "${#value}" -eq "$length" ] || fail "$label must be $length lowercase hex characters"
  case "$value" in *[!0-9a-f]*) fail "$label must be lowercase hexadecimal" ;; esac
}

require_hex "$EXPECTED_HEAD" 40 "EXPECTED_HEAD"
require_hex "$EXPECTED_SOURCE_MANIFEST_SHA" 64 "EXPECTED_SOURCE_MANIFEST_SHA"
[ -n "$EXPECTED_BASELINE_VERSION" ] || fail "EXPECTED_BASELINE_VERSION required"
case "$EXPECTED_CURRENT_MONTH" in
  ????-??) ;;
  *) fail "EXPECTED_CURRENT_MONTH must be YYYY-MM" ;;
esac

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

git fetch origin main >/dev/null 2>&1
[ "$(git rev-parse HEAD)" = "$EXPECTED_HEAD" ] || fail "checkout is not EXPECTED_HEAD"
git merge-base --is-ancestor "$EXPECTED_HEAD" origin/main || fail "EXPECTED_HEAD is not contained in current origin/main"
[ -z "$(git status --porcelain --untracked-files=all)" ] || fail "checkout is not clean"
git cat-file -e "${PROD_SITE_BASE_SHA}^{commit}"
[ -z "$(git diff --name-only "$PROD_SITE_BASE_SHA" "$EXPECTED_HEAD" -- site/)" ] || fail "site/** differs from accepted Production frontend baseline"
[ -f "$SOURCE_V1/manifest.json" ] || fail "canonical youtube/v1 manifest missing"
[ "$(sha256_file "$SOURCE_V1/manifest.json")" = "$EXPECTED_SOURCE_MANIFEST_SHA" ] || fail "canonical source manifest SHA changed"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp -d /private/tmp/holoviewer-issue437-gate4.XXXXXX)"
OUT="/tmp/holoviewer-issue437-gate4-$STAMP"
mkdir -p "$OUT"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

echo "=== 1. BUILD CURRENT-ONLY CANDIDATE ==="
python3 scripts/youtube_static_assets_preview.py stage-current-release \
  --source-site site \
  --source-v1 "$SOURCE_V1" \
  --target-site "$TMP/site" \
  --expected-current-month "$EXPECTED_CURRENT_MONTH" >"$OUT/scope.json"

jq -e '
  .release_scope == "CURRENT_ONLY" and
  .month_count == 1 and
  .historical_months_included == 0 and
  .full_128_month_history == false and
  .object_count == (.channel_index_count + 2)
' "$OUT/scope.json" >/dev/null || fail "computed YouTube scope violates Gate-4 bounds"

[ ! -d "$TMP/site/youtube/v1/archive" ] || \
  [ -z "$(find "$TMP/site/youtube/v1/archive" -type f -print -quit)" ] || \
  fail "historical archive object entered candidate"

python3 scripts/youtube_static_assets_preview.py write-config \
  --source-config cloudflare/wrangler.json \
  --output-config "$TMP/wrangler.json" \
  --staged-site "$TMP/site" >"$OUT/config.json"

echo
echo "============================================================"
echo "GATE4 EXACT BOUNDED SCOPE — BEFORE MUTATION"
echo "============================================================"
echo "GATE4_RELEASE_SHA=$EXPECTED_HEAD"
echo "ACTIVE_FRONTEND_SOURCE_SHA=$PROD_SITE_BASE_SHA"
echo "EXPECTED_ACTIVE_FRONTEND_VERSION=$EXPECTED_BASELINE_VERSION"
echo "ROLLBACK_VERSION=$EXPECTED_BASELINE_VERSION"
echo "YOUTUBE_MONTH_PATHS=$(jq -r '.month_paths | join(",")' "$OUT/scope.json")"
echo "YOUTUBE_MONTH_COUNT=$(jq -r '.month_count' "$OUT/scope.json")"
echo "YOUTUBE_CHANNEL_INDEX_COUNT=$(jq -r '.channel_index_count' "$OUT/scope.json")"
echo "YOUTUBE_OBJECT_COUNT=$(jq -r '.object_count' "$OUT/scope.json")"
echo "YOUTUBE_TOTAL_BYTES=$(jq -r '.total_bytes' "$OUT/scope.json")"
echo "HISTORICAL_MONTHS_INCLUDED=0"
echo "FULL_128_MONTH_HISTORY=NO"
echo "OTHER_APPROVED_FRONTEND_DELTA=NONE"
echo "UNEXPECTED_SITE_DELTA=NO"
echo "WATCHALONG_ASSETS_PRESERVED=YES"
echo "PTT_STATIC_ASSETS_PRESERVED=YES"
echo "READBACK_MODE=MANIFEST_PLUS_CHANGED_DELTA"
echo "YOUTUBE_OBJECT_PATHS_BEGIN"
jq -r '.object_paths[]' "$OUT/scope.json"
echo "YOUTUBE_OBJECT_PATHS_END"
echo "============================================================"

echo
echo "=== 2. CAPTURE / VERIFY PRODUCTION BASELINE ==="
BASELINE_STATUS="$OUT/deployments-before.txt"
npx --yes wrangler deployments status \
  --config cloudflare/wrangler.json \
  --name holoviewer-public >"$BASELINE_STATUS"
cat "$BASELINE_STATUS"
BASELINE_VERSION="$(awk '/Version\(s\):/{print $3; exit}' "$BASELINE_STATUS")"
[ "$BASELINE_VERSION" = "$EXPECTED_BASELINE_VERSION" ] || fail "Production active version changed"

# First YouTube Production release must not overwrite an already-live YouTube manifest.
if curl -fsS --max-time 10 "$LIVE_ORIGIN/youtube/v1/manifest.json?gate4=baseline-$STAMP" \
    -o "$OUT/live-youtube-manifest.before" 2>/dev/null; then
  if jq -e '.schema_version == 1 and (.months|type=="array")' "$OUT/live-youtube-manifest.before" >/dev/null 2>&1; then
    fail "Production already has a YouTube v1 manifest; first-publish mode refuses overwrite"
  fi
fi

for rel in "/" "/assets/app.js" "/data/watchalong/manifest.json" "/ptt-today/" "/viewer/" "/watchalong-viewer/"; do
  safe="$(printf '%s' "$rel" | tr '/.' '__')"
  curl -fsS --max-time 15 "$LIVE_ORIGIN$rel?gate4=before-$STAMP" -o "$OUT/protected-before-$safe"
  sha256_file "$OUT/protected-before-$safe" >"$OUT/protected-before-$safe.sha256"
done

echo
echo "=== 3. OWNER-LOCAL PRODUCTION DEPLOY ==="
npx --yes wrangler deploy \
  --config "$TMP/wrangler.json" \
  --name holoviewer-public

echo
echo "=== 4. BOUNDED DUAL-ORIGIN YOUTUBE READBACK ==="
for origin in "$LIVE_ORIGIN" "$WORKERS_ORIGIN"; do
  label="$(printf '%s' "$origin" | sed 's#https://##; s#[^A-Za-z0-9]#_#g')"
  attempt=1
  ok=0
  while [ "$attempt" -le 4 ]; do
    if python3 scripts/youtube_static_assets_preview.py verify-http \
      --base-url "$origin" \
      --v1 "$TMP/site/youtube/v1" \
      --nonce "$STAMP-$attempt" \
      --workers 12 >"$OUT/readback-$label-$attempt.txt" 2>&1; then
      cat "$OUT/readback-$label-$attempt.txt"
      ok=1
      break
    fi
    cat "$OUT/readback-$label-$attempt.txt"
    attempt=$((attempt + 1))
    [ "$attempt" -le 4 ] && sleep $((attempt * 2))
  done
  [ "$ok" -eq 1 ] || fail "YouTube readback failed persistently for $origin"
done

echo
echo "=== 5. FORWARD-ONLY PROTECTED ASSET READBACK ==="
for rel in "/" "/assets/app.js" "/data/watchalong/manifest.json" "/ptt-today/" "/viewer/" "/watchalong-viewer/"; do
  safe="$(printf '%s' "$rel" | tr '/.' '__')"
  curl -fsS --max-time 15 "$LIVE_ORIGIN$rel?gate4=after-$STAMP" -o "$OUT/protected-after-$safe"
  [ "$(sha256_file "$OUT/protected-after-$safe")" = "$(cat "$OUT/protected-before-$safe.sha256")" ] || \
    fail "protected non-YouTube Production asset changed: $rel"
done

POST_STATUS="$OUT/deployments-after.txt"
npx --yes wrangler deployments status \
  --config cloudflare/wrangler.json \
  --name holoviewer-public >"$POST_STATUS"
cat "$POST_STATUS"
POST_VERSION="$(awk '/Version\(s\):/{print $3; exit}' "$POST_STATUS")"
[ -n "$POST_VERSION" ] || fail "could not parse new Production version"
[ "$POST_VERSION" != "$BASELINE_VERSION" ] || fail "Production active version did not change"

echo
echo "=== 6. GATE-4 RECEIPT ==="
cat <<EOF
GATE4_PRODUCTION_STATIC_ASSETS=PASS
GATE4_RELEASE_SHA=$EXPECTED_HEAD
BASELINE_ACTIVE_VERSION=$BASELINE_VERSION
NEW_ACTIVE_VERSION=$POST_VERSION
ROLLBACK_VERSION=$BASELINE_VERSION
YOUTUBE_CURRENT_MONTH=$EXPECTED_CURRENT_MONTH
YOUTUBE_MONTH_COUNT=1
YOUTUBE_CHANNEL_INDEX_COUNT=$(jq -r '.channel_index_count' "$OUT/scope.json")
YOUTUBE_OBJECT_COUNT=$(jq -r '.object_count' "$OUT/scope.json")
YOUTUBE_TOTAL_BYTES=$(jq -r '.total_bytes' "$OUT/scope.json")
HISTORICAL_MONTHS_INCLUDED=0
FULL_128_MONTH_HISTORY=NO
DUAL_ORIGIN_READBACK=PASS
WATCHALONG_ASSETS_PRESERVED=YES
PTT_STATIC_ASSETS_PRESERVED=YES
PRODUCTION_D1_CHANGED=NO
PRODUCTION_API_WORKER_CHANGED=NO
SCHEDULER_INSTALLED=NO
R2_USED=NO
READY_FOR_GATE5_SCHEDULER_REVIEW=YES
EVIDENCE_DIR=$OUT
ROLLBACK_COMMAND=cd $repo_root && npx --yes wrangler rollback $BASELINE_VERSION --config cloudflare/wrangler.json --name holoviewer-public
EOF
