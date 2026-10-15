#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo "== Python =="
python3 -B -m py_compile app.py public_snapshot.py test_public_smoke.py test_4174_ui_parity.py
python3 -B -m unittest -v test_public_smoke test_4174_ui_parity

echo "== JavaScript =="
node --check site/assets/app.js
node --check site/assets/config.js
node --check site/assets/4174-shared-viewing-a144bb3.js
node --check site/assets/4174-shared-viewing-a144bb3-dom.js

echo "PASS: local Public preflight"
