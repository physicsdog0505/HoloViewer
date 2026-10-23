#!/usr/bin/env python3
"""Owner-local launchd installer for the resilient #48 Publisher.

Default mode is inspect-only. --apply performs a stop-first replacement of the
legacy detached Publisher with one launchd KeepAlive service. It never deploys
Cloudflare resources, rotates secrets, edits Collector data, or mutates D1.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .public_today_contract import ContractError

LABEL="com.holodocchi.ptt-publisher"

def _run(cmd,*,check=True,capture=True):
    return subprocess.run(cmd,check=check,text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None)

def _pid_alive(pid):
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False

def _read_pid(path):
    try:
        value=int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError,ValueError):
        return None
    return value if value>0 else None

def _command(pid):
    r=_run(["ps","-p",str(pid),"-o","command="],check=False)
    return (r.stdout or "").strip()

def _uncertain_states(state_dir):
    found=[]
    for path in sorted(Path(state_dir).glob("*.json")):
        try:
            body=json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if body.get("status") in {"REMOTE_UNCERTAIN","STOP_MANUAL","STOP_RECONCILE"}:
            found.append({
                "file":path.name,
                "status":body.get("status"),
                "pending_batch_id":body.get("pending_batch_id"),
            })
    return found

def build_plist(*,repo_root,owner_root,python_executable):
    repo_root=Path(repo_root).resolve()
    owner_root=Path(owner_root).expanduser().resolve()
    state=owner_root/".ptt-publisher-state"
    return {
        "Label":LABEL,
        "ProgramArguments":[
            str(python_executable),"-B","-m","ptt_offline.publisher_service",
            "--root",str(owner_root),
        ],
        "WorkingDirectory":str(repo_root),
        "RunAtLoad":True,
        "KeepAlive":True,
        "ProcessType":"Background",
        "ThrottleInterval":10,
        "StandardOutPath":str(state/"publisher-service.log"),
        "StandardErrorPath":str(state/"publisher-service.log"),
        "EnvironmentVariables":{
            "PYTHONUNBUFFERED":"1",
        },
    }

def _atomic_plist(path,body):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as handle:
            plistlib.dump(body,handle,sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def _stop_legacy(pidfile):
    pid=_read_pid(pidfile)
    if pid is None or not _pid_alive(pid):
        Path(pidfile).unlink(missing_ok=True)
        return {"stopped":False,"pid":pid,"reason":"NO_LIVE_PID"}
    command=_command(pid)
    if ("ptt_offline.recurring_publisher" not in command and
        "ptt_offline.publisher_service" not in command):
        raise ContractError("publisher pidfile points to unexpected live process")
    os.kill(pid,signal.SIGTERM)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if not _pid_alive(pid):
            Path(pidfile).unlink(missing_ok=True)
            return {"stopped":True,"pid":pid,"command":command}
        time.sleep(0.2)
    raise ContractError("Publisher did not stop after SIGTERM; refusing SIGKILL")

def inspect(*,repo_root,owner_root,python_executable):
    owner_root=Path(owner_root).expanduser().resolve()
    state=owner_root/".ptt-publisher-state"
    pidfile=state/"publisher.pid"
    pid=_read_pid(pidfile)
    command=_command(pid) if pid and _pid_alive(pid) else None
    plist_path=Path.home()/"Library"/"LaunchAgents"/(LABEL+".plist")
    return {
        "label":LABEL,
        "repo_root":str(Path(repo_root).resolve()),
        "owner_root":str(owner_root),
        "python":str(python_executable),
        "pidfile":str(pidfile),
        "pid":pid,
        "pid_alive":bool(pid and _pid_alive(pid)),
        "command":command,
        "ambiguous_states":_uncertain_states(state/"state"),
        "plist_path":str(plist_path),
        "plist_exists":plist_path.exists(),
    }

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    p.add_argument("--python",default=sys.executable)
    p.add_argument("--apply",action="store_true")
    args=p.parse_args(argv)

    repo_root=Path(__file__).resolve().parents[1]
    owner_root=Path(args.root).expanduser().resolve()
    state=owner_root/".ptt-publisher-state"
    if not (owner_root/"hololive_ptt.sqlite3").is_file():
        raise SystemExit("Collector SQLite missing")
    if not (state/".publisher-secrets.json").is_file():
        raise SystemExit("Publisher secrets missing")

    before=inspect(repo_root=repo_root,owner_root=owner_root,
                   python_executable=args.python)
    if not args.apply:
        print(json.dumps({"mode":"INSPECT_ONLY",**before},ensure_ascii=False,indent=2))
        return
    if before["ambiguous_states"]:
        raise SystemExit("ambiguous Publisher state exists; reconcile before launchd cutover")

    uid=os.getuid()
    target=f"gui/{uid}/{LABEL}"
    plist_path=Path(before["plist_path"])

    # Remove any previously loaded service before replacing the legacy writer.
    _run(["launchctl","bootout",target],check=False)
    stopped=_stop_legacy(state/"publisher.pid")

    body=build_plist(repo_root=repo_root,owner_root=owner_root,
                     python_executable=args.python)
    _atomic_plist(plist_path,body)

    _run(["launchctl","bootstrap",f"gui/{uid}",str(plist_path)],check=True)
    _run(["launchctl","enable",target],check=True)
    _run(["launchctl","kickstart","-k",target],check=True)

    time.sleep(3)
    after=inspect(repo_root=repo_root,owner_root=owner_root,
                  python_executable=args.python)
    if not after["pid_alive"]:
        raise SystemExit("launchd Publisher did not claim pidfile")
    if "ptt_offline.publisher_service" not in (after["command"] or ""):
        raise SystemExit("launchd Publisher process identity mismatch")

    print(json.dumps({
        "status":"LAUNCHD_CUTOVER_PASS",
        "stop_first":stopped,
        "before":before,
        "after":after,
        "cloudflare_changed":False,
        "collector_changed":False,
        "d1_changed":False,
        "secrets_rotated":False,
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
