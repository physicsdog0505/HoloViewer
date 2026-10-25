#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec python3 "$SCRIPT_DIR/run_public_frontend_owner_release.py" "$@"
