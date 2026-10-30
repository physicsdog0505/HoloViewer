#!/bin/sh
set -eu

WORKER_NAME="holoviewer-watchalong-static-assets"
WRANGLER_CONFIG="cloudflare/watchalong-static-assets.wrangler.json"
ASSET_ROOT="watchalong-static"
MANIFEST_REL="data/watchalong/manifest.json"
LIVE_ORIGIN="https://holoviewer-watchalong-static-assets.singlebagel.workers.dev"

fail() {
  printf 'Watchalong Static Assets release: %s\n' "$*" >&2
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
  [ "${#value}" -eq "$length" ] || fail "$label must be $length hexadecimal characters"
  case "$value" in *[!0-9a-f]*) fail "$label must be lowercase hexadecimal" ;; esac
}

current_version() {
  tmp="$(mktemp /private/tmp/watchalong-static-status.XXXXXX)"
  if npx --yes wrangler deployments status --config "$WRANGLER_CONFIG" --name "$WORKER_NAME" >"$tmp" 2>&1; then
    awk '/Version\(s\):/{print $3; exit}' "$tmp"
  else
    printf 'ABSENT\n'
  fi
  rm -f "$tmp"
}

verify_candidate() {
  expected_head="$1"
  expected_manifest_sha="$2"
  repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
  cd "$repo_root"
  [ "$(git rev-parse HEAD)" = "$expected_head" ] || fail "checkout is not reviewed candidate HEAD"
  [ -z "$(git status --porcelain --untracked-files=all)" ] || fail "candidate checkout is not clean"
  [ ! -e site/data/watchalong ] || fail "Watchalong data is still packaged by holoviewer-public"
  [ -f "$ASSET_ROOT/$MANIFEST_REL" ] || fail "dedicated manifest missing"
  [ "$(sha256_file "$ASSET_ROOT/$MANIFEST_REL")" = "$expected_manifest_sha" ] || fail "candidate manifest hash mismatch"
  jq -e '.schema_version == "holoviewer-watchalong-manifest-v1" and .event_count == 6 and (.events|length) == 6' "$ASSET_ROOT/$MANIFEST_REL" >/dev/null || fail "candidate manifest inventory mismatch"
  jq -r '.events[] | [.path,.sha256] | @tsv' "$ASSET_ROOT/$MANIFEST_REL" | while IFS="$(printf '\t')" read -r path expected; do
    require_hex "$expected" 64 "event SHA-256"
    file="$ASSET_ROOT/${path#/}"
    [ -f "$file" ] || fail "candidate event missing: $path"
    [ "$(sha256_file "$file")" = "$expected" ] || fail "candidate event hash mismatch: $path"
  done
  SOURCE_ROOT="${SOURCE_ROOT:-/Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer}"
  APPROVED_SYNC_ROOT="${APPROVED_SYNC_ROOT:-}"
  [ -n "$APPROVED_SYNC_ROOT" ] || fail "APPROVED_SYNC_ROOT must point to exact reviewed authority checkout"
  python3 scripts/export_watchalong_assets.py --source-root "$SOURCE_ROOT" --approved-sync-root "$APPROVED_SYNC_ROOT" --output-root "$ASSET_ROOT/data/watchalong" --check
  python3 -B -m unittest -v test_watchalong_assets
}

readback() {
  expected_manifest_sha="$1"
  nonce="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$(mktemp -d /private/tmp/watchalong-static-readback.XXXXXX)"
  curl -fsS --max-time 30 "$LIVE_ORIGIN/$MANIFEST_REL?release=$nonce" -o "$tmp/manifest.json"
  [ "$(sha256_file "$tmp/manifest.json")" = "$expected_manifest_sha" ] || fail "production manifest hash mismatch"
  jq -r '.events[] | [.path,.sha256] | @tsv' "$tmp/manifest.json" | while IFS="$(printf '\t')" read -r path expected; do
    out="$tmp/$(basename "$path")"
    curl -fsS --max-time 30 "$LIVE_ORIGIN$path?release=$nonce" -o "$out"
    [ "$(sha256_file "$out")" = "$expected" ] || fail "production event hash mismatch: $path"
  done
  cors="$(curl -fsSI --max-time 30 "$LIVE_ORIGIN/$MANIFEST_REL?release=$nonce" | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2; exit}')"
  [ "$cors" = "*" ] || fail "CORS header mismatch"
  printf 'WATCHALONG_STATIC_READBACK=PASS origin=%s manifest_sha256=%s\n' "$LIVE_ORIGIN" "$expected_manifest_sha"
}

mode="${1:-}"
case "$mode" in
  prepare)
    [ "$#" -eq 3 ] || fail "usage: $0 prepare EXPECTED_HEAD MANIFEST_SHA256"
    require_hex "$2" 40 "candidate HEAD"
    require_hex "$3" 64 "manifest SHA-256"
    verify_candidate "$2" "$3"
    baseline="$(current_version)"
    printf 'WATCHALONG_STATIC_PREPARE=PASS\n'
    printf 'CANDIDATE_HEAD=%s\n' "$2"
    printf 'MANIFEST_SHA256=%s\n' "$3"
    printf 'BASELINE_VERSION=%s\n' "$baseline"
    printf 'PRODUCTION_MUTATION=NO\n'
    ;;
  deploy)
    [ "$#" -eq 4 ] || fail "usage: $0 deploy EXPECTED_HEAD MANIFEST_SHA256 EXPECTED_BASELINE_VERSION"
    require_hex "$2" 40 "candidate HEAD"
    require_hex "$3" 64 "manifest SHA-256"
    verify_candidate "$2" "$3"
    baseline="$(current_version)"
    [ "$baseline" = "$4" ] || fail "dedicated Worker baseline changed since Owner approval"
    npx --yes wrangler deploy --config "$WRANGLER_CONFIG" --name "$WORKER_NAME"
    readback "$3"
    new_version="$(current_version)"
    [ "$new_version" != "ABSENT" ] || fail "unable to read deployed Worker version"
    [ "$new_version" != "$baseline" ] || fail "active dedicated Worker version did not change"
    printf 'WATCHALONG_STATIC_RELEASE=PASS\n'
    printf 'BASELINE_VERSION=%s\n' "$baseline"
    printf 'NEW_VERSION=%s\n' "$new_version"
    printf 'FRONTEND_DEPLOY=NO\n'
    ;;
  smoke)
    [ "$#" -eq 2 ] || fail "usage: $0 smoke MANIFEST_SHA256"
    require_hex "$2" 64 "manifest SHA-256"
    readback "$2"
    ;;
  *)
    fail "first argument must be prepare, deploy, or smoke"
    ;;
esac
