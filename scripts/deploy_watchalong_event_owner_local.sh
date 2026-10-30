#!/bin/sh
set -eu

VIDEO_ONE_ID="jqJb0qnueDo"
VIDEO_TWO_ID="x7bMoyNWaEE"
LIVE_ORIGIN="https://holodocchi.com"
EVENT_ONE_REL="site/data/watchalong/events/${VIDEO_ONE_ID}.json"
EVENT_TWO_REL="site/data/watchalong/events/${VIDEO_TWO_ID}.json"
MANIFEST_REL="site/data/watchalong/manifest.json"

fail() {
  printf 'Pekora Watchalong deploy: %s\n' "$*" >&2
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
  expected_event_one_sha="$1"
  expected_event_two_sha="$2"
  expected_manifest_sha="$3"
  nonce="$4"
  temporary_dir="$(mktemp -d /private/tmp/holoviewer-pekora-watchalong-readback.XXXXXX)"
  live_manifest="$temporary_dir/manifest.json"
  live_event_one="$temporary_dir/event-one.json"
  live_event_two="$temporary_dir/event-two.json"
  live_viewer="$temporary_dir/viewer.html"

  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/manifest.json?pekora-watchalong=${nonce}" -o "$live_manifest"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${VIDEO_ONE_ID}.json?pekora-watchalong=${nonce}" -o "$live_event_one"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${VIDEO_TWO_ID}.json?pekora-watchalong=${nonce}" -o "$live_event_two"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/watchalong-viewer/?watchalong_event=${VIDEO_ONE_ID}&pekora-watchalong=${nonce}" -o "$live_viewer"

  [ "$(sha256_file "$live_manifest")" = "$expected_manifest_sha" ] || fail "production manifest hash mismatch"
  live_events_tsv="$temporary_dir/live-events.tsv"
  jq -r '.events[] | [.event_id, .sha256] | @tsv' "$live_manifest" >"$live_events_tsv"
  while IFS="$(printf '\t')" read -r event_id event_sha; do
    require_hex "$event_sha" 64 "manifest event SHA-256"
    live_event_path="$temporary_dir/live-${event_id}.json"
    curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${event_id}.json?pekora-watchalong=${nonce}" -o "$live_event_path"
    [ "$(sha256_file "$live_event_path")" = "$event_sha" ] || fail "production event hash mismatch: $event_id"
  done <"$live_events_tsv"
  [ "$(sha256_file "$live_event_one")" = "$expected_event_one_sha" ] || fail "production first event hash mismatch"
  [ "$(sha256_file "$live_event_two")" = "$expected_event_two_sha" ] || fail "production second event hash mismatch"
  jq -e --arg first "$VIDEO_ONE_ID" --arg second "$VIDEO_TWO_ID" '
    .event_count == 6 and
    any(.events[]; .event_id == $first and .master_video_id == $first and .cue_count == 449) and
    any(.events[]; .event_id == $second and .master_video_id == $second and .cue_count == 888)
  ' "$live_manifest" >/dev/null || fail "production manifest registration mismatch"
  jq -e --arg video "$VIDEO_ONE_ID" '
    .schema_version == "holoviewer-watchalong-event-v1" and
    .event_id == $video and .master_video_id == $video and
    .playlist_start_index == 1 and
    (.source_video_ids | length) == 2 and
    (.segments | map(.host_start_ms)) == [586760,2073480] and
    (.subtitles | length) == 449 and
    .artifacts.transcript.transcript_id == "800774361d14746957549eb2d885fe1eee6f40b15e467307b6f0aea852be25dd" and
    .artifacts.transcript.content_hash == "d4321ddc1bcac20aa8c6bc04759c8ca461ffc0ac05dbee26ea88496365e0dae6" and
    .artifacts.translation.artifact_id == "141898ea22cd37595160c64d3899f8202916e1126f066c5193b8dd0681e7b6c5" and
    .artifacts.translation.translated_cues == 449 and
    .artifacts.sync.status == "PRESENT"
  ' "$live_event_one" >/dev/null || fail "production first event identity/readback mismatch"
  jq -e --arg video "$VIDEO_TWO_ID" '
    .schema_version == "holoviewer-watchalong-event-v1" and
    .event_id == $video and .master_video_id == $video and
    .playlist_start_index == 2 and
    (.source_video_ids | length) == 4 and
    (.segments | map(.host_start_ms)) == [124840,1620240,3066119,4552520] and
    (.subtitles | length) == 888 and
    .artifacts.transcript.transcript_id == "8bef48719c6fdeb9fda78bed0a56f58a6dc4fd7d144c40f1fea010d758488e17" and
    .artifacts.transcript.content_hash == "450573590110d9563829c85cc04fa0b488c71c5ee2969c48982f293fbad1c2dd" and
    .artifacts.translation.artifact_id == "9868c1c078edecd96e487fd914fb8e7842de38838dc2000ebee8e16f13741360" and
    .artifacts.translation.translated_cues == 888 and
    .artifacts.sync.status == "PRESENT"
  ' "$live_event_two" >/dev/null || fail "production second event identity/readback mismatch"
  grep -F '/assets/watchalong-standalone.js' "$live_viewer" >/dev/null || fail "production Watchalong viewer route is incomplete"
  printf 'PRODUCTION_READBACK=PASS origin=%s video_ids=%s,%s manifest_sha256=%s event_sha256=%s,%s\n' \
    "$LIVE_ORIGIN" "$VIDEO_ONE_ID" "$VIDEO_TWO_ID" "$expected_manifest_sha" "$expected_event_one_sha" "$expected_event_two_sha"
}

mode="${1:-}"
case "$mode" in
  smoke)
    [ "$#" -eq 4 ] || fail "usage: $0 smoke EVENT_ONE_SHA256 EVENT_TWO_SHA256 MANIFEST_SHA256"
    require_hex "$2" 64 "event SHA-256"
    require_hex "$3" 64 "event SHA-256"
    require_hex "$4" 64 "manifest SHA-256"
    readback "$2" "$3" "$4" "smoke-$(date -u +%Y%m%dT%H%M%SZ)"
    exit 0
    ;;
  deploy)
    [ "$#" -eq 7 ] || fail "usage: $0 deploy EXPECTED_HEAD EVENT_ONE_SHA256 EVENT_TWO_SHA256 MANIFEST_SHA256 BASELINE_VERSION_ID BASELINE_MANIFEST_SHA256"
    ;;
  *)
    fail "first argument must be deploy or smoke"
    ;;
esac

expected_head="$2"
expected_event_one_sha="$3"
expected_event_two_sha="$4"
expected_manifest_sha="$5"
expected_baseline_version="$6"
expected_baseline_manifest_sha="$7"
require_hex "$expected_head" 40 "candidate HEAD"
require_hex "$expected_event_one_sha" 64 "event SHA-256"
require_hex "$expected_event_two_sha" 64 "event SHA-256"
require_hex "$expected_manifest_sha" 64 "manifest SHA-256"
require_hex "$expected_baseline_manifest_sha" 64 "baseline manifest SHA-256"

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
[ "$(git rev-parse HEAD)" = "$expected_head" ] || fail "checkout is not the reviewed candidate HEAD"
[ -z "$(git status --porcelain --untracked-files=all)" ] || fail "candidate checkout is not clean"
[ "$(sha256_file "$EVENT_ONE_REL")" = "$expected_event_one_sha" ] || fail "candidate first event hash mismatch"
[ "$(sha256_file "$EVENT_TWO_REL")" = "$expected_event_two_sha" ] || fail "candidate second event hash mismatch"
[ "$(sha256_file "$MANIFEST_REL")" = "$expected_manifest_sha" ] || fail "candidate manifest hash mismatch"

python3 scripts/export_watchalong_assets.py \
  --source-root /Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer \
  --output-root site/data/watchalong \
  --check
python3 -B -m unittest -v test_watchalong_assets test_public_smoke

temporary_dir="$(mktemp -d /private/tmp/holoviewer-pekora-watchalong-preflight.XXXXXX)"
baseline_manifest="$temporary_dir/manifest.json"
baseline_event_one="$temporary_dir/${VIDEO_ONE_ID}.json"
baseline_event_two="$temporary_dir/${VIDEO_TWO_ID}.json"
deployment_status="$temporary_dir/deployment-status.txt"
curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/manifest.json?pekora-watchalong=baseline-${expected_head}" -o "$baseline_manifest"
[ "$(sha256_file "$baseline_manifest")" = "$expected_baseline_manifest_sha" ] || fail "production manifest changed since packet preparation"
baseline_events_tsv="$temporary_dir/baseline-events.tsv"
jq -r '.events[] | [.event_id, .sha256] | @tsv' "$baseline_manifest" >"$baseline_events_tsv"
while IFS="$(printf '\t')" read -r event_id event_sha; do
  require_hex "$event_sha" 64 "baseline manifest event SHA-256"
  baseline_event_path="$temporary_dir/baseline-${event_id}.json"
  curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${event_id}.json?pekora-watchalong=baseline-${expected_head}" -o "$baseline_event_path"
  [ "$(sha256_file "$baseline_event_path")" = "$event_sha" ] || fail "Production baseline event hash mismatch: $event_id"
done <"$baseline_events_tsv"
jq -e --arg first "$VIDEO_ONE_ID" --arg second "$VIDEO_TWO_ID" \
  '.event_count == 6 and
   any(.events[]; .event_id == $first and .cue_count == 449 and .source_count == 2 and .sha256 == "d3b030036931ac8ce95435bafa721d33f57323bb61e33db2b694377cbe7f182a") and
   any(.events[]; .event_id == $second and .cue_count == 888 and .source_count == 3 and .sha256 == "ff12e04eea458f096558a033ed5d2d44646ddd1e49c78ea067028553eef28db8")' \
  "$baseline_manifest" >/dev/null || fail "Production target baseline identity mismatch"
curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${VIDEO_ONE_ID}.json?pekora-watchalong=baseline-${expected_head}" -o "$baseline_event_one"
curl -fsS --max-time 30 "${LIVE_ORIGIN}/data/watchalong/events/${VIDEO_TWO_ID}.json?pekora-watchalong=baseline-${expected_head}" -o "$baseline_event_two"
[ "$(sha256_file "$baseline_event_one")" = "d3b030036931ac8ce95435bafa721d33f57323bb61e33db2b694377cbe7f182a" ] || fail "Production first event baseline hash mismatch"
[ "$(sha256_file "$baseline_event_two")" = "ff12e04eea458f096558a033ed5d2d44646ddd1e49c78ea067028553eef28db8" ] || fail "Production second event baseline hash mismatch"

npx --yes wrangler deployments status --config cloudflare/wrangler.json --name holoviewer-public >"$deployment_status"
baseline_version="$(awk '/Version\(s\):/{print $3; exit}' "$deployment_status")"
[ "$baseline_version" = "$expected_baseline_version" ] || fail "production Worker baseline changed since packet preparation"

backup_root="/Users/hsuhsunshun/Downloads/HoloViewer-deploy-backups"
backup_dir="$backup_root/pekora-watchalong-$(date -u +%Y%m%dT%H%M%SZ)-$baseline_version"
mkdir -p "$backup_dir"
cp "$baseline_manifest" "$backup_dir/manifest.json"
cp "$baseline_event_one" "$backup_dir/${VIDEO_ONE_ID}.json"
cp "$baseline_event_two" "$backup_dir/${VIDEO_TWO_ID}.json"
cp "$deployment_status" "$backup_dir/deployment-status.txt"
cp cloudflare/wrangler.json "$backup_dir/wrangler.json"
printf 'candidate_head=%s\nevent_one_sha256=%s\nevent_two_sha256=%s\nmanifest_sha256=%s\nbaseline_version=%s\nbaseline_manifest_sha256=%s\n' \
  "$expected_head" "$expected_event_one_sha" "$expected_event_two_sha" "$expected_manifest_sha" "$baseline_version" "$expected_baseline_manifest_sha" \
  >"$backup_dir/packet.txt"

npx --yes wrangler deploy --config cloudflare/wrangler.json --name holoviewer-public
readback "$expected_event_one_sha" "$expected_event_two_sha" "$expected_manifest_sha" "$expected_head"

post_status="$backup_dir/post-deployment-status.txt"
npx --yes wrangler deployments status --config cloudflare/wrangler.json --name holoviewer-public >"$post_status"
post_version="$(awk '/Version\(s\):/{print $3; exit}' "$post_status")"
[ -n "$post_version" ] || fail "unable to read deployed Worker version"
[ "$post_version" != "$baseline_version" ] || fail "Cloudflare did not activate a new static-assets version"

printf 'WATCHALONG_SMOKE=PASS video_ids=%s,%s cue_counts=449,888 source_counts=2,4\n' "$VIDEO_ONE_ID" "$VIDEO_TWO_ID"
printf 'BACKUP_DIR=%s\n' "$backup_dir"
printf 'ROLLBACK_TARGET=%s\n' "$baseline_version"
printf 'ROLLBACK_COMMAND=cd %s && npx --yes wrangler rollback %s --config cloudflare/wrangler.json --name holoviewer-public\n' \
  "$repo_root" "$baseline_version"
