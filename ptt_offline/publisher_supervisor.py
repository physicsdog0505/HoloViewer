"""Owner-local launchd supervisor installer for resilient #48 Publisher.

Default mode is plan-only. --apply performs a stop-first cutover from the
currently running manual recurring Publisher to one launchd-managed service.
It never deploys Worker code, rotates secrets, changes D1 schema, or touches
the Collector process/database.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path

from .public_today_contract import ContractError

LABEL="com.holodocchi.ptt-publisher"
DEFAULT_PLIST=Path.home()/"Library"/"LaunchAgents"/f"{LABEL}.plist"

def _run(cmd,*,check=True):
    return subprocess.run(cmd,check=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)

def _pid_alive(pid):
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False

def _command(pid):
    return _run(["ps","-p",str(pid),"-o","command="]).stdout.strip()

def _wait_dead(pid,timeout=20.0):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    raise ContractError("manual Publisher did not stop after SIGTERM")

def _ambiguous_states(state_dir):
    found=[]
    for path in sorted(Path(state_dir).glob("*.json")):
        try:
            body=json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if body.get("status") in {"REMOTE_UNCERTAIN","STOP_RECONCILE","STOP_MANUAL"}:
            found.append((path.name,body.get("status"),body.get("pending_batch_id")))
    return found

def _lock_holders(lock_path):
    result=_run(["lsof","-t",str(lock_path)],check=False)
    return [int(x) for x in result.stdout.split() if x.isdigit()]

def render_plist(*,repo_root,runtime_root,python_executable,log_path):
    repo_root=str(Path(repo_root).expanduser().resolve())
    runtime_root=str(Path(runtime_root).expanduser().resolve())
    # Preserve a stable owner-supplied symlink such as /opt/homebrew/bin/python3.
    # Resolving into a Homebrew Cellar version would make launchd brittle after upgrades.
    python_executable=os.path.abspath(os.path.expanduser(str(python_executable)))
    log_path=str(Path(log_path).expanduser().resolve())
    return {
        "Label":LABEL,
        "ProgramArguments":[
            python_executable,"-B","-m","ptt_offline.publisher_service",
            "--root",runtime_root,
        ],
        "WorkingDirectory":repo_root,
        "RunAtLoad":True,
        "KeepAlive":{"SuccessfulExit":False},
        "ThrottleInterval":30,
        "ProcessType":"Background",
        "StandardOutPath":log_path,
        "StandardErrorPath":log_path,
        "EnvironmentVariables":{"PYTHONUNBUFFERED":"1"},
    }

def preflight(*,repo_root,runtime_root,expected_head):
    repo_root=Path(repo_root).expanduser().resolve()
    runtime_root=Path(runtime_root).expanduser().resolve()
    state_root=runtime_root/".ptt-publisher-state"
    state_dir=state_root/"state"
    pidfile=state_root/"publisher.pid"
    source=runtime_root/"hololive_ptt.sqlite3"
    secrets=state_root/".publisher-secrets.json"
    if not source.is_file() or not secrets.is_file() or not state_dir.is_dir():
        raise ContractError("runtime source/state/secrets missing")
    head=_run(["git","-C",str(repo_root),"rev-parse","HEAD"]).stdout.strip()
    if expected_head and head!=expected_head:
        raise ContractError("supervisor candidate HEAD mismatch")
    ambiguous=_ambiguous_states(state_dir)
    pid=None
    command=None
    if pidfile.is_file():
        try:
            pid=int(pidfile.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise ContractError("invalid Publisher pidfile") from exc
        if _pid_alive(pid):
            command=_command(pid)
            if "ptt_offline.recurring_publisher" not in command:
                raise ContractError("pidfile process is not recurring Publisher")
        else:
            pid=None
    holders=_lock_holders(state_dir/".single-publisher.lock")
    if holders and (pid is None or holders!=[pid]):
        raise ContractError("writer lock ownership does not match current Publisher")
    if pid is not None and ambiguous:
        raise ContractError("live manual Publisher has unresolved state; wait for a clean checkpoint before cutover")
    return {
        "repo_root":str(repo_root),
        "runtime_root":str(runtime_root),
        "state_root":str(state_root),
        "head":head,
        "manual_pid":pid,
        "manual_command":command,
        "lock_holders":holders,
        "ambiguous_count":len(ambiguous),
        "ambiguous_states":ambiguous,
    }

def _atomic_plist(path,body):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    with temp.open("wb") as handle:
        plistlib.dump(body,handle,fmt=plistlib.FMT_XML,sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    os.chmod(path,0o644)

def apply_cutover(*,repo_root,runtime_root,expected_head,python_executable,plist_path=DEFAULT_PLIST):
    proof=preflight(repo_root=repo_root,runtime_root=runtime_root,expected_head=expected_head)
    state_root=Path(proof["state_root"])
    state_dir=state_root/"state"
    pidfile=state_root/"publisher.pid"
    old_pid=proof["manual_pid"]
    if old_pid is not None:
        os.kill(old_pid,signal.SIGTERM)
        _wait_dead(old_pid)
    holders=_lock_holders(state_dir/".single-publisher.lock")
    if holders:
        raise ContractError("writer lock still held after manual Publisher stop")
    pidfile.unlink(missing_ok=True)

    log_path=state_root/"publisher-service.log"
    plist=render_plist(repo_root=repo_root,runtime_root=runtime_root,
                       python_executable=python_executable,log_path=log_path)
    _atomic_plist(plist_path,plist)

    domain=f"gui/{os.getuid()}"
    service=f"{domain}/{LABEL}"
    _run(["launchctl","bootout",service],check=False)
    _run(["launchctl","bootstrap",domain,str(Path(plist_path).resolve())])
    time.sleep(3)
    status=_run(["launchctl","print",service]).stdout
    if "state = running" not in status:
        raise ContractError("launchd Publisher service did not reach running state")
    holders=_lock_holders(state_dir/".single-publisher.lock")
    if len(holders)!=1:
        raise ContractError("launchd service did not establish exactly one writer lock")
    return {
        "status":"SUPERVISOR_CUTOVER_APPLIED",
        "label":LABEL,
        "old_manual_pid":old_pid,
        "new_writer_pid":holders[0],
        "plist":str(Path(plist_path).resolve()),
        "log":str(log_path),
        "head":proof["head"],
        "worker_deploy":False,
        "collector_restart":False,
        "secrets_rotated":False,
        "d1_schema_changed":False,
    }

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root",required=True)
    p.add_argument("--runtime-root",required=True)
    p.add_argument("--expected-head",required=True)
    p.add_argument("--python",default=sys.executable)
    p.add_argument("--plist",default=str(DEFAULT_PLIST))
    p.add_argument("--apply",action="store_true")
    args=p.parse_args(argv)
    proof=preflight(repo_root=args.repo_root,runtime_root=args.runtime_root,
                    expected_head=args.expected_head)
    if not args.apply:
        plist=render_plist(repo_root=args.repo_root,runtime_root=args.runtime_root,
                           python_executable=args.python,
                           log_path=Path(proof["state_root"])/"publisher-service.log")
        print(json.dumps({"status":"PLAN_ONLY","preflight":proof,"plist":plist,
                          "mutation":False},ensure_ascii=False,indent=2))
        return
    result=apply_cutover(repo_root=args.repo_root,runtime_root=args.runtime_root,
                         expected_head=args.expected_head,
                         python_executable=args.python,plist_path=args.plist)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
