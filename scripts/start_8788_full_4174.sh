#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8788}"

cd "$ROOT"

python3 tools/verify_4174_snapshot.py

export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH

exec python3 tools/run_4174_snapshot.py --port "$PORT"
