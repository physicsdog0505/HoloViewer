"""Operational limits and runtime settings for the collector's live mode.

These values are intentionally kept in one file so they can be reviewed and
changed without searching through the navigation code.
"""

from __future__ import annotations

import json
from pathlib import Path

DISCOVERY_MAX_PAGES = 30
GAP_REPAIR_MAX_PAGES = 50
REFRESH_INTERVAL_SECONDS = 60
RECONNECT_DELAY_SECONDS = 15
DISCOVERY_INTERVAL_SECONDS = 30
ALLOWED_REFRESH_INTERVALS = (5, 10, 30, 60)

ROOT = Path(__file__).resolve().parent
EVENT_LOG_PATH = ROOT / "collector_events.jsonl"
INSTANCE_LOCK_PATH = ROOT / ".collector.lock"
RUNTIME_SETTINGS_PATH = Path(__file__).resolve().parent / "collector_runtime_settings.json"


def get_refresh_interval(path: str | Path = RUNTIME_SETTINGS_PATH) -> int:
    """Return a validated live refresh interval, falling back safely to 60."""
    try:
        value = int(json.loads(Path(path).read_text(encoding="utf-8"))["refresh_interval_seconds"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return REFRESH_INTERVAL_SECONDS
    return value if value in ALLOWED_REFRESH_INTERVALS else REFRESH_INTERVAL_SECONDS


def set_refresh_interval(value: int, path: str | Path = RUNTIME_SETTINGS_PATH) -> None:
    """Atomically publish a frontend-selected collector refresh interval."""
    value = int(value)
    if value not in ALLOWED_REFRESH_INTERVALS:
        raise ValueError(f"不支援的更新秒數：{value}")
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"refresh_interval_seconds": value}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
