"""Read-only health adapter for the local Hololive PTT Collector runtime.

This module only reads the Collector's status/event/SQLite evidence. It never
logs in, launches/stops Collector, mutates checkpoints, or writes the source DB.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Any


DEFAULT_HEARTBEAT_MAX_AGE=15
DEFAULT_REFRESH_MAX_AGE=90


def _read_json(path: Path) -> dict[str,Any]:
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError):
        return {}
    return value if isinstance(value,dict) else {}


def _parse_event_time(value: object) -> float | None:
    if not isinstance(value,str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
    except ValueError:
        return None


def _latest_refresh_event(path: Path, *, after_timestamp: float | None=None) -> dict[str,Any] | None:
    try:
        lines=path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in reversed(lines[-500:]):
        try:
            row=json.loads(raw)
        except (ValueError,TypeError):
            continue
        if isinstance(row,dict) and row.get("event")=="refresh_complete":
            if after_timestamp is None:
                return row
            event_time=_parse_event_time(row.get("time_utc"))
            if event_time is not None and event_time>after_timestamp:
                return row
    return None


def read_collector_health(
    root: str | Path,
    *,
    now: float | None=None,
    heartbeat_max_age: int=DEFAULT_HEARTBEAT_MAX_AGE,
    refresh_max_age: int=DEFAULT_REFRESH_MAX_AGE,
    refresh_after_timestamp: float | None=None,
) -> dict[str,Any]:
    """Return sanitized health evidence from existing local runtime artifacts.

    "frontier_progressing" means recent successful refresh activity exists;
    source_line itself is allowed to remain unchanged when there are no new
    pushes.
    """
    root=Path(root)
    current=time.time() if now is None else float(now)
    status=_read_json(root/"collector_live_status.json")
    refresh=_latest_refresh_event(
        root/"collector_events.jsonl",
        after_timestamp=refresh_after_timestamp,
    )

    updated_at=status.get("updated_at")
    heartbeat_age=(current-float(updated_at)
                   if isinstance(updated_at,(int,float)) else None)
    heartbeat_fresh=(
        heartbeat_age is not None and 0<=heartbeat_age<=heartbeat_max_age
    )

    pid=status.get("pid")
    process_alive=False
    if type(pid) is int and pid>0:
        try:
            import os
            os.kill(pid,0)
        except (OSError,ValueError):
            process_alive=False
        else:
            process_alive=True

    refresh_at=_parse_event_time(refresh.get("time_utc") if refresh else None)
    refresh_age=(current-refresh_at if refresh_at is not None else None)
    refresh_fresh=(
        refresh_age is not None and 0<=refresh_age<=refresh_max_age
    )

    live_aid=refresh.get("aid") if refresh else None
    frontier=refresh.get("last_source_line") if refresh else None
    live_context_valid=(
        isinstance(live_aid,str) and bool(live_aid)
        and type(frontier) is int and frontier>=1
    )

    return {
        "process_alive":process_alive,
        "heartbeat_fresh":heartbeat_fresh,
        "live_context_valid":live_context_valid,
        "frontier_progressing":refresh_fresh,
        "live_aid":live_aid,
        "frontier":frontier,
        "phase":status.get("phase"),
        "managed":status.get("managed"),
        "pid":pid,
        "run_id":status.get("run_id"),
        "heartbeat_age_seconds":heartbeat_age,
        "refresh_age_seconds":refresh_age,
        "evidence":{
            "status_path":str(root/"collector_live_status.json"),
            "event_log_path":str(root/"collector_events.jsonl"),
            "refresh_event_time":refresh.get("time_utc") if refresh else None,
        },
    }
