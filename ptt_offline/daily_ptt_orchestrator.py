"""Thin 07:30 orchestration seam between accepted #48 gate and #163 runtime.

This module owns no Collector health, recovery, completeness, repair, packaging,
or publication logic. It only sequences two already-reviewed commands:

1. #48 Collector health/recovery gate
2. #163 daily history runtime

The downstream command is executed only when the gate returns JSON with
health_gate_passed=true and exits successfully. Any gate failure stops closed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any, Callable


SCHEMA_VERSION="holoviewer-ptt-0730-orchestrator-v1"


class DailyPttOrchestrationError(RuntimeError):
    pass


def _run_json_command(command: list[str]) -> tuple[int,dict[str,Any]]:
    try:
        result=subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise DailyPttOrchestrationError("command launch failed") from exc
    try:
        body=json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DailyPttOrchestrationError("command did not return one JSON object") from exc
    if not isinstance(body,dict):
        raise DailyPttOrchestrationError("command JSON object required")
    return result.returncode,body


def run_orchestration(
    *,
    gate_command: list[str],
    downstream_command: list[str],
    mode: str,
    command_runner: Callable[[list[str]],tuple[int,dict[str,Any]]] | None=None,
) -> dict[str,Any]:
    if not gate_command or not all(isinstance(x,str) and x for x in gate_command):
        raise DailyPttOrchestrationError("gate command required")
    if not downstream_command or not all(isinstance(x,str) and x for x in downstream_command):
        raise DailyPttOrchestrationError("downstream command required")
    if mode not in {"production","acceptance"}:
        raise DailyPttOrchestrationError("mode must be production or acceptance")

    runner=command_runner or _run_json_command
    gate_rc,gate=runner(gate_command)

    if gate_rc!=0 or gate.get("health_gate_passed") is not True:
        return {
            "schema_version":SCHEMA_VERSION,
            "status":"BLOCKED",
            "day":gate.get("day"),
            "gate_returncode":gate_rc,
            "health_gate_passed":gate.get("health_gate_passed") is True,
            "downstream_invoked":False,
            "downstream_status":"NOT_RUN",
            "failure_code":(
                gate.get("failure_code")
                if isinstance(gate.get("failure_code"),str)
                else "collector-health-gate-failed"
            ),
            "gate_receipt":gate,
        }

    gate_day=gate.get("day")
    if not isinstance(gate_day,str) or not gate_day:
        return {
            "schema_version":SCHEMA_VERSION,
            "status":"FAILED",
            "day":None,
            "mode":mode,
            "gate_returncode":gate_rc,
            "health_gate_passed":True,
            "downstream_invoked":False,
            "downstream_status":"NOT_RUN",
            "failure_code":"gate-day-missing",
            "gate_receipt":gate,
        }

    downstream_rc,downstream=runner(downstream_command)
    downstream_status=downstream.get("status")
    downstream_day=downstream.get("day")
    if not isinstance(downstream_day,str) or not downstream_day:
        success=False
        failure_code="downstream-day-missing"
    elif downstream_day!=gate_day:
        success=False
        failure_code="gate-downstream-day-mismatch"
    else:
        allowed_statuses=(
            {"VERIFIED_COMPLETE_PUBLISHED","ALREADY_VERIFIED"}
            if mode=="production"
            else {"READY_TO_DEPLOY","VERIFIED_COMPLETE_PUBLISHED","ALREADY_VERIFIED"}
        )
        success=downstream_rc==0 and downstream_status in allowed_statuses
        failure_code=None if success else (
            "ready-to-deploy-not-valid-in-production"
            if mode=="production" and downstream_status=="READY_TO_DEPLOY"
            else (
                downstream.get("failure_code")
                if isinstance(downstream.get("failure_code"),str)
                else "daily-history-runtime-failed"
            )
        )
    return {
        "schema_version":SCHEMA_VERSION,
        "status":"SUCCEEDED" if success else "FAILED",
        "day":gate_day,
        "mode":mode,
        "gate_returncode":gate_rc,
        "health_gate_passed":True,
        "downstream_invoked":True,
        "downstream_returncode":downstream_rc,
        "downstream_status":downstream_status,
        "failure_code":failure_code,
        "gate_receipt":gate,
        "downstream_receipt":downstream,
    }


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-command-json",required=True)
    parser.add_argument("--downstream-command-json",required=True)
    parser.add_argument("--mode",choices=("production","acceptance"),required=True)
    args=parser.parse_args(argv)

    try:
        gate_command=json.loads(args.gate_command_json)
        downstream_command=json.loads(args.downstream_command_json)
        body=run_orchestration(
            gate_command=gate_command,
            downstream_command=downstream_command,
            mode=args.mode,
        )
    except (ValueError,TypeError,DailyPttOrchestrationError) as exc:
        print(json.dumps({
            "schema_version":SCHEMA_VERSION,
            "status":"FAILED",
            "failure_code":type(exc).__name__,
        },ensure_ascii=False,sort_keys=True))
        return 2

    print(json.dumps(body,ensure_ascii=False,sort_keys=True))
    return 0 if body.get("status")=="SUCCEEDED" else 3


if __name__=="__main__":
    raise SystemExit(main())
