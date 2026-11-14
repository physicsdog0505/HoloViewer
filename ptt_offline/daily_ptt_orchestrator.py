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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .daily_ptt_finalization import previous_taipei_day


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
        raise DailyPttOrchestrationError(
            "command launch failed: "+type(exc).__name__) from exc
    try:
        body=json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        stderr_tail=(result.stderr or "").strip().splitlines()[-1:]
        detail=stderr_tail[0][:500] if stderr_tail else "stderr-empty"
        raise DailyPttOrchestrationError(
            f"command did not return one JSON object (rc={result.returncode}; {detail})") from exc
    if not isinstance(body,dict):
        raise DailyPttOrchestrationError("command JSON object required")
    return result.returncode,body


def _failed_command_receipt(*, stage: str, day: str | None,
                            exc: DailyPttOrchestrationError) -> dict[str,Any]:
    return {
        "schema_version":SCHEMA_VERSION,
        "status":"FAILED",
        "day":day,
        "failure_code":"command-output-invalid",
        "failure_stage":stage,
        "failure_detail":str(exc),
        "downstream_invoked":stage=="downstream",
        "downstream_status":"FAILED" if stage=="downstream" else "NOT_RUN",
    }


def _expand_day(command: list[str], day: str) -> list[str]:
    return [part.replace("{day}",day).replace("{month}",day[:7]) for part in command]


def _validate_command(command: object, *, name: str) -> list[str]:
    if (not isinstance(command,list) or not command or
            not all(isinstance(part,str) and part for part in command)):
        raise DailyPttOrchestrationError(f"{name} command must be a non-empty JSON string array")
    return command


def _canonical_day(value: str, *, name: str) -> date:
    try:
        parsed=date.fromisoformat(value)
    except ValueError as exc:
        raise DailyPttOrchestrationError(f"{name} must be canonical YYYY-MM-DD") from exc
    if parsed.isoformat()!=value:
        raise DailyPttOrchestrationError(f"{name} must be canonical YYYY-MM-DD")
    return parsed


def pending_archive_days(*, state_root: Path, start_day: str,
                         through_day: str, limit: int) -> tuple[list[str],bool]:
    """Return closed days without a verified archive receipt, oldest first."""
    if limit<1 or limit>31:
        raise DailyPttOrchestrationError("catch-up limit must be between 1 and 31")
    start=_canonical_day(start_day,name="catch-up start day")
    through=_canonical_day(through_day,name="catch-up through day")
    if start>through:
        return [],False
    pending=[]
    cursor=start
    while cursor<=through:
        day=cursor.isoformat()
        receipt=state_root/"archive"/day/"archive-job.json"
        verified=False
        try:
            body=json.loads(receipt.read_text(encoding="utf-8"))
            verified=isinstance(body,dict) and body.get("job_verified") is True
        except (OSError,UnicodeDecodeError,json.JSONDecodeError):
            pass
        if not verified:
            pending.append(day)
        cursor+=timedelta(days=1)
    return pending[:limit],len(pending)>limit


def run_backlog_orchestration(
    *,
    gate_command: list[str],
    downstream_command: list[str],
    mode: str,
    state_root: Path,
    start_day: str,
    through_day: str,
    max_days: int=3,
    post_command: list[str] | None=None,
    command_runner: Callable[[list[str]],tuple[int,dict[str,Any]]] | None=None,
) -> dict[str,Any]:
    days,more=pending_archive_days(
        state_root=state_root,start_day=start_day,through_day=through_day,
        limit=max_days)
    receipts=[]
    for target_day in days:
        receipt=run_orchestration(
            gate_command=_expand_day(gate_command,target_day),
            downstream_command=_expand_day(downstream_command,target_day),
            mode=mode,command_runner=command_runner)
        receipts.append(receipt)
        if receipt.get("status")!="SUCCEEDED":
            return {
                "schema_version":SCHEMA_VERSION,
                "status":receipt.get("status","FAILED"),
                "day":target_day,
                "failure_code":receipt.get("failure_code","catch-up-day-failed"),
                "processed_days":[item.get("day") for item in receipts[:-1]],
                "failed_receipt":receipt,
                "pending_remaining":True,
            }
    post_receipt=None
    if post_command is not None and receipts:
        runner=command_runner or _run_json_command
        try:
            post_rc,post_receipt=runner(_expand_day(post_command,days[-1]))
        except DailyPttOrchestrationError as exc:
            return {
                "schema_version":SCHEMA_VERSION,"status":"FAILED",
                "day":days[-1],"failure_code":"post-command-output-invalid",
                "failure_stage":"monthly-release","failure_detail":str(exc),
                "processed_days":[item.get("day") for item in receipts],
                "pending_remaining":more,
            }
        allowed=(
            {"MONTHLY_RELEASE_DEPLOYED","MONTHLY_RELEASE_ALREADY_CURRENT"}
            if mode=="production" else
            {"MONTHLY_RELEASE_READY","MONTHLY_RELEASE_DEPLOYED",
             "MONTHLY_RELEASE_ALREADY_CURRENT"}
        )
        if post_rc!=0 or post_receipt.get("status") not in allowed:
            return {
                "schema_version":SCHEMA_VERSION,"status":"FAILED",
                "day":days[-1],"failure_code":post_receipt.get(
                    "failure_code","monthly-release-failed"),
                "failure_stage":"monthly-release",
                "processed_days":[item.get("day") for item in receipts],
                "pending_remaining":more,"post_receipt":post_receipt,
            }
    return {
        "schema_version":SCHEMA_VERSION,
        "status":"SUCCEEDED",
        "day":days[-1] if days else None,
        "processed_days":[item.get("day") for item in receipts],
        "pending_remaining":more,
        "catchup_noop":not days,
        "receipts":receipts,
        "post_receipt":post_receipt,
    }


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
    try:
        gate_rc,gate=runner(gate_command)
    except DailyPttOrchestrationError as exc:
        return _failed_command_receipt(stage="gate",day=None,exc=exc)

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
    try:
        parsed_gate_day=date.fromisoformat(gate_day) if isinstance(gate_day,str) else None
    except ValueError:
        parsed_gate_day=None
    if parsed_gate_day is None or gate_day!=parsed_gate_day.isoformat():
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

    try:
        downstream_rc,downstream=runner(downstream_command)
    except DailyPttOrchestrationError as exc:
        receipt=_failed_command_receipt(stage="downstream",day=gate_day,exc=exc)
        receipt.update({
            "mode":mode,"gate_returncode":gate_rc,
            "health_gate_passed":True,"gate_receipt":gate,
        })
        return receipt
    downstream_status=downstream.get("status")
    downstream_day=downstream.get("day")
    try:
        parsed_downstream_day=(
            date.fromisoformat(downstream_day)
            if isinstance(downstream_day,str)
            else None
        )
    except ValueError:
        parsed_downstream_day=None
    if parsed_downstream_day is None or downstream_day!=parsed_downstream_day.isoformat():
        success=False
        failure_code="downstream-day-invalid"
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
    parser.add_argument("--state-root")
    parser.add_argument("--catchup-start-day")
    parser.add_argument("--through-day")
    parser.add_argument("--max-days",type=int,default=3)
    parser.add_argument("--post-command-json")
    args=parser.parse_args(argv)

    try:
        gate_command=_validate_command(
            json.loads(args.gate_command_json),name="gate")
        downstream_command=_validate_command(
            json.loads(args.downstream_command_json),name="downstream")
        post_command=(
            _validate_command(json.loads(args.post_command_json),name="post")
            if args.post_command_json is not None else None)
        catchup_required=(args.state_root,args.catchup_start_day)
        if any(catchup_required) and not all(catchup_required):
            raise DailyPttOrchestrationError(
                "state-root and catchup-start-day must be provided together")
        if all(catchup_required):
            through_day=args.through_day or previous_taipei_day(
                datetime.now(ZoneInfo("Asia/Taipei")))
            body=run_backlog_orchestration(
                gate_command=gate_command,downstream_command=downstream_command,
                mode=args.mode,state_root=Path(args.state_root).expanduser(),
                start_day=args.catchup_start_day,through_day=through_day,
                max_days=args.max_days,post_command=post_command)
        else:
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
