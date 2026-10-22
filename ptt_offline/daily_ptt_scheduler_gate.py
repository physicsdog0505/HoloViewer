"""Owner-local 07:30 Collector health/recovery gate for #48.

This is the scheduler seam in front of the existing daily history runtime.
It performs only Collector health classification and, for an explicitly stopped
dead Collector, at most one already-reviewed controlled start.

Until authoritative remote-tail acquisition is integrated, this gate deliberately
does not invoke the downstream completeness/archive runtime.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .collector_controlled_recovery import controlled_start_once
from .collector_runtime_health import read_collector_health
from .collector_health_contract import classify_collector_health
from .daily_ptt_finalization import previous_taipei_day

TPE=ZoneInfo("Asia/Taipei")
SCHEMA_VERSION="holoviewer-ptt-0730-scheduler-gate-v1"


def _atomic_json(path: Path, body: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(body,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)


def _load_daily_config(path: Path) -> dict[str,Any]:
    try:
        body=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError) as exc:
        raise RuntimeError("daily history config unavailable") from exc
    if not isinstance(body,dict):
        raise RuntimeError("daily history config object required")
    source=Path(str(body.get("collector_source") or "")).expanduser()
    state=Path(str(body.get("state_root") or "")).expanduser()
    if not source.is_file():
        raise RuntimeError("collector source unavailable")
    if not str(state):
        raise RuntimeError("state_root required")
    return {
        "collector_source":source.resolve(),
        "collector_root":source.resolve().parent,
        "state_root":state.resolve(),
    }


def run_scheduler_gate(
    *,
    daily_config_path: str | Path,
    recovery_config_path: str | Path | None=None,
    now: datetime | None=None,
    health_probe=None,
    recovery_executor=None,
) -> dict[str,Any]:
    config=_load_daily_config(Path(daily_config_path).expanduser())
    local_now=(now or datetime.now(TPE)).astimezone(TPE)
    day=previous_taipei_day(local_now)
    root: Path=config["collector_root"]
    state: Path=config["state_root"]
    receipt_path=state/"collector-health"/f"{day}.json"
    recovery_receipt=state/"collector-health"/f"{day}.recovery.json"
    recovery_config=(
        Path(recovery_config_path).expanduser()
        if recovery_config_path is not None
        else root/".collector-recovery-config.json"
    )

    probe=health_probe or (lambda:read_collector_health(root))
    raw_before=probe()
    health_before=classify_collector_health(raw_before)
    attempted=False
    recovery_result="NOT_NEEDED"
    raw_after=raw_before

    if not health_before["healthy"]:
        if raw_before.get("process_alive") is True:
            recovery_result="ALIVE_UNHEALTHY_NO_RECOVERY_CHANNEL"
        else:
            attempted=True
            run_key=f"0730-{day}"
            executor=recovery_executor or (
                lambda:controlled_start_once(
                    collector_root=root,
                    config_path=recovery_config,
                    receipt_path=recovery_receipt,
                    run_key=run_key,
                )
            )
            try:
                recovery=executor()
            except Exception as exc:
                recovery_result="FAILED:"+type(exc).__name__
            else:
                recovery_result=(
                    recovery.get("status")
                    if isinstance(recovery,dict)
                    else "ATTEMPTED"
                )
                raw_after=probe()

    health_after=classify_collector_health(raw_after)
    health_ok=health_after["healthy"]

    body={
        "schema_version":SCHEMA_VERSION,
        "day":day,
        "observed_at":local_now.isoformat(),
        "collector_health_before":health_before,
        "restart_attempted":attempted,
        "restart_result":recovery_result,
        "collector_health_after":health_after,
        "resolved_live_aid":health_after.get("live_aid"),
        "resolved_live_frontier":health_after.get("frontier"),
        "health_gate_passed":health_ok,
        "downstream_authorized":False,
        "downstream_status":"HOLD_AUTHORITATIVE_TAIL_INTEGRATION",
        "handoff_status":"BLOCKED_FOR_163_HANDOFF",
        "handoff_blockers":[
            "authoritative-remote-tail-provenance-pending",
            "fresh-verified-complete-finalization-pending",
        ] if health_ok else [
            "collector-health-gate-not-passed",
            "authoritative-remote-tail-provenance-pending",
            "fresh-verified-complete-finalization-pending",
        ],
        "archive_ready":False,
        "failure_code":(
            "authoritative-tail-integration-pending"
            if health_ok
            else "collector-health-not-restored"
        ),
        "safety":{
            "restart_attempts":1 if attempted else 0,
            "checkpoint_reset":False,
            "db_clear":False,
            "duplicate_collector_launch":False,
            "publisher_mutation":False,
        },
    }
    _atomic_json(receipt_path,body)
    return body


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-config",required=True)
    parser.add_argument("--recovery-config")
    args=parser.parse_args(argv)
    try:
        body=run_scheduler_gate(
            daily_config_path=args.daily_config,
            recovery_config_path=args.recovery_config,
        )
    except Exception as exc:
        print(json.dumps({
            "schema_version":SCHEMA_VERSION,
            "status":"FAILED",
            "failure_code":type(exc).__name__,
        },ensure_ascii=False,sort_keys=True))
        return 2
    print(json.dumps(body,ensure_ascii=False,sort_keys=True))
    return 0 if body.get("health_gate_passed") is True else 3


if __name__=="__main__":
    raise SystemExit(main())
