#!/bin/sh
set -eu
printf '%s\n' "This frontend-coupled Watchalong deploy entrypoint is retired." >&2
printf '%s\n' "Use scripts/deploy_watchalong_static_assets_owner_local.sh." >&2
exit 2
