#!/bin/sh
set -eu

VIDEO_ID="t8q3XEmK0aM"
LIVE_ORIGIN="https://holodocchi.com"
EVENT_REL="site/data/watchalong/events/${VIDEO_ID}.json"
MANIFEST_REL="site/data/watchalong/manifest.json"

fail() {
  printf 'issue441 deploy: %s\n' "$*" >&2
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
  case "$value" in
    *[!0-9a-f]*) fail "$label must be lowercase hexadecimal" ;;
  esac
}

readback() {
  expected_event_sha="$1"
  expected_manifest_sha="$2"
  nonce="$3"
  temporary_dir="$(mktemp -d /private/tmp/holoviewer-issue441-readback.XXXXXX)"
  live_manifest="$temporary_dir/manifest.json"
  live_event="$temporary_dir/event.json"
  live_viewer="$temporary_dir/viewer.html"

  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/manifest.json?issue441=${nonce}" -o "$live_manifest"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${VIDEO_ID}.json?issue441=${nonce}" -o "$live_event"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/watchalong-viewer/?watchalong_event=${VIDEO_ID}&issue441=${nonce}" -o "$live_viewer"

  [ "$(sha256_file "$live_manifest")" = "$expected_manifest_sha" ] || fail "production manifest hash mismatch"
  [ "$(sha256_file "$live_event")" = "$expected_event_sha" ] || fail "production event hash mismatch"
  jq -e --arg video "$VIDEO_ID" '
    .event_count == 4 and
    any(.events[]; .event_id == $video and .master_video_id == $video and .cue_count == 1367)
  ' "$live_manifest" >/dev/null || fail "production manifest registration mismatch"
  jq -e --arg video "$VIDEO_ID" '
    .schema_version == "holoviewer-watchalong-event-v1" and
    .event_id == $video and .master_video_id == $video and
    .playlist_start_index == 19 and
    (.source_video_ids | length) == 6 and
    (.segments | map(.host_start_ms)) == [727000,2195000,3683000,5170000,6691000,8233000] and
    (.segments | map(.host_start_ms) | index(8610000)) == null and
    (.subtitles | length) == 1367 and
    .artifacts.transcript.transcript_id == "178aae1474d868fb3800c451eb75ce29de0b26dd8d7f32bf66a62c99f59b108a" and
    .artifacts.transcript.content_hash == "c71004b6d0d4b888b841f97862d5e0856035c7c09fe039ac4c0844109c72f06d" and
    .artifacts.translation.artifact_id == "a9376309a49b753a1d57326b818d9ec13e12ab3caaf57aaf3d63b4005676b2c6" and
    .artifacts.translation.translated_cues == 1367 and
    .artifacts.sync.status == "PRESENT"
  ' "$live_event" >/dev/null || fail "production event identity/readback mismatch"
  grep -F '/assets/watchalong-standalone.js' "$live_viewer" >/dev/null || fail "production Watchalong viewer route is incomplete"
  printf 'PRODUCTION_READBACK=PASS origin=%s video_id=%s manifest_sha256=%s event_sha256=%s\n' \
    "$LIVE_ORIGIN" "$VIDEO_ID" "$expected_manifest_sha" "$expected_event_sha"
}

mode="${1:-}"
case "$mode" in
  smoke)
    [ "$#" -eq 3 ] || fail "usage: $0 smoke EVENT_SHA256 MANIFEST_SHA256"
    require_hex "$2" 64 "event SHA-256"
    require_hex "$3" 64 "manifest SHA-256"
    readback "$2" "$3" "smoke-$(date -u +%Y%m%dT%H%M%SZ)"
    exit 0
    ;;
  deploy)
    [ "$#" -eq 6 ] || fail "usage: $0 deploy EXPECTED_HEAD EVENT_SHA256 MANIFEST_SHA256 BASELINE_VERSION_ID BASELINE_MANIFEST_SHA256"
    ;;
  *)
    fail "first argument must be deploy or smoke"
    ;;
esac

expected_head="$2"
expected_event_sha="$3"
expected_manifest_sha="$4"
expected_baseline_version="$5"
expected_baseline_manifest_sha="$6"
require_hex "$expected_head" 40 "candidate HEAD"
require_hex "$expected_event_sha" 64 "event SHA-256"
require_hex "$expected_manifest_sha" 64 "manifest SHA-256"
require_hex "$expected_baseline_manifest_sha" 64 "baseline manifest SHA-256"

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
[ "$(git rev-parse HEAD)" = "$expected_head" ] || fail "checkout is not the reviewed candidate HEAD"
[ -z "$(git status --porcelain --untracked-files=all)" ] || fail "candidate checkout is not clean"
[ "$(sha256_file "$EVENT_REL")" = "$expected_event_sha" ] || fail "candidate event hash mismatch"
[ "$(sha256_file "$MANIFEST_REL")" = "$expected_manifest_sha" ] || fail "candidate manifest hash mismatch"

python3 scripts/export_watchalong_assets.py \
  --source-root /Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer \
  --output-root site/data/watchalong \
  --check
python3 -B -m unittest -v test_watchalong_assets test_public_smoke

temporary_dir="$(mktemp -d /private/tmp/holoviewer-issue441-preflight.XXXXXX)"
baseline_manifest="$temporary_dir/manifest.json"
deployment_status="$temporary_dir/deployment-status.txt"
curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/manifest.json?issue441=baseline-${expected_head}" -o "$baseline_manifest"
[ "$(sha256_file "$baseline_manifest")" = "$expected_baseline_manifest_sha" ] || fail "production manifest changed since packet preparation"
jq -e --arg video "$VIDEO_ID" 'all(.events[]; .event_id != $video)' "$baseline_manifest" >/dev/null || fail "target video is already registered in Production"

npx --yes wrangler deployments status --config cloudflare/wrangler.json --name holoviewer-public >"$deployment_status"
baseline_version="$(awk '/Version\(s\):/{print $3; exit}' "$deployment_status")"
[ "$baseline_version" = "$expected_baseline_version" ] || fail "production Worker baseline changed since packet preparation"

backup_root="/Users/hsuhsunshun/Downloads/HoloViewer-deploy-backups"
backup_dir="$backup_root/issue441-$(date -u +%Y%m%dT%H%M%SZ)-$baseline_version"
mkdir -p "$backup_dir"
cp "$baseline_manifest" "$backup_dir/manifest.json"
cp "$deployment_status" "$backup_dir/deployment-status.txt"
cp cloudflare/wrangler.json "$backup_dir/wrangler.json"
printf 'ABSENT from the authoritative Production manifest before Issue #441 deployment\n' \
  >"$backup_dir/${VIDEO_ID}.absent"
printf 'candidate_head=%s\nevent_sha256=%s\nmanifest_sha256=%s\nbaseline_version=%s\nbaseline_manifest_sha256=%s\n' \
  "$expected_head" "$expected_event_sha" "$expected_manifest_sha" "$baseline_version" "$expected_baseline_manifest_sha" \
  >"$backup_dir/packet.txt"

npx --yes wrangler deploy --config cloudflare/wrangler.json --name holoviewer-public
readback "$expected_event_sha" "$expected_manifest_sha" "$expected_head"

post_status="$backup_dir/post-deployment-status.txt"
npx --yes wrangler deployments status --config cloudflare/wrangler.json --name holoviewer-public >"$post_status"
post_version="$(awk '/Version\(s\):/{print $3; exit}' "$post_status")"
[ -n "$post_version" ] || fail "unable to read deployed Worker version"
[ "$post_version" != "$baseline_version" ] || fail "Cloudflare did not activate a new static-assets version"

printf 'WATCHALONG_SMOKE=PASS video_id=%s cue_count=1367 source_count=6\n' "$VIDEO_ID"
printf 'BACKUP_DIR=%s\n' "$backup_dir"
printf 'ROLLBACK_TARGET=%s\n' "$baseline_version"
printf 'ROLLBACK_COMMAND=cd %s && npx --yes wrangler rollback %s --config cloudflare/wrangler.json --name holoviewer-public\n' \
  "$repo_root" "$baseline_version"
