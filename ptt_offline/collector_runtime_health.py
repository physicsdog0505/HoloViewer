"""Read-only health adapter for the local Hololive PTT Collector runtime.

Prefer the fixed #430 collectorctl health contract when the production
controller is installed. Fall back to the legacy checkout-local status/event
files only for pre-cutover runtimes.

This module never logs in, starts/stops Collector, mutates checkpoints, or
writes the source DB.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import os
import subprocess
import sys
import time
from typing import Any


DEFAULT_HEARTBEAT_MAX_AGE=15
DEFAULT_REFRESH_MAX_AGE=90
DEFAULT_FIXED_ROOT=Path.home()/"Library/Application Support/HoloViewer/collector"


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


def _fixed_collector_health(
    *,
    fixed_root: Path,
    now: float,
    heartbeat_max_age: int,
) -> dict[str,Any] | None:
    controller=fixed_root/"bin/collectorctl.py"
    if not controller.is_file():
        return None
    try:
        result=subprocess.run(
            [sys.executable,str(controller),"--root",str(fixed_root),"status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        body=json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,ValueError,TypeError):
        return None
    if not isinstance(body,dict):
        return None

    state=body.get("state")
    process_count=body.get("process_count")
    managed=body.get("managed_identity") is True
    kernel_lock=body.get("kernel_lock_held") is True
    process_alive=(
        type(process_count) is int
        and process_count==1
        and managed
        and kernel_lock
        and state in {"RUNNING","UNHEALTHY"}
    )

    heartbeat_age=body.get("heartbeat_age_seconds")
    heartbeat_fresh=(
        isinstance(heartbeat_age,(int,float))
        and 0<=float(heartbeat_age)<=heartbeat_max_age
    )

    live_aid=body.get("live_aid")
    frontier=body.get("frontier_source_line")
    live_context_valid=(
        isinstance(live_aid,str)
        and bool(live_aid)
        and type(frontier) is int
        and frontier>=1
    )

    healthy=body.get("healthy") is True and state=="RUNNING"
    return {
        "process_alive":process_alive,
        "heartbeat_fresh":heartbeat_fresh,
        "live_context_valid":live_context_valid,
        "frontier_progressing":healthy,
        "live_aid":live_aid,
        "frontier":frontier,
        "phase":body.get("phase"),
        "managed":managed,
        "pid":body.get("pid"),
        "process_state":state,
        "run_id":body.get("run_id"),
        "heartbeat_timestamp":(
            now-float(heartbeat_age)
            if isinstance(heartbeat_age,(int,float))
            else None
        ),
        "heartbeat_age_seconds":heartbeat_age,
        "refresh_age_seconds":(
            now-float(body["last_refresh_complete"])
            if isinstance(body.get("last_refresh_complete"),(int,float))
            else None
        ),
        "evidence":{
            "authority":"collectorctl-status-v1",
            "controller_path":str(controller),
            "state_path":body.get("state_path"),
            "runtime_source_head":body.get("runtime_source_head"),
            "approved_head":body.get("approved_head"),
            "remote_tail":body.get("remote_tail"),
            "gap_status":body.get("gap_status"),
            "startup_backfill_complete":body.get("startup_backfill_complete"),
        },
    }


def read_collector_health(
    root: str | Path,
    *,
    now: float | None=None,
    heartbeat_max_age: int=DEFAULT_HEARTBEAT_MAX_AGE,
    refresh_max_age: int=DEFAULT_REFRESH_MAX_AGE,
    refresh_after_timestamp: float | None=None,
    fixed_root: str | Path | None=None,
) -> dict[str,Any]:
    """Return sanitized Collector health evidence.

    The fixed #430 collectorctl status contract is authoritative when present.
    Legacy checkout-local status/event files remain a compatibility fallback.
    """
    current=time.time() if now is None else float(now)
    canonical_root=(
        Path(fixed_root).expanduser().resolve()
        if fixed_root is not None
        else Path(
            os.environ.get(
                "HOLOVIEWER_COLLECTOR_RUNTIME_ROOT",
                str(DEFAULT_FIXED_ROOT),
            )
        ).expanduser().resolve()
    )
    fixed=_fixed_collector_health(
        fixed_root=canonical_root,
        now=current,
        heartbeat_max_age=heartbeat_max_age,
    )
    if fixed is not None:
        return fixed

    root=Path(root)
    status=_read_json(root/"collector_live_status.json")
    refresh=_latest_refresh_event(
        root/"collector_events.jsonl",
        after_timestamp=refresh_after_timestamp,
    )

    updated_at=status.get("updated_at")
    heartbeat_age=(
        current-float(updated_at)
        if isinstance(updated_at,(int,float))
        else None
    )
    heartbeat_fresh=(
        heartbeat_age is not None
        and 0<=heartbeat_age<=heartbeat_max_age
    )

    pid=status.get("pid")
    process_alive=False
    process_state=None
    if type(pid) is int and pid>0:
        try:
            os.kill(pid,0)
        except (OSError,ValueError):
            process_alive=False
        else:
            try:
                result=subprocess.run(
                    ["ps","-p",str(pid),"-o","stat="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                process_state=(
                    result.stdout.strip().split()[0]
                    if result.stdout.strip()
                    else None
                )
            except (OSError,subprocess.SubprocessError):
                process_state=None
            process_alive=bool(process_state) and not process_state.startswith("Z")

    refresh_at=_parse_event_time(refresh.get("time_utc") if refresh else None)
    refresh_age=current-refresh_at if refresh_at is not None else None
    refresh_fresh=(
        refresh_age is not None
        and 0<=refresh_age<=refresh_max_age
    )

    live_aid=refresh.get("aid") if refresh else None
    frontier=refresh.get("last_source_line") if refresh else None
    live_context_valid=(
        isinstance(live_aid,str)
        and bool(live_aid)
        and type(frontier) is int
        and frontier>=1
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
        "process_state":process_state,
        "run_id":status.get("run_id"),
        "heartbeat_timestamp":updated_at,
        "heartbeat_age_seconds":heartbeat_age,
        "refresh_age_seconds":refresh_age,
        "evidence":{
            "authority":"legacy-checkout-health-v1",
            "status_path":str(root/"collector_live_status.json"),
            "event_log_path":str(root/"collector_events.jsonl"),
            "refresh_event_time":refresh.get("time_utc") if refresh else None,
        },
    }
