#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

PYTHON_BIN="${PTT_CLIENT_PYTHON:-python3}"
HOST="${PTT_CLIENT_HOST:-127.0.0.1}"
PORT="${PTT_CLIENT_PORT:-4174}"
RUNTIME_ROOT="${PTT_CLIENT_RUNTIME_ROOT:-}"

if [ -n "$RUNTIME_ROOT" ]; then
  exec "$PYTHON_BIN" client_app.py --host "$HOST" --port "$PORT" --runtime-root "$RUNTIME_ROOT"
fi
exec "$PYTHON_BIN" client_app.py --host "$HOST" --port "$PORT"
