#!/bin/sh
set -eu

EXPECTED_HEAD="${1:-}"
SOURCE_V1="${2:-$HOME/.holoviewer/youtube-static-assets/youtube/v1}"
PROFILE="${PROFILE:-}"

fail() {
  printf 'issue448 preview: %s\n' "$*" >&2
  exit 1
}

require_hex40() {
  value="$1"
  [ "${#value}" -eq 40 ] || fail "EXPECTED_HEAD must be 40 hex chars"
  case "$value" in *[!0-9a-f]*) fail "EXPECTED_HEAD must be lowercase hex" ;; esac
}

require_hex40 "$EXPECTED_HEAD"

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

[ "$(git rev-parse HEAD)" = "$EXPECTED_HEAD" ] || fail "checkout is not expected reviewed HEAD"
[ -z "$(git status --porcelain --untracked-files=all)" ] || fail "checkout is not clean"
[ -f "$SOURCE_V1/manifest.json" ] || fail "accepted youtube/v1 manifest missing"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ALIAS_STAMP="$(printf '%s' "$STAMP" | tr '[:upper:]' '[:lower:]')"
ALIAS="issue448-$ALIAS_STAMP"
TMP="$(mktemp -d /private/tmp/holoviewer-issue448.XXXXXX)"
OUT="/tmp/holoviewer-issue448-$STAMP"
mkdir -p "$OUT"

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT HUP INT TERM

PROFILE_ARGS=""
if [ -n "$PROFILE" ]; then
  PROFILE_ARGS="--profile $PROFILE"
fi

echo "============================================================"
echo "ISSUE #448 STATIC ASSETS VERSION URL PILOT"
echo "============================================================"
echo "HEAD=$EXPECTED_HEAD"
echo "SOURCE_V1=$SOURCE_V1"
echo "ALIAS=$ALIAS"
echo "OUT=$OUT"

echo
echo "=== 1. LOCAL TREE + TESTS ==="
if ! python3 scripts/youtube_static_assets_preview.py check-local \
  --v1 "$SOURCE_V1" >"$OUT/local-readback.json" 2>&1; then
  cat "$OUT/local-readback.json"
  fail "local youtube/v1 readback failed"
fi
cat "$OUT/local-readback.json"

if ! python3 -B -m unittest -v \
  test_youtube_static_assets_preview >"$OUT/tests.txt" 2>&1; then
  cat "$OUT/tests.txt"
  fail "offline regression failed"
fi
cat "$OUT/tests.txt"

echo
echo "=== 2. STAGE EXISTING SITE + ACCEPTED YOUTUBE TREE ==="
if ! python3 scripts/youtube_static_assets_preview.py stage \
  --source-site site \
  --source-v1 "$SOURCE_V1" \
  --target-site "$TMP/site" >"$OUT/stage.json" 2>&1; then
  cat "$OUT/stage.json"
  fail "Static Assets staging failed"
fi
cat "$OUT/stage.json"

if ! python3 scripts/youtube_static_assets_preview.py write-config \
  --source-config cloudflare/wrangler.json \
  --output-config "$TMP/wrangler.json" \
  --staged-site "$TMP/site" >"$OUT/config.json" 2>&1; then
  cat "$OUT/config.json"
  fail "preview Wrangler config generation failed"
fi
cat "$OUT/config.json"

echo
echo "=== 3. CAPTURE ACTIVE PRODUCTION DEPLOYMENT ==="
BASELINE_STATUS="$OUT/deployments-before.txt"
npx --yes wrangler deployments status   --config cloudflare/wrangler.json   --name holoviewer-public   $PROFILE_ARGS >"$BASELINE_STATUS"

cat "$BASELINE_STATUS"
BASELINE_VERSION="$(awk '/Version\(s\):/{print $3; exit}' "$BASELINE_STATUS")"
[ -n "$BASELINE_VERSION" ] || fail "could not parse baseline active version"
echo "BASELINE_ACTIVE_VERSION=$BASELINE_VERSION"

echo
echo "=== 4. UPLOAD VERSION ONLY — NO DEPLOYMENT ==="
UPLOAD_OUT="$OUT/version-upload.txt"
if ! npx --yes wrangler versions upload \
  --config "$TMP/wrangler.json" \
  --name holoviewer-public \
  --preview-alias "$ALIAS" \
  --message "Issue #448 Static Assets Version URL pilot $EXPECTED_HEAD" \
  $PROFILE_ARGS >"$UPLOAD_OUT" 2>&1; then
  cat "$UPLOAD_OUT"
  fail "Cloudflare version upload failed"
fi
cat "$UPLOAD_OUT"

VERSION_URL="$(grep -Eo 'https://[A-Za-z0-9.-]+\.workers\.dev' "$UPLOAD_OUT" | tail -n1 || true)"
[ -n "$VERSION_URL" ] || fail "Wrangler did not return a Version URL"
echo "PREVIEW_OR_VERSION_URL=$VERSION_URL"

echo
echo "=== 5. HTTP READBACK OF COMPLETE YOUTUBE/V1 TREE ==="
if ! python3 scripts/youtube_static_assets_preview.py verify-http \
  --base-url "$VERSION_URL" \
  --v1 "$SOURCE_V1" \
  --nonce "$STAMP" >"$OUT/http-readback.json" 2>&1; then
  cat "$OUT/http-readback.json"
  fail "Version URL HTTP readback failed"
fi
cat "$OUT/http-readback.json"

echo
echo "=== 6. VERIFY PRODUCTION ACTIVE DEPLOYMENT UNCHANGED ==="
POST_STATUS="$OUT/deployments-after.txt"
npx --yes wrangler deployments status   --config cloudflare/wrangler.json   --name holoviewer-public   $PROFILE_ARGS >"$POST_STATUS"

cat "$POST_STATUS"
POST_VERSION="$(awk '/Version\(s\):/{print $3; exit}' "$POST_STATUS")"
[ -n "$POST_VERSION" ] || fail "could not parse post-upload active version"
[ "$POST_VERSION" = "$BASELINE_VERSION" ] || fail "Production active deployment changed"

echo "POST_ACTIVE_VERSION=$POST_VERSION"

echo
echo "=== 7. RECEIPT ==="
cat >"$OUT/receipt.txt" <<EOF
STATIC_ASSETS_PREVIEW_UPLOAD=PASS
PREVIEW_OR_VERSION_URL=$VERSION_URL
MANIFEST_HTTP_READBACK=PASS
MONTH_OBJECTS_HTTP_READBACK=PASS
CHANNEL_INDEX_HTTP_READBACK=PASS
BASELINE_ACTIVE_VERSION=$BASELINE_VERSION
POST_ACTIVE_VERSION=$POST_VERSION
PRODUCTION_TRAFFIC_CHANGED=NO
PRODUCTION_FRONTEND_CHANGED=NO
PRODUCTION_D1_CHANGED=NO
PRODUCTION_WORKER_CHANGED=NO
SCHEDULER_INSTALLED=NO
R2_USED=NO
READY_FOR_GATE4_PRODUCTION_STATIC_ASSETS=YES
EVIDENCE_DIR=$OUT
EOF

cat "$OUT/receipt.txt"

echo
echo "NOTE: the uploaded Version remains inert until an explicit"
echo "      'wrangler versions deploy' or 'wrangler deploy' is run."
echo "      A later Version upload replaces the alias target without"
echo "      switching Production traffic."
