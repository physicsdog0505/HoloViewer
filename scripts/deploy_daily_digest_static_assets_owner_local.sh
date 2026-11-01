#!/bin/sh
set -eu

WORKER_NAME="holoviewer-daily-digest-static-assets"
WRANGLER_CONFIG="cloudflare/daily-digest-static-assets.wrangler.json"
ASSET_ROOT="daily-digest-static"
LIVE_ORIGIN="https://holoviewer-daily-digest-static-assets.singlebagel.workers.dev"

fail(){ printf 'Daily Digest Static Assets release: %s\n' "$*" >&2; exit 1; }
sha256_file(){ if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"|awk '{print $1}'; else sha256sum "$1"|awk '{print $1}'; fi; }
require_hex(){ value="$1"; length="$2"; [ "${#value}" -eq "$length" ]||fail "invalid hexadecimal length"; case "$value" in *[!0-9a-f]*) fail "expected lowercase hexadecimal";; esac; }

current_version(){
  tmp="$(mktemp /private/tmp/daily-digest-static-status.XXXXXX)"
  if npx --yes wrangler deployments status --config "$WRANGLER_CONFIG" --name "$WORKER_NAME" >"$tmp" 2>&1; then
    awk '/Version\(s\):/{print $3; exit}' "$tmp"
  else
    printf 'ABSENT\n'
  fi
  rm -f "$tmp"
}

verify_candidate(){
  expected_head="$1"
  repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"; cd "$repo_root"
  [ "$(git rev-parse HEAD)" = "$expected_head" ]||fail "checkout is not reviewed candidate HEAD"

  dirty="$(git status --porcelain --untracked-files=all | grep -Ev '^.. daily-digest-static/data/daily-digest/months/[0-9]{4}-[0-9]{2}\.json$' || true)"
  [ -z "$dirty" ]||fail "candidate checkout has non-Daily-Digest runtime drift"

  [ ! -e site/data/daily-digest ]||fail "Daily Digest data must not be packaged by holoviewer-public"
  root="$ASSET_ROOT/data/daily-digest/months"
  [ -d "$root" ]||fail "month shard root missing"
  find "$root" -type f -name '*.json' | while read -r file; do
    base="$(basename "$file" .json)"
    jq -e --arg month "$base" '
      .schema_version == 1 and
      .kind == "holodocchi.daily_digest_month" and
      .month == $month and
      (.days | type == "object") and
      (all(.days | to_entries[];
        (.key | startswith($month + "-")) and
        (.value.schema_version == 1) and
        (.value.kind == "holodocchi.daily_digest") and
        (.value.target_day == .key)
      ))
    ' "$file" >/dev/null || fail "invalid month shard: $file"
  done
}

readback(){
  tmp="$(mktemp -d /private/tmp/daily-digest-static-readback.XXXXXX)"
  find "$ASSET_ROOT/data/daily-digest/months" -type f -name '*.json' | while read -r file; do
    rel="${file#$ASSET_ROOT/}"
    out="$tmp/$(basename "$file")"
    curl -fsS --max-time 30 "$LIVE_ORIGIN/$rel?release=$(date +%s)" -o "$out"
    [ "$(sha256_file "$out")" = "$(sha256_file "$file")" ]||fail "production month shard mismatch: $rel"
  done
  printf 'DAILY_DIGEST_STATIC_READBACK=PASS\n'
}

mode="${1:-}"
case "$mode" in
  prepare)
    [ "$#" -eq 2 ]||fail "usage: $0 prepare EXPECTED_HEAD"
    require_hex "$2" 40
    verify_candidate "$2"
    baseline="$(current_version)"
    printf 'DAILY_DIGEST_STATIC_PREPARE=PASS\n'
    printf 'CANDIDATE_HEAD=%s\n' "$2"
    printf 'BASELINE_VERSION=%s\n' "$baseline"
    printf 'PRODUCTION_MUTATION=NO\n'
    ;;
  verify)
    [ "$#" -eq 2 ]||fail "usage: $0 verify EXPECTED_HEAD"
    require_hex "$2" 40
    verify_candidate "$2"
    current="$(current_version)"
    [ "$current" != "ABSENT" ]||fail "dedicated Worker is absent"
    readback
    printf 'DAILY_DIGEST_STATIC_VERIFY=PASS\n'
    printf 'CURRENT_VERSION=%s\n' "$current"
    printf 'PRODUCTION_MUTATION=NO\n'
    printf 'FRONTEND_DEPLOY=NO\n'
    ;;
  deploy)
    [ "$#" -eq 3 ]||fail "usage: $0 deploy EXPECTED_HEAD EXPECTED_BASELINE_VERSION"
    require_hex "$2" 40
    verify_candidate "$2"
    baseline="$(current_version)"
    [ "$baseline" = "$3" ]||fail "dedicated Worker baseline changed since Owner approval"
    npx --yes wrangler deploy --config "$WRANGLER_CONFIG" --name "$WORKER_NAME"
    readback
    new_version="$(current_version)"
    [ "$new_version" != "ABSENT" ]||fail "unable to read deployed Worker version"
    printf 'DAILY_DIGEST_STATIC_RELEASE=PASS\n'
    printf 'BASELINE_VERSION=%s\n' "$baseline"
    printf 'NEW_VERSION=%s\n' "$new_version"
    printf 'FRONTEND_DEPLOY=NO\n'
    ;;
  *)
    fail "first argument must be prepare, verify, or deploy"
    ;;
esac
