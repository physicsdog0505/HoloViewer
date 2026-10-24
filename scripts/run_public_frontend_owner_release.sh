#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  sh scripts/run_public_frontend_owner_release.sh <expected-release-sha>
  sh scripts/run_public_frontend_owner_release.sh <expected-release-sha> --execute --expected-active-version <version>

Default mode is PREPARE_ONLY and never mutates Production.
EOF
}

EXPECTED_RELEASE_SHA=""
EXECUTE=0
EXPECTED_ACTIVE_VERSION=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --execute)
      EXECUTE=1
      shift
      ;;
    --expected-active-version)
      [ "$#" -ge 2 ] || { usage >&2; exit 2; }
      EXPECTED_ACTIVE_VERSION="$2"
      shift 2
      ;;
    -*)
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$EXPECTED_RELEASE_SHA" ]; then
        usage >&2
        exit 2
      fi
      EXPECTED_RELEASE_SHA="$1"
      shift
      ;;
  esac
done

[ -n "$EXPECTED_RELEASE_SHA" ] || { usage >&2; exit 2; }

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

WRANGLER_CONFIG="cloudflare/wrangler.json"
WORKER_NAME="holoviewer-public"

run_status() {
  npx --yes wrangler deployments status     --config "$WRANGLER_CONFIG"     --name "$WORKER_NAME"
}

active_version() {
  run_status | awk '/Version\(s\):/ {print $NF; exit}'
}

echo "============================================================"
echo "1. EXACT SOURCE GATE"
echo "============================================================"

git fetch origin main

HEAD_SHA=$(git rev-parse HEAD)
REMOTE_MAIN=$(git rev-parse origin/main)

echo "EXPECTED_RELEASE_SHA=$EXPECTED_RELEASE_SHA"
echo "HEAD_SHA=$HEAD_SHA"
echo "REMOTE_MAIN=$REMOTE_MAIN"

[ "$HEAD_SHA" = "$EXPECTED_RELEASE_SHA" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: checkout is not expected release SHA" >&2
  exit 1
}

git merge-base --is-ancestor "$EXPECTED_RELEASE_SHA" origin/main || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: release SHA is not contained in origin/main" >&2
  exit 1
}

[ -z "$(git status --porcelain --untracked-files=all)" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: checkout is not clean" >&2
  exit 1
}

echo
echo "============================================================"
echo "2. STATIC ASSET OWNERSHIP GATE"
echo "============================================================"

FOREIGN_COUNT=$(
  find site -type f \(     -path 'site/youtube/v1/*' -o     -path 'site/ptt/v1/*'   \) -print 2>/dev/null | wc -l | tr -d ' '
)

echo "FOREIGN_OWNER_FILE_COUNT=$FOREIGN_COUNT"

[ "$FOREIGN_COUNT" = "0" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: foreign-owner Static Assets are staged in site/" >&2
  find site -type f \( -path 'site/youtube/v1/*' -o -path 'site/ptt/v1/*' \) -print >&2
  exit 1
}

[ -f site/data/watchalong/manifest.json ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: watchalong manifest missing from frontend-owned site" >&2
  exit 1
}

if [ -d site/data/search/aliases/v1 ]; then
  [ -f site/data/search/aliases/v1/latest.json ] || {
    echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: Alias directory exists without latest.json" >&2
    exit 1
  }
fi

SITE_FILE_COUNT=$(find site -type f | wc -l | tr -d ' ')
WATCHALONG_FILE_COUNT=$(find site/data/watchalong -type f 2>/dev/null | wc -l | tr -d ' ')
ALIAS_FILE_COUNT=$(find site/data/search/aliases/v1 -type f 2>/dev/null | wc -l | tr -d ' ')

echo "SITE_FILE_COUNT=$SITE_FILE_COUNT"
echo "WATCHALONG_FILE_COUNT=$WATCHALONG_FILE_COUNT"
echo "ALIAS_FILE_COUNT=$ALIAS_FILE_COUNT"
echo "STATIC_ASSET_OWNERSHIP_GATE=PASS"

echo
echo "============================================================"
echo "3. WRANGLER CONFIG GATE"
echo "============================================================"

python3 - <<'PY'
import json
from pathlib import Path

p = Path("cloudflare/wrangler.json")
data = json.loads(p.read_text())
assert data.get("name") == "holoviewer-public"
assets = data.get("assets")
assert isinstance(assets, dict)
assert assets.get("directory") == "../site"
print("WRANGLER_CONFIG_GATE=PASS")
PY

BASELINE_VERSION=$(active_version)
[ -n "$BASELINE_VERSION" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: unable to determine active Worker version" >&2
  exit 1
}

echo "BASELINE_ACTIVE_VERSION=$BASELINE_VERSION"

if [ "$EXECUTE" -eq 0 ]; then
  echo
  echo "============================================================"
  echo "PUBLIC_FRONTEND_RELEASE_PREPARE=PASS"
  echo "PRODUCTION_MUTATION=NO"
  echo "DEPLOY=NO"
  echo "============================================================"
  exit 0
fi

[ -n "$EXPECTED_ACTIVE_VERSION" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: --expected-active-version is required with --execute" >&2
  exit 1
}

[ "$BASELINE_VERSION" = "$EXPECTED_ACTIVE_VERSION" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: active Worker version changed since approval" >&2
  exit 1
}

echo
echo "============================================================"
echo "4. OWNER-LOCAL EXECUTE"
echo "============================================================"
echo "OWNER_EXPLICIT_EXECUTE=YES"

npx --yes wrangler deploy   --config "$WRANGLER_CONFIG"   --name "$WORKER_NAME"

NEW_VERSION=$(active_version)

[ -n "$NEW_VERSION" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: unable to determine new Worker version" >&2
  exit 1
}

[ "$NEW_VERSION" != "$BASELINE_VERSION" ] || {
  echo "PUBLIC_FRONTEND_RELEASE=BLOCKED: active Worker version did not change" >&2
  exit 1
}

echo "BASELINE_ACTIVE_VERSION=$BASELINE_VERSION"
echo "NEW_ACTIVE_VERSION=$NEW_VERSION"
echo "PRODUCTION_DEPLOY=COMPLETED"
echo "AUTOMATIC_ROLLBACK=NO"
echo "ROLLBACK_TARGET=$BASELINE_VERSION"
