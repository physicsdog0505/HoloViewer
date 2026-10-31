#!/bin/sh
set -eu

WORKER_NAME="holoviewer-vod-subtitles-static-assets"
WRANGLER_CONFIG="cloudflare/vod-subtitle-static-assets.wrangler.json"
ASSET_ROOT="vod-subtitles-static"
LIVE_ORIGIN="https://holoviewer-vod-subtitles-static-assets.singlebagel.workers.dev"

fail(){ printf 'VOD Subtitle Static Assets release: %s\n' "$*" >&2; exit 1; }
sha256_file(){ if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"|awk '{print $1}'; else sha256sum "$1"|awk '{print $1}'; fi; }
require_hex(){ value="$1"; length="$2"; [ "${#value}" -eq "$length" ]||fail "invalid hexadecimal length"; case "$value" in *[!0-9a-f]*) fail "expected lowercase hexadecimal";; esac; }

verify_candidate(){
 expected_head="$1"; receipts_root="$2"; catalog_root="$3"
 repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"; cd "$repo_root"
 [ "$(git rev-parse HEAD)" = "$expected_head" ]||fail "checkout is not reviewed candidate HEAD"
 python3 -B vod_subtitle_publisher.py validate \
   --candidate-root "$ASSET_ROOT" \
   --receipts-root "$receipts_root" \
   --catalog-root "$catalog_root" >/dev/null \
   || fail "atomic subtitle candidate validation failed"
 [ -f "$ASSET_ROOT/data/subtitles/index.json" ]||fail "global availability index missing"
 [ -d "$ASSET_ROOT/data/subtitles/manifests/by-vod-month" ]||fail "by-VOD-month indexes missing"
 if find "$ASSET_ROOT/data/subtitles/manifests" -maxdepth 1 -type f -name '????-??.json' | grep -q .; then
   fail "old manifests/<YYYY-MM>.json contract is forbidden"
 fi
 [ ! -e "$ASSET_ROOT/data/subtitles/receipts" ]||fail "private receipts exposed in public assets"
 [ ! -e "$ASSET_ROOT/data/watchalong" ]||fail "Watchalong content is forbidden in General VOD target"
}

mode="${1:-}"
case "$mode" in
 prepare)
  [ "$#" -eq 4 ]||fail "usage: $0 prepare EXPECTED_HEAD PRIVATE_RECEIPTS_ROOT VOD_CATALOG_ROOT"
  require_hex "$2" 40; verify_candidate "$2" "$3" "$4"
  printf 'VOD_SUBTITLE_STATIC_PREPARE=PASS\nPRODUCTION_MUTATION=NO\n'
  ;;
 deploy)
  [ "$#" -eq 4 ]||fail "usage: $0 deploy EXPECTED_HEAD PRIVATE_RECEIPTS_ROOT VOD_CATALOG_ROOT"
  require_hex "$2" 40; verify_candidate "$2" "$3" "$4"
  npx --yes wrangler deploy --config "$WRANGLER_CONFIG" --name "$WORKER_NAME"
  ;;
 smoke)
  [ "$#" -eq 2 ]||fail "usage: $0 smoke INDEX_SHA256"
  require_hex "$2" 64
  tmp="$(mktemp /private/tmp/vod-subtitle-index.XXXXXX)"
  curl -fsS --max-time 30 "$LIVE_ORIGIN/data/subtitles/index.json" -o "$tmp"
  [ "$(sha256_file "$tmp")" = "$2" ]||fail "deployed availability index hash mismatch"
  rm -f "$tmp"; printf 'VOD_SUBTITLE_STATIC_READBACK=PASS\n'
  ;;
 *) fail "first argument must be prepare, deploy, or smoke";;
esac
