#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
ACCEPTED_4174_ROOT="${ACCEPTED_4174_ROOT:-}"
pick_port() {
  python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
PY
}

BASELINE_PORT="${BASELINE_PORT:-$(pick_port)}"
CANDIDATE_PORT="${CANDIDATE_PORT:-$(pick_port)}"
if [ "$BASELINE_PORT" = "$CANDIDATE_PORT" ]; then
  CANDIDATE_PORT="$(pick_port)"
fi

if [ -z "$ACCEPTED_4174_ROOT" ]; then
  echo "ACCEPTED_4174_ROOT is required and must point to the clean accepted 4174 checkout." >&2
  exit 1
fi

ACCEPTED_4174_ROOT="$(cd "$ACCEPTED_4174_ROOT" && pwd)"
if [ ! -f "$ACCEPTED_4174_ROOT/client_app.py" ]; then
  echo "accepted 4174 client_app.py not found: $ACCEPTED_4174_ROOT" >&2
  exit 1
fi

SOURCE_HEAD="$(git -C "$ACCEPTED_4174_ROOT" rev-parse HEAD)"
EXPECTED_SOURCE="a144bb378a8bdd772faa867d608c1e7491253883"
if [ "$SOURCE_HEAD" != "$EXPECTED_SOURCE" ]; then
  echo "accepted 4174 checkout HEAD mismatch: $SOURCE_HEAD" >&2
  exit 1
fi

if [ -n "$(git -C "$ACCEPTED_4174_ROOT" status --short)" ]; then
  echo "accepted 4174 checkout must be clean" >&2
  git -C "$ACCEPTED_4174_ROOT" status --short >&2
  exit 1
fi

cd "$ROOT"
python3 tools/verify_4174_snapshot.py
python3 -m unittest -v test_runtime_isolation

BASELINE_DATA="$(mktemp -d "${TMPDIR:-/tmp}/holoviewer-4174-parity.XXXXXX")"
CANDIDATE_DATA="$(mktemp -d "${TMPDIR:-/tmp}/holoviewer-8788-parity.XXXXXX")"
BASELINE_LOG="$(mktemp "${TMPDIR:-/tmp}/holoviewer-4174-parity-log.XXXXXX")"
CANDIDATE_LOG="$(mktemp "${TMPDIR:-/tmp}/holoviewer-8788-parity-log.XXXXXX")"

BASELINE_PID=""
CANDIDATE_PID=""

cleanup() {
  if [ -n "$BASELINE_PID" ]; then kill "$BASELINE_PID" 2>/dev/null || true; fi
  if [ -n "$CANDIDATE_PID" ]; then kill "$CANDIDATE_PID" 2>/dev/null || true; fi
  wait "$BASELINE_PID" 2>/dev/null || true
  wait "$CANDIDATE_PID" 2>/dev/null || true
  rm -rf "$BASELINE_DATA" "$CANDIDATE_DATA"
  rm -f "$BASELINE_LOG" "$CANDIDATE_LOG"
}
trap cleanup EXIT INT TERM HUP

(
  cd "$ACCEPTED_4174_ROOT"
  export PYTHONNOUSERSITE=1
  export PYTHONDONTWRITEBYTECODE=1
  export PTT_CLIENT_DISABLE_TODAY_REFRESH=1
  unset PYTHONPATH
  exec python3 client_app.py     --host 127.0.0.1     --port "$BASELINE_PORT"     --runtime-root "$BASELINE_DATA"
) >"$BASELINE_LOG" 2>&1 &
BASELINE_PID=$!

(
  cd "$ROOT"
  exec python3 tools/run_4174_snapshot.py     --port "$CANDIDATE_PORT"     --runtime-data-root "$CANDIDATE_DATA"
) >"$CANDIDATE_LOG" 2>&1 &
CANDIDATE_PID=$!

wait_ready() {
  url="$1"
  label="$2"
  log="$3"
  pid="$4"
  expected_runtime_root="$5"
  n=0
  while [ "$n" -lt 50 ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$label process exited before readiness: pid=$pid" >&2
      cat "$log" >&2
      return 1
    fi
    if python3 - "$url" <<'PY'
import sys
from urllib.request import urlopen
try:
    with urlopen(sys.argv[1], timeout=1) as r:
        raise SystemExit(0 if r.status < 500 else 1)
except Exception:
    raise SystemExit(1)
PY
    then
      n=0
      while [ "$n" -lt 20 ]; do
        if grep -F "Client runtime data: $expected_runtime_root" "$log" >/dev/null 2>&1; then
          return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
          echo "$label process exited before provenance confirmation: pid=$pid" >&2
          cat "$log" >&2
          return 1
        fi
        n=$((n + 1))
        sleep 0.1
      done
      echo "$label responded, but provenance did not confirm expected runtime root" >&2
      echo "expected: $expected_runtime_root" >&2
      cat "$log" >&2
      return 1
    fi
    n=$((n + 1))
    sleep 0.2
  done
  echo "$label did not become ready: $url" >&2
  cat "$log" >&2
  return 1
}

wait_ready "http://127.0.0.1:$BASELINE_PORT/" "accepted 4174" "$BASELINE_LOG" "$BASELINE_PID" "$BASELINE_DATA"
wait_ready "http://127.0.0.1:$CANDIDATE_PORT/" "candidate 8788" "$CANDIDATE_LOG" "$CANDIDATE_PID" "$CANDIDATE_DATA"

python3 tools/check_4174_http_parity.py   --baseline "http://127.0.0.1:$BASELINE_PORT"   --candidate "http://127.0.0.1:$CANDIDATE_PORT"

echo "=== ACCEPTED 4174 LOG ==="
cat "$BASELINE_LOG"
echo "=== ISOLATED 8788 LOG ==="
cat "$CANDIDATE_LOG"
