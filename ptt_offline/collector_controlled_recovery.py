"""Owner-local, single-attempt Collector recovery adapter for #48.

This adapter never stores a password. It delegates launch to the existing
Hololive-PTT-Viewer collector_control.launch_collector(), which uses the local
Keychain, launch lock, single-instance lock and startup guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

from .collector_runtime_health import read_collector_health
from .public_today_contract import ContractError


SCHEMA_VERSION="holoviewer-ptt-collector-recovery-v1"


def _atomic_json(path: Path, body: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    tmp.replace(path)


def load_recovery_config(path: str | Path) -> dict[str,Any]:
    try:
        body=json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError) as exc:
        raise ContractError("collector recovery config unavailable") from exc
    if not isinstance(body,dict) or body.get("enabled") is not True:
        raise ContractError("collector recovery is not explicitly enabled")
    username=body.get("username")
    if not isinstance(username,str) or not username.isascii() or not username.isalnum():
        raise ContractError("invalid collector recovery username")
    test_account=body.get("test_account",False)
    if type(test_account) is not bool:
        raise ContractError("invalid collector recovery test_account")
    return {"username":username,"test_account":test_account}


def _load_collector_control(root: Path):
    path=root/"collector_control.py"
    if not path.is_file():
        raise ContractError("collector_control.py unavailable")
    # Existing collector modules import each other by checkout-local name.
    root_text=str(root)
    if root_text not in sys.path:
        sys.path.insert(0,root_text)
    spec=importlib.util.spec_from_file_location("_ptt48_collector_control",path)
    if spec is None or spec.loader is None:
        raise ContractError("cannot load collector_control")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def controlled_start_once(
    *,
    collector_root: str | Path,
    config_path: str | Path,
    receipt_path: str | Path,
    run_key: str,
    health_probe: Callable[[],dict[str,Any]] | None=None,
    sleep: Callable[[float],None]=time.sleep,
    confirm_timeout_seconds: int=30,
    confirm_interval_seconds: int=2,
) -> dict[str,Any]:
    """Launch a dead Collector at most once for one durable run_key."""
    root=Path(collector_root)
    receipt=Path(receipt_path)
    if not run_key or not isinstance(run_key,str):
        raise ContractError("recovery run_key required")

    probe=health_probe or (lambda **kwargs:read_collector_health(root,**kwargs))
    before=probe()
    healthy_before=(
        before.get("process_alive") is True
        and before.get("heartbeat_fresh") is True
        and before.get("live_context_valid") is True
        and before.get("frontier_progressing") is True
    )
    if healthy_before:
        return {
            "schema_version":SCHEMA_VERSION,
            "run_key":run_key,
            "status":"NOT_NEEDED",
            "attempted":False,
            "collector_health_after":before,
        }
    if before.get("phase")=="blocked":
        raise ContractError("collector blocked; automatic start forbidden")
    if before.get("process_alive") is True:
        return {
            "schema_version":SCHEMA_VERSION,
            "run_key":run_key,
            "status":"ALIVE_UNHEALTHY_NO_RECOVERY_CHANNEL",
            "attempted":False,
            "collector_health_after":before,
        }

    allowed_dead_phases={"stopped"}
    if before.get("phase") not in allowed_dead_phases:
        raise ContractError("collector phase not eligible for automatic start")

    if receipt.exists():
        try:
            prior=json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError,ValueError,TypeError):
            prior={}
        if isinstance(prior,dict) and prior.get("run_key")==run_key and prior.get("attempted") is True:
            raise ContractError("collector recovery already attempted for run_key")

    cfg=load_recovery_config(config_path)
    attempt_timestamp=time.time()
    pre_attempt_pid=before.get("pid")
    pre_attempt_run_id=before.get("run_id")
    attempt={
        "schema_version":SCHEMA_VERSION,
        "run_key":run_key,
        "attempted":True,
        "status":"ATTEMPTING",
        "attempted_at":datetime.fromtimestamp(
            attempt_timestamp,timezone.utc
        ).isoformat(timespec="seconds"),
        "pre_attempt_pid":pre_attempt_pid,
        "pre_attempt_run_id":pre_attempt_run_id,
        "test_account":cfg["test_account"],
        # Deliberately omit username from receipt.
        "password_storage":"macOS-keychain-existing-entry",
        "restart_attempts":1,
        "checkpoint_reset":False,
        "db_clear":False,
        "duplicate_launch_allowed":False,
    }
    _atomic_json(receipt,attempt)

    control=_load_collector_control(root)
    try:
        message=control.launch_collector(cfg["username"],test_account=cfg["test_account"])
    except Exception as exc:
        failed={**attempt,"status":"FAILED","failure_code":"launch-"+type(exc).__name__}
        _atomic_json(receipt,failed)
        return failed

    deadline=time.monotonic()+confirm_timeout_seconds
    after=None
    while time.monotonic()<deadline:
        try:
            after=probe(refresh_after_timestamp=attempt_timestamp)
        except TypeError:
            after=probe()
        new_identity=(
            after.get("pid") is not None
            and after.get("run_id") is not None
            and (
                after.get("pid")!=pre_attempt_pid
                or after.get("run_id")!=pre_attempt_run_id
            )
        )
        heartbeat_timestamp=after.get("heartbeat_timestamp")
        heartbeat_after_attempt=(
            isinstance(heartbeat_timestamp,(int,float))
            and heartbeat_timestamp>attempt_timestamp
        )
        if (
            after.get("process_alive") is True
            and after.get("heartbeat_fresh") is True
            and after.get("live_context_valid") is True
            and after.get("frontier_progressing") is True
            and new_identity
            and heartbeat_after_attempt
        ):
            ok={
                **attempt,
                "status":"RECOVERED",
                "launch_message":message,
                "collector_health_after":after,
            }
            _atomic_json(receipt,ok)
            return ok
        sleep(confirm_interval_seconds)

    uncertain={
        **attempt,
        "status":"STARTED_UNCONFIRMED",
        "launch_message":message,
        "collector_health_after":after,
    }
    _atomic_json(receipt,uncertain)
    return uncertain


def main() -> int:
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector-root",required=True)
    parser.add_argument("--config",required=True)
    parser.add_argument("--receipt",required=True)
    parser.add_argument("--run-key",required=True)
    args=parser.parse_args()
    try:
        body=controlled_start_once(
            collector_root=args.collector_root,
            config_path=args.config,
            receipt_path=args.receipt,
            run_key=args.run_key,
        )
    except Exception as exc:
        print(json.dumps({
            "schema_version":SCHEMA_VERSION,
            "status":"FAILED",
            "failure_code":type(exc).__name__,
        },ensure_ascii=False,sort_keys=True))
        return 2
    print(json.dumps(body,ensure_ascii=False,sort_keys=True))
    return 0 if body.get("status") in ("NOT_NEEDED","RECOVERED") else 3


if __name__=="__main__":
    raise SystemExit(main())
