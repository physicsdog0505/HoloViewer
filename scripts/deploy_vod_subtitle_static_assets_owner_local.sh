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
 expected_head="$1"; month="$2"; expected_sha="$3"
 repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"; cd "$repo_root"
 [ "$(git rev-parse HEAD)" = "$expected_head" ]||fail "checkout is not reviewed candidate HEAD"
 [ -z "$(git status --porcelain --untracked-files=all)" ]||fail "candidate checkout is not clean"
 case "$month" in ????-??) ;; *) fail "month must use YYYY-MM";; esac
 manifest="$ASSET_ROOT/data/subtitles/manifests/$month.json"
 [ -f "$manifest" ]||fail "month manifest missing"
 [ "$(sha256_file "$manifest")" = "$expected_sha" ]||fail "month manifest hash mismatch"
 jq -e '.schema_version=="holodocchi-vod-subtitle-manifest-v1" and (.complete|type)=="boolean" and .video_count==(.videos|length)' "$manifest" >/dev/null||fail "month manifest contract mismatch"
 jq -r '.videos[]|[.path,.sha256]|@tsv' "$manifest"|while IFS="$(printf '\t')" read -r path expected; do
  case "$path" in /data/subtitles/videos/*.json) ;; *) fail "video path escapes General VOD namespace";; esac
  require_hex "$expected" 64
  file="$ASSET_ROOT/${path#/}"; [ -f "$file" ]||fail "video asset missing: $path"
  [ "$(sha256_file "$file")" = "$expected" ]||fail "video asset hash mismatch: $path"
 done
 [ ! -e "$ASSET_ROOT/data/watchalong" ]||fail "Watchalong content is forbidden in General VOD target"
}

mode="${1:-}"
case "$mode" in
 prepare)
  [ "$#" -eq 4 ]||fail "usage: $0 prepare EXPECTED_HEAD YYYY-MM MANIFEST_SHA256"
  require_hex "$2" 40; require_hex "$4" 64; verify_candidate "$2" "$3" "$4"
  printf 'VOD_SUBTITLE_STATIC_PREPARE=PASS\nPRODUCTION_MUTATION=NO\n'
  ;;
 deploy)
  [ "$#" -eq 4 ]||fail "usage: $0 deploy EXPECTED_HEAD YYYY-MM MANIFEST_SHA256"
  require_hex "$2" 40; require_hex "$4" 64; verify_candidate "$2" "$3" "$4"
  npx --yes wrangler deploy --config "$WRANGLER_CONFIG" --name "$WORKER_NAME"
  ;;
 smoke)
  [ "$#" -eq 3 ]||fail "usage: $0 smoke YYYY-MM MANIFEST_SHA256"
  require_hex "$3" 64
  tmp="$(mktemp /private/tmp/vod-subtitle-manifest.XXXXXX)"
  curl -fsS --max-time 30 "$LIVE_ORIGIN/data/subtitles/manifests/$2.json" -o "$tmp"
  [ "$(sha256_file "$tmp")" = "$3" ]||fail "deployed manifest hash mismatch"
  rm -f "$tmp"; printf 'VOD_SUBTITLE_STATIC_READBACK=PASS\n'
  ;;
 *) fail "first argument must be prepare, deploy, or smoke";;
esac
