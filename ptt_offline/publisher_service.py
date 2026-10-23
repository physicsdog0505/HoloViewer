"""Owner-local service entrypoint for resilient #48 Publisher.

Designed for launchd KeepAlive. It loads existing local secrets, never prints
secret values, and delegates all single-writer/checkpoint/recovery semantics to
recurring_publisher. This module does not edit Publisher state itself.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from .recurring_publisher import main as recurring_main
from .public_today_contract import ContractError

def build_runtime(root):
    root=Path(root).expanduser().resolve()
    state=root/".ptt-publisher-state"
    secrets_path=state/".publisher-secrets.json"
    source=root/"hololive_ptt.sqlite3"
    if not source.is_file():
        raise ContractError("collector database missing")
    if not secrets_path.is_file():
        raise ContractError("publisher secrets missing")
    try:
        secrets=json.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError("publisher secrets unreadable") from exc
    publish=secrets.get("PTT_PUBLISH_HMAC_SECRET")
    authority=secrets.get("PTT_TIME_AUTHORITY_SECRET")
    if not isinstance(publish,str) or len(publish)<32 or not isinstance(authority,str) or len(authority)<32:
        raise ContractError("publisher secrets invalid")
    env={
        "PTT_ALLOW_CAPTURE_TIME_POLICY":"true",
        "PTT_PUBLISH_HMAC_SECRET":publish,
        "PTT_TIME_AUTHORITY_SECRET":authority,
    }
    argv=[
        "--source",str(source),
        "--state-dir",str(state/"state"),
        "--metrics",str(state/"minute-metrics.jsonl"),
        "--iterations","0",
        "--batch-cap","10",
        "--max-batches","1",
        "--burst-max-batches","1",
        "--max-articles","4",
        "--adaptive-live-cadence",
        "--send",
        "--approve-live-capture-policy",
    ]
    return env,argv

def _pid_alive(pid):
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False

def _claim_pidfile(path):
    path=Path(path)
    if path.exists():
        try:
            old=int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            old=None
        if old is not None and old!=os.getpid() and _pid_alive(old):
            raise ContractError("another Publisher pidfile owner is alive")
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            handle.write(str(os.getpid())+"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,path)
        os.chmod(path,0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def _release_pidfile(path):
    path=Path(path)
    try:
        current=int(path.read_text(encoding="utf-8").strip())
    except (OSError,ValueError):
        return
    if current==os.getpid():
        path.unlink(missing_ok=True)

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    args=p.parse_args(argv)
    env,child_argv=build_runtime(args.root)
    state=Path(args.root).expanduser().resolve()/".ptt-publisher-state"
    pidfile=state/"publisher.pid"
    _claim_pidfile(pidfile)
    old={k:os.environ.get(k) for k in env}
    try:
        os.environ.update(env)
        return recurring_main(child_argv)
    finally:
        _release_pidfile(pidfile)
        for key,value in old.items():
            if value is None:
                os.environ.pop(key,None)
            else:
                os.environ[key]=value

if __name__=="__main__":
    main()
