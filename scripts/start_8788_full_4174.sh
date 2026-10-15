#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8788}"
RUNTIME_DATA_ROOT="${PTT_4174_RUNTIME_DATA_ROOT:-}"

cd "$ROOT"

python3 tools/verify_4174_snapshot.py
python3 -m unittest -v test_runtime_isolation

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH

CLEANUP_RUNTIME_DATA=0
if [ -z "$RUNTIME_DATA_ROOT" ]; then
  RUNTIME_DATA_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/holoviewer-8788-runtime.XXXXXX")"
  CLEANUP_RUNTIME_DATA=1
fi

cleanup() {
  if [ "$CLEANUP_RUNTIME_DATA" -eq 1 ] && [ -d "$RUNTIME_DATA_ROOT" ]; then
    rm -rf "$RUNTIME_DATA_ROOT"
  fi
}
trap cleanup EXIT INT TERM HUP

echo "8788 code root: $ROOT/vendor/4174-a144bb3"
echo "8788 runtime-data root: $RUNTIME_DATA_ROOT"
echo "Today refresh: disabled (Public API is the sole source when enabled)"
if [ -n "${HOLOVIEWER_PUBLIC_API_BASE:-}" ]; then
  echo "Public API provider: configured; no direct D1 or SQLite integration"
fi
echo "URL: http://127.0.0.1:$PORT/"

if [ -n "${HOLOVIEWER_PUBLIC_API_BASE:-}" ]; then
  python3 tools/run_4174_snapshot.py --port "$PORT" --runtime-data-root "$RUNTIME_DATA_ROOT" --public-api-base "$HOLOVIEWER_PUBLIC_API_BASE"
else
  python3 tools/run_4174_snapshot.py --port "$PORT" --runtime-data-root "$RUNTIME_DATA_ROOT"
fi

python3 tools/verify_4174_snapshot.py
