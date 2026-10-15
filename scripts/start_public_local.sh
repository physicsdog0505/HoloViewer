#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PORT="${HOLOVIEWER_PUBLIC_LOCAL_PORT:-8788}"

cd "$ROOT"

echo "HoloViewer Public local acceptance"
echo "Root: $ROOT"
echo "URL:  http://127.0.0.1:$PORT/"
echo "Mode: Cloudflare Wrangler local static-assets runtime"
echo

if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: node is required." >&2
  exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx is required." >&2
  exit 1
fi

node --check site/assets/app.js
node --check site/assets/config.js
node --check site/assets/4174-shared-viewing-a144bb3.js
node --check site/assets/4174-shared-viewing-a144bb3-dom.js

cd "$ROOT/cloudflare"
exec npx wrangler dev --local --port "$PORT" --config wrangler.json
