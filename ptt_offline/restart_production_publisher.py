#!/usr/bin/env python3
"""Safely upgrade/restart the existing production PTT Publisher process.

This helper never changes Cloudflare Worker config, secrets, D1 schema or frontend.
It refuses to restart while any REMOTE_UNCERTAIN state exists. It performs one
read-only snapshot with the currently checked-out Publisher code before replacing
the existing local recurring process, reusing the already aligned local secrets.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .activate_production_publisher import PRODUCTION_PROFILE,start_publisher
from .recurring_publisher import run_snapshot


def uncertain_states(state_dir: Path):
    found=[]
    for path in sorted(state_dir.glob("*.json")):
        try:
            body=json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if body.get("status")=="REMOTE_UNCERTAIN":
            found.append(str(path))
    return found


def assert_recent_completed_cycle(metrics: Path, *, now=None, max_age_seconds=20):
    if not metrics.is_file():
        raise SystemExit("Publisher metrics missing; cannot prove an idle restart window")
    last=None
    for line in metrics.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                last=json.loads(line)
            except json.JSONDecodeError:
                continue
    if not isinstance(last,dict):
        raise SystemExit("Publisher metrics contain no valid completed cycle")
    if last.get("status") not in {"ACK","NO_NEW_ROWS"}:
        raise SystemExit("latest Publisher cycle is not a clean completed send/no-op")
    stamp=last.get("observed_at")
    try:
        observed=datetime.fromisoformat(str(stamp).replace("Z","+00:00")).astimezone(timezone.utc)
    except (TypeError,ValueError):
        raise SystemExit("latest Publisher metric has invalid timestamp")
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age=(current-observed).total_seconds()
    if age<0 or age>max_age_seconds:
        raise SystemExit("no recent completed Publisher cycle; rerun immediately after the next metric")
    return last


def read_running_pid(pidfile: Path) -> int:
    if not pidfile.is_file():
        raise SystemExit("Publisher pidfile missing; use normal activation path instead")
    try:
        pid=int(pidfile.read_text(encoding="utf-8").strip())
    except ValueError:
        raise SystemExit("invalid Publisher pidfile")
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        raise SystemExit("Publisher pidfile is stale; inspect process/state before restart")
    return pid


def process_command(pid: int) -> str:
    result=subprocess.run(
        ["ps","-p",str(pid),"-o","command="],
        check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
    )
    return result.stdout.strip()


def assert_expected_process(pid: int):
    command=process_command(pid)
    if "ptt_offline.recurring_publisher" not in command:
        raise SystemExit("PID does not look like the production recurring Publisher")
    return command


def wait_stopped(pid: int, timeout=15.0):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            os.kill(pid,0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    raise SystemExit("Publisher did not stop after SIGTERM; refusing SIGKILL")


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--source",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/"hololive_ptt.sqlite3"))
    p.add_argument("--state-root",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/".ptt-publisher-state"))
    args=p.parse_args(argv)
    if not args.apply:
        raise SystemExit("refusing Publisher restart without --apply")

    repo_root=Path(__file__).resolve().parents[1]
    source=str(Path(args.source).expanduser().resolve(strict=True))
    state_root=Path(args.state_root).expanduser().resolve()
    state_dir=state_root/"state"
    secrets_path=state_root/".publisher-secrets.json"
    pidfile=state_root/"publisher.pid"
    metrics=state_root/"minute-metrics.jsonl"

    if not secrets_path.is_file():
        raise SystemExit("publisher secrets file missing")
    secrets=json.loads(secrets_path.read_text(encoding="utf-8"))
    for name in ("PTT_PUBLISH_HMAC_SECRET","PTT_TIME_AUTHORITY_SECRET"):
        value=secrets.get(name)
        if not isinstance(value,str) or len(value)<32:
            raise SystemExit(name+" missing or invalid")

    uncertain=uncertain_states(state_dir)
    if uncertain:
        raise SystemExit("REMOTE_UNCERTAIN state exists; reconcile exact batch before restart")

    old_pid=read_running_pid(pidfile)
    old_command=assert_expected_process(old_pid)
    idle_receipt=assert_recent_completed_cycle(metrics)

    # Stop only immediately after a completed ACK/NO_NEW_ROWS cycle. This
    # minimizes the chance of interrupting a signed POST from the old code.
    os.kill(old_pid,signal.SIGTERM)
    wait_stopped(old_pid)
    pidfile.unlink(missing_ok=True)

    preview=run_snapshot(
        source=source,state_dir=str(state_dir),send=False,
        batch_cap=PRODUCTION_PROFILE["rows"],
        max_batches=PRODUCTION_PROFILE["max_batches"],
        max_articles=PRODUCTION_PROFILE["max_articles"],
    )
    if preview.get("publisher_mode")!="DRY_RUN":
        raise SystemExit("unexpected preview mode")

    process=start_publisher(repo_root,source,state_root,secrets_path)
    print(json.dumps({
        "status":"PUBLISHER_UPGRADED_AND_RESTARTED",
        "old_pid":old_pid,
        "old_command":old_command,
        "idle_receipt":idle_receipt,
        "preview":preview,
        "process":process,
        "cloudflare_changed":False,
        "secrets_rotated":False,
        "d1_schema_changed":False,
    },ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
