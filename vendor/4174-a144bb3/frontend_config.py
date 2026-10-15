"""Viewer database locations; relative settings are rooted at this checkout."""
from __future__ import annotations

import os
from pathlib import Path

from client_runtime import client_runtime_root
from typing import Mapping

ROOT = Path(__file__).resolve().parent


def database_paths(
    root: Path | None = None, environ: Mapping[str, str] | None = None,
) -> tuple[Path, Path]:
    env = os.environ if environ is None else environ
    # Standalone 4174 may run from a clean code checkout while reading the
    # owner-controlled runtime checkout. Relative DB defaults must follow that
    # runtime root, not this module's code location.
    if root is None:
        root = client_runtime_root(code_root=ROOT, environ=env)
    collector_default = (
        "hololive_ptt_test.sqlite3"
        if env.get("PTT_VIEWER_TEST_ACCOUNT") == "1"
        else "hololive_ptt.sqlite3"
    )

    def resolve(name: str, default: str) -> Path:
        path = Path(env.get(name) or default).expanduser()
        return (path if path.is_absolute() else root / path).resolve()

    return (
        resolve("PTT_VIEWER_COLLECTOR_DB", collector_default),
        resolve("PTT_VIEWER_WEB_DB", "../Hololive-PTT-Viewer-web-pilot/web_week_pilot_2026.sqlite3"),
    )
