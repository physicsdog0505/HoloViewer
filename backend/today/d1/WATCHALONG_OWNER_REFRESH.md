# #47 Watchalong recent source coverage — Owner Mac execution gate

No D1 import, Cloudflare deploy, Web History DB write, or frontend changes.

## Cause of previous false PASS

The exporter is executed using a Python interpreter without `playwright`; the existing `Hololive-PTT-Viewer/web_backfill.py::PttWebClient` imports `playwright.sync_api` lazily. The Web import package is listed in the **private source repository's** `requirements-web.txt`, not core `requirements.txt`. The PttWebClient launches **installed Google Chrome** via `pw.chromium.launch(channel="chrome",headless=True)`. Downloading Playwright Chromium is not required when Chrome is already installed, but Chrome itself must be installed/available and launchable. Keep using the official `thread_discovery.discover_for_date`, `live_stream_discovery.refresh_target`, `fetch_body_via_pttweb`, and `watchalong_ptt_catalog.parse_watchalong_events` paths.

## Owner commands (existing project virtualenv, not system Python)

```bash
set -e
cd "$HOME/Downloads/Hololive-PTT-Viewer"
PY="$PWD/.venv-frontend/bin/python"
test -x "$PY" || { echo "Existing .venv-frontend not found; stop and use your existing project venv"; exit 2; }
"$PY" -m pip install -r requirements-web.txt
"$PY" - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome",headless=True)
    browser.close()
print("WATCHALONG_WEB_RUNTIME_PASS")
PY
cd "$HOME/Downloads/HoloViewer"
git fetch origin issue47-public-collab-watchalong-api
git show origin/issue47-public-collab-watchalong-api:backend/today/d1/export-watchalong-events.py > /tmp/hv47-watchalong-exporter.py
"$PY" -B /tmp/hv47-watchalong-exporter.py \
  --source-root "$HOME/Downloads/Hololive-PTT-Viewer" \
  --days 90 --refresh-missing-recent 30 \
  --output /tmp/hv47-watchalong-repaired.sql \
  --json-output /tmp/hv47-watchalong-repaired.json
```

If the existing environment has no pip module, stop and report the interpreter details; do not install into system Python. If Chrome launch fails, report the error before any fetch. The exporter prints `BLOCKED_WEB_DEPENDENCY` / `BLOCKED_REFRESH_ERRORS` / `BLOCKED_CACHE_PARSE` / `BLOCKED_PROJECTION_INTEGRITY` and exits nonzero without writing a **new** payload. Pre-existing /tmp artifacts must not be reused; only a freshly produced PASS + verified data count as candidate release.

## Required acceptance

JSON stdout must have `status=PASS`, `refresh.days=30`, `refresh.targets`, `refresh.already_cached`, `refresh.fetched`, `refresh.errors=[]`, `refresh.discovery_ok=true`, `refresh.fetch_errors=0`, `refresh.coverage_incomplete=false`, `events`, `streams`, `sql`, `json`. A zero `fetched` is allowed only if **every discovered target was already cached** and zero refresh errors occurred. Never accept the old 153/166 or 164/177 data.

Perform source-based manual calibration before #45 release: three distinct normally parsed Pekora Mushoku Tensei events on 2026-10-01, 2026-10-08 and 2026-10-15, each with a valid 11-character YouTube video ID, no dedupe collision, plus random other recent Watchalong samples. Review output for private body/transcript/translation/mapping leaks. Send receipt and payload hash to #47 before #45 import. #45 alone owns production D1 import and verification.
