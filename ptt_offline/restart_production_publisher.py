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
from pathlib import Path

from .activate_production_publisher import start_publisher
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

    preview=run_snapshot(
        source=source,state_dir=str(state_dir),send=False,
        batch_cap=25,max_batches=8,max_articles=4,
    )
    if preview.get("publisher_mode")!="DRY_RUN":
        raise SystemExit("unexpected preview mode")

    os.kill(old_pid,signal.SIGTERM)
    wait_stopped(old_pid)
    pidfile.unlink(missing_ok=True)

    process=start_publisher(repo_root,source,state_root,secrets_path)
    print(json.dumps({
        "status":"PUBLISHER_UPGRADED_AND_RESTARTED",
        "old_pid":old_pid,
        "old_command":old_command,
        "preview":preview,
        "process":process,
        "cloudflare_changed":False,
        "secrets_rotated":False,
        "d1_schema_changed":False,
    },ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
