#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/vendor/4174-a144bb3"
PORT="${PORT:-8788}"
RUNTIME_ROOT="${PTT_4174_RUNTIME_ROOT:-$HOME/Downloads/Hololive-PTT-Viewer}"

python3 "$ROOT/tools/verify_4174_snapshot.py"

if [ ! -d "$RUNTIME_ROOT" ]; then
  echo "Missing runtime data root: $RUNTIME_ROOT" >&2
  echo "Set PTT_4174_RUNTIME_ROOT to the existing 4174 runtime-data checkout." >&2
  exit 1
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
unset PYTHONPATH

echo "4174 source: a144bb378a8bdd772faa867d608c1e7491253883"
echo "4174 code root: $VENDOR"
echo "Runtime data root: $RUNTIME_ROOT"
echo "URL: http://127.0.0.1:$PORT/"

exec python3 "$ROOT/tools/run_4174_snapshot.py" --port "$PORT" --runtime-root "$RUNTIME_ROOT"
