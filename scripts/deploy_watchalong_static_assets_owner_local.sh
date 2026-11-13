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

validate_manifest() {
  manifest="$1"
  jq -e '
    .schema_version == "holoviewer-watchalong-manifest-v1" and
    (.event_count | type == "number") and
    .event_count > 0 and
    .event_count == (.events | length) and
    ([.events[].event_id] | unique | length) == .event_count and
    all(.events[];
      (.event_id | type == "string") and
      (.master_video_id == .event_id) and
      (.path == ("/data/watchalong/events/" + .event_id + ".json")) and
      (.sha256 | test("^[0-9a-f]{64}$"))
    )
  ' "$manifest" >/dev/null || fail "manifest inventory is malformed"
}

verify_candidate() {
  expected_head="$1"
  expected_manifest_sha="$2"
  repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
  cd "$repo_root"
  [ "$(git rev-parse HEAD)" = "$expected_head" ] || fail "checkout is not the reviewed candidate HEAD"
  [ -z "$(git status --porcelain --untracked-files=all)" ] || fail "candidate checkout is not clean"
  [ ! -e site/data/watchalong ] || fail "Watchalong data is still packaged by holoviewer-public"
  [ -f "$ASSET_ROOT/$MANIFEST_REL" ] || fail "dedicated manifest missing"
  [ "$(sha256_file "$ASSET_ROOT/$MANIFEST_REL")" = "$expected_manifest_sha" ] || fail "candidate manifest hash mismatch"
  validate_manifest "$ASSET_ROOT/$MANIFEST_REL"
  jq -r '.events[] | [.path,.sha256] | @tsv' "$ASSET_ROOT/$MANIFEST_REL" | while IFS="$(printf '\t')" read -r path expected; do
    require_hex "$expected" 64 "event SHA-256"
    file="$ASSET_ROOT/${path#/}"
    [ -f "$file" ] || fail "candidate event missing: $path"
    [ "$(sha256_file "$file")" = "$expected" ] || fail "candidate event hash mismatch: $path"
  done
  SOURCE_ROOT="${SOURCE_ROOT:-/Users/hsuhsunshun/Downloads/Hololive-PTT-Viewer}"
  APPROVED_SYNC_ROOT="${APPROVED_SYNC_ROOT:-}"
  [ -n "$APPROVED_SYNC_ROOT" ] || fail "APPROVED_SYNC_ROOT must point to exact reviewed authority checkout"
  authority_repo="$(git -C "$APPROVED_SYNC_ROOT" rev-parse --show-toplevel 2>/dev/null)" || fail "approved sync root is not in a Git checkout"
  [ -z "$(git -C "$authority_repo" status --porcelain --untracked-files=all)" ] || fail "approved sync authority checkout is not clean"
  APPROVED_AUTHORITY_HEAD="$(git -C "$authority_repo" rev-parse HEAD)"
  require_hex "$APPROVED_AUTHORITY_HEAD" 40 "approved sync authority HEAD"
  if git -C "$authority_repo" rev-parse --verify refs/remotes/origin/main >/dev/null 2>&1; then
    [ "$APPROVED_AUTHORITY_HEAD" = "$(git -C "$authority_repo" rev-parse refs/remotes/origin/main)" ] || fail "approved sync authority must equal the fetched private origin/main"
  else
    fail "private origin/main is unavailable; fetch it before release"
  fi
  python3 scripts/export_watchalong_assets.py --source-root "$SOURCE_ROOT" --approved-sync-root "$APPROVED_SYNC_ROOT" --output-root "$ASSET_ROOT/data/watchalong" --check
  python3 -B -m unittest -v test_watchalong_assets
}

fetch_remote_assets() {
  origin="$1"
  expected_manifest_sha="$2"
  output_root="$3"
  nonce="$4"
  mkdir -p "$output_root/events"
  curl -fsS --max-time 30 "$origin/$MANIFEST_REL?release=$nonce" -o "$output_root/manifest.json"
  [ "$(sha256_file "$output_root/manifest.json")" = "$expected_manifest_sha" ] || fail "remote manifest hash mismatch at $origin"
  validate_manifest "$output_root/manifest.json"
  jq -r '.events[] | [.event_id,.path,.sha256] | @tsv' "$output_root/manifest.json" | while IFS="$(printf '\t')" read -r event_id path expected; do
    out="$output_root/events/$event_id.json"
    curl -fsS --max-time 30 "$origin$path?release=$nonce" -o "$out"
    [ "$(sha256_file "$out")" = "$expected" ] || fail "remote event hash mismatch at $origin: $path"
  done
  cors="$(curl -fsSI --max-time 30 "$origin/$MANIFEST_REL?release=$nonce" | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2; exit}')"
  [ "$cors" = "*" ] || fail "CORS header mismatch at $origin"
}

readback() {
  expected_manifest_sha="$1"
  nonce="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="$(mktemp -d /private/tmp/watchalong-static-readback.XXXXXX)"
  fetch_remote_assets "$LIVE_ORIGIN" "$expected_manifest_sha" "$tmp" "$nonce"
  printf 'WATCHALONG_STATIC_READBACK=PASS origin=%s manifest_sha256=%s\n' "$LIVE_ORIGIN" "$expected_manifest_sha"
}

verify_additive_preview() {
  production_manifest="$1"
  candidate_manifest="$2"
  new_event_id="$(jq -n -r --slurpfile production "$production_manifest" --slurpfile candidate "$candidate_manifest" '
    ([ $candidate[0].events[].event_id ] - [ $production[0].events[].event_id ]) as $new
    | if ($new | length) == 1 then $new[0] else empty end
  ')"
  [ -n "$new_event_id" ] || fail "candidate must add exactly one new event"
  jq -e -n --slurpfile production "$production_manifest" --slurpfile candidate "$candidate_manifest" '
    ($candidate[0].events | map({key:.event_id,value:.sha256}) | from_entries) as $candidate_hashes
    | ($candidate[0].event_count == ($production[0].event_count + 1)) and
      all($production[0].events[]; . as $event | $candidate_hashes[$event.event_id] == $event.sha256)
  ' >/dev/null || fail "candidate is not an additive release or changed an existing event"
  printf '%s\n' "$new_event_id"
}

verify_resource_parity() {
  baseline_version="$1"
  candidate_version="$2"
  output_root="$3"
  npx --yes wrangler versions view "$baseline_version" --json --config "$WRANGLER_CONFIG" --name "$WORKER_NAME" >"$output_root/baseline-version.json"
  npx --yes wrangler versions view "$candidate_version" --json --config "$WRANGLER_CONFIG" --name "$WORKER_NAME" >"$output_root/candidate-version.json"
  jq -S '.resources' "$output_root/baseline-version.json" >"$output_root/baseline-resources.json"
  jq -S '.resources' "$output_root/candidate-version.json" >"$output_root/candidate-resources.json"
  cmp -s "$output_root/baseline-resources.json" "$output_root/candidate-resources.json" || fail "candidate Worker resources differ from Production"
}

release() {
  [ "${CONFIRM_WATCHALONG_RELEASE:-}" = "DEPLOY" ] || fail "set CONFIRM_WATCHALONG_RELEASE=DEPLOY for the one-command Production release"
  command -v jq >/dev/null 2>&1 || fail "jq is required"
  command -v npx >/dev/null 2>&1 || fail "npx is required"

  repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
  cd "$repo_root"
  expected_head="$(git rev-parse HEAD)"
  require_hex "$expected_head" 40 "candidate HEAD"
  if git rev-parse --verify refs/remotes/origin/main >/dev/null 2>&1; then
    [ "$expected_head" = "$(git rev-parse refs/remotes/origin/main)" ] || fail "release checkout must equal the fetched origin/main"
  else
    fail "origin/main is unavailable; fetch it before release"
  fi
  expected_manifest_sha="$(sha256_file "$ASSET_ROOT/$MANIFEST_REL")"
  require_hex "$expected_manifest_sha" 64 "manifest SHA-256"

  # This is the only source/export/test pass. Preview and Production stages
  # verify the already-uploaded bytes instead of rerunning the same tests.
  verify_candidate "$expected_head" "$expected_manifest_sha"

  baseline_version="$(current_version)"
  [ "$baseline_version" != "ABSENT" ] || fail "unable to lock the active Production version"
  work="$(mktemp -d /private/tmp/watchalong-static-release.XXXXXX)"
  nonce="$(date -u +%Y%m%dT%H%M%SZ)"
  curl -fsS --max-time 30 "$LIVE_ORIGIN/$MANIFEST_REL?baseline=$nonce" -o "$work/production-manifest.json"
  validate_manifest "$work/production-manifest.json"
  baseline_manifest_sha="$(sha256_file "$work/production-manifest.json")"

  short_head="$(printf '%s' "$expected_head" | cut -c1-12)"
  upload_log="$work/upload.log"
  npx --yes wrangler versions upload \
    --config "$WRANGLER_CONFIG" \
    --name "$WORKER_NAME" \
    --preview-alias "watchalong-$short_head" \
    --message "Watchalong additive release $expected_head" >"$upload_log" 2>&1
  cat "$upload_log"
  candidate_version="$(awk -F': ' '/Worker Version ID:/{print $2; exit}' "$upload_log" | tr -d '\r')"
  [ -n "$candidate_version" ] || fail "unable to parse uploaded candidate version"
  preview_origin="https://${candidate_version%%-*}-$WORKER_NAME.singlebagel.workers.dev"

  [ "$(current_version)" = "$baseline_version" ] || fail "Production changed while the zero-traffic candidate was uploading"
  verify_resource_parity "$baseline_version" "$candidate_version" "$work"
  fetch_remote_assets "$preview_origin" "$expected_manifest_sha" "$work/preview" "preview-$nonce"
  target_event_id="$(verify_additive_preview "$work/production-manifest.json" "$work/preview/manifest.json")"
  [ "$(current_version)" = "$baseline_version" ] || fail "Production changed during preview verification"

  npx --yes wrangler versions deploy "$candidate_version@100%" \
    --config "$WRANGLER_CONFIG" \
    --name "$WORKER_NAME" \
    --message "Watchalong $target_event_id; source $expected_head; rollback $baseline_version" \
    -y

  if [ "$(current_version)" != "$candidate_version" ] || ! (readback "$expected_manifest_sha"); then
    printf 'Post-cutover verification failed; restoring %s\n' "$baseline_version" >&2
    if npx --yes wrangler versions deploy "$baseline_version@100%" \
      --config "$WRANGLER_CONFIG" \
      --name "$WORKER_NAME" \
      --message "Automatic rollback after failed Watchalong readback" \
      -y; then
      fail "release rolled back after failed Production verification"
    fi
    fail "Production verification and automatic rollback both failed; manual recovery is required"
  fi

  printf 'WATCHALONG_STATIC_RELEASE=PASS\n'
  printf 'TARGET_EVENT_ID=%s\n' "$target_event_id"
  printf 'CANDIDATE_HEAD=%s\n' "$expected_head"
  printf 'APPROVED_AUTHORITY_HEAD=%s\n' "$APPROVED_AUTHORITY_HEAD"
  printf 'MANIFEST_SHA256=%s\n' "$expected_manifest_sha"
  printf 'BASELINE_MANIFEST_SHA256=%s\n' "$baseline_manifest_sha"
  printf 'BASELINE_VERSION=%s\n' "$baseline_version"
  printf 'NEW_VERSION=%s\n' "$candidate_version"
  printf 'RESOURCE_PARITY=PASS\n'
  printf 'PREVIEW_ADDITIVE_PARITY=PASS\n'
  printf 'FRONTEND_DEPLOY=NO\n'
  printf 'ROLLBACK_COMMAND=npx --yes wrangler versions deploy %s@100%% --config %s --name %s -y\n' \
    "$baseline_version" "$WRANGLER_CONFIG" "$WORKER_NAME"
}

mode="${1:-}"
case "$mode" in
  release)
    [ "$#" -eq 1 ] || fail "usage: $0 release"
    release
    ;;
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
  help|-h|--help)
    printf 'Usage:\n'
    printf '  CONFIRM_WATCHALONG_RELEASE=DEPLOY APPROVED_SYNC_ROOT=/clean/private/watchalong_approved_sync %s release\n' "$0"
    printf '  %s prepare EXPECTED_HEAD MANIFEST_SHA256\n' "$0"
    printf '  %s smoke MANIFEST_SHA256\n' "$0"
    ;;
  *)
    fail "first argument must be release, prepare, deploy, smoke, or help"
    ;;
esac
