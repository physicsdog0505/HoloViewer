"""Daily previous-day PTT finalization orchestration for #48.

Pure orchestration only:
- consumes an authoritative expected-AID contract and sanitized per-AID coverage;
- classifies each expected thread;
- emits bounded missing ranges only for VERIFIED repairable gaps;
- optionally invokes an injected repair executor;
- re-runs the same classifier after repair;
- never logs in, scans PTT, controls Collector/Publisher, or writes D1/R2 by itself.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .data_lifecycle_evidence import AID_SCHEMA, COVERAGE_SCHEMA

SCHEMA_VERSION="holoviewer-ptt-daily-finalization-v1"
TAIPEI=ZoneInfo("Asia/Taipei")
STATES=("VERIFIED_COMPLETE","REPAIR_NEEDED","UNKNOWN","CONFLICT")
REPAIRABLE_COVERAGE_GAPS={
    "source-line-gap",
    "collector-source-line-gap",
    "collector-screen-coverage-behind-local-tail",
}


def _digest(value: object) -> str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return sha256(raw).hexdigest()


def previous_taipei_day(now: datetime | None=None) -> str:
    current=now or datetime.now(TAIPEI)
    if current.tzinfo is None:
        raise ValueError("timezone-aware now required")
    return (current.astimezone(TAIPEI).date()-timedelta(days=1)).isoformat()


def _ranges(lines: list[int]) -> list[list[int]]:
    ordered=sorted(set(lines))
    if not ordered:
        return []
    out=[]
    start=end=ordered[0]
    for line in ordered[1:]:
        if line==end+1:
            end=line
            continue
        out.append([start,end])
        start=end=line
    out.append([start,end])
    return out


def _classify_expected(expected: dict[str,Any]) -> tuple[str,list[str],list[str]]:
    gaps=[]
    conflicts=[]
    if not isinstance(expected,dict) or expected.get("schema_version")!=AID_SCHEMA:
        return "UNKNOWN",["expected-aid-contract-unavailable"],[]
    conflicts.extend(expected.get("conflicts",[]) if isinstance(expected.get("conflicts"),list) else [])
    gaps.extend(expected.get("contract_gaps",[]) if isinstance(expected.get("contract_gaps"),list) else [])
    authority=expected.get("authority") if isinstance(expected.get("authority"),dict) else {}
    if expected.get("status")=="CONFLICT" or conflicts:
        return "CONFLICT",sorted(set(gaps)),sorted(set(conflicts))
    if (expected.get("status")!="COMPLETE" or authority.get("verified") is not True
            or authority.get("day")!=expected.get("day")):
        if not gaps:
            gaps.append("expected-aid-authority-not-complete")
        return "UNKNOWN",sorted(set(gaps)),[]
    rows=expected.get("expected")
    if not isinstance(rows,list) or not rows:
        return "UNKNOWN",["expected-aid-set-empty"],[]
    return "VERIFIED_COMPLETE",[],[]


def _classify_coverage(*,day: str,aid: str,coverage: dict[str,Any] | None) -> dict[str,Any]:
    base={
        "aid":aid,
        "state":"UNKNOWN",
        "repairable":False,
        "repair_ranges":[],
        "missing_source_lines":[],
        "coverage_digest":None,
        "contract_gaps":[],
        "conflicts":[],
    }
    if not isinstance(coverage,dict):
        base["contract_gaps"]=["coverage-unavailable"]
        return base
    base["coverage_digest"]=coverage.get("evidence_digest")
    if coverage.get("schema_version")!=COVERAGE_SCHEMA:
        base["contract_gaps"]=["coverage-schema-mismatch"]
        return base
    if coverage.get("day")!=day or str(coverage.get("aid") or "").lstrip("#")!=str(aid).lstrip("#"):
        base["state"]="CONFLICT"
        base["conflicts"]=["coverage-identity-mismatch"]
        return base
    conflicts=coverage.get("conflicts") if isinstance(coverage.get("conflicts"),list) else []
    gaps=coverage.get("contract_gaps") if isinstance(coverage.get("contract_gaps"),list) else []
    missing=coverage.get("missing_source_lines") if isinstance(coverage.get("missing_source_lines"),list) else []
    valid_missing=(
        all(type(x) is int and x>=1 for x in missing)
        and len(missing)==len(set(missing))
    )
    final_line=coverage.get("final_source_line")
    start_line=coverage.get("article_start_line")
    if conflicts or coverage.get("status")=="CONFLICT":
        base.update(state="CONFLICT",conflicts=sorted(set(conflicts or ["coverage-conflict"])),
                    contract_gaps=sorted(set(gaps)))
        return base
    tail_parity=coverage.get("tail_parity_confirmed")
    if (coverage.get("status")=="COMPLETE" and start_line==1
            and type(final_line) is int and final_line>=1 and not missing and not gaps
            and tail_parity is True):
        base["state"]="VERIFIED_COMPLETE"
        return base
    if coverage.get("status")=="COMPLETE" and tail_parity is not True:
        base["contract_gaps"]=["authoritative-tail-parity-unconfirmed"]
        return base
    repair_gaps=set(gaps)
    repair_authority_complete=repair_gaps.issubset(REPAIRABLE_COVERAGE_GAPS)
    if (coverage.get("status")=="REPAIR_NEEDED" and start_line==1
            and type(final_line) is int and final_line>=1 and valid_missing and missing
            and repair_authority_complete
            and all(1<=line<=final_line for line in missing)):
        base.update(
            state="REPAIR_NEEDED",
            repairable=True,
            repair_ranges=_ranges(missing),
            missing_source_lines=sorted(missing),
            contract_gaps=sorted(set(gaps)),
        )
        return base
    base["contract_gaps"]=sorted(set(gaps or ["coverage-authority-incomplete"]))
    return base


def finalize_day(
    *,
    day: str,
    expected_contract: dict[str,Any],
    coverage_by_aid: dict[str,dict[str,Any]],
    repair_executor: Callable[[dict[str,Any]],dict[str,Any]] | None=None,
    observed_at: str | None=None,
) -> dict[str,Any]:
    expected_state,expected_gaps,expected_conflicts=_classify_expected(expected_contract)
    if not isinstance(expected_contract,dict) or expected_contract.get("day")!=day:
        expected_state="CONFLICT"
        expected_conflicts=sorted(set(expected_conflicts+["expected-day-mismatch"]))

    expected_rows=expected_contract.get("expected",[]) if isinstance(expected_contract,dict) else []
    expected_aids=[
        str(row.get("aid")).lstrip("#")
        for row in expected_rows if isinstance(row,dict) and isinstance(row.get("aid"),str)
    ] if expected_state=="VERIFIED_COMPLETE" else []

    thread_results=[]
    repair_attempts=0
    if expected_state=="VERIFIED_COMPLETE":
        for aid in expected_aids:
            initial=_classify_coverage(day=day,aid=aid,coverage=coverage_by_aid.get(aid)
                                       or coverage_by_aid.get("#"+aid))
            result={**initial,"repair_attempted":False,"repair_result":None}
            if initial["state"]=="REPAIR_NEEDED" and initial["repairable"] and repair_executor:
                request={
                    "day":day,
                    "aid":aid,
                    "missing_source_lines":initial["missing_source_lines"],
                    "repair_ranges":initial["repair_ranges"],
                    "mode":"bounded-missing-ranges-only",
                }
                repair_attempts+=1
                try:
                    refreshed=repair_executor(request)
                except Exception as exc:
                    result={
                        **initial,
                        "repair_attempted":True,
                        "repair_request":request,
                        "repair_result":"FAILED",
                        "repair_failure_code":"repair-executor-"+type(exc).__name__,
                        "pre_repair_state":initial["state"],
                        "pre_repair_coverage_digest":initial["coverage_digest"],
                    }
                else:
                    after=_classify_coverage(day=day,aid=aid,coverage=refreshed)
                    result={
                        **after,
                        "repair_attempted":True,
                        "repair_request":request,
                        "repair_result":after["state"],
                        "repair_failure_code":None,
                        "pre_repair_state":initial["state"],
                        "pre_repair_coverage_digest":initial["coverage_digest"],
                    }
            thread_results.append(result)

    states=[row["state"] for row in thread_results]
    if expected_state=="CONFLICT":
        final_state="CONFLICT"
    elif expected_state!="VERIFIED_COMPLETE":
        final_state="UNKNOWN"
    elif any(state=="CONFLICT" for state in states):
        final_state="CONFLICT"
    elif any(state=="UNKNOWN" for state in states):
        final_state="UNKNOWN"
    elif any(state=="REPAIR_NEEDED" for state in states):
        final_state="REPAIR_NEEDED"
    elif states and all(state=="VERIFIED_COMPLETE" for state in states):
        final_state="VERIFIED_COMPLETE"
    else:
        final_state="UNKNOWN"

    contract_gaps=list(expected_gaps)
    conflicts=list(expected_conflicts)
    for row in thread_results:
        contract_gaps.extend(row.get("contract_gaps",[]))
        conflicts.extend(row.get("conflicts",[]))

    body={
        "schema_version":SCHEMA_VERSION,
        "sanitized":True,
        "day":day,
        "state":final_state,
        "observed_at":observed_at,
        "expected_set":{
            "schema_version":expected_contract.get("schema_version") if isinstance(expected_contract,dict) else None,
            "status":expected_contract.get("status") if isinstance(expected_contract,dict) else None,
            "evidence_digest":expected_contract.get("evidence_digest") if isinstance(expected_contract,dict) else None,
            "authority":expected_contract.get("authority") if isinstance(expected_contract,dict) else None,
            "expected_aids":expected_aids if expected_state=="VERIFIED_COMPLETE" else None,
        },
        "threads":thread_results,
        "summary":{
            "expected_threads":len(expected_aids),
            "verified_complete":states.count("VERIFIED_COMPLETE"),
            "repair_needed":states.count("REPAIR_NEEDED"),
            "unknown":states.count("UNKNOWN"),
            "conflict":states.count("CONFLICT"),
            "repair_attempts":repair_attempts,
        },
        "archive_ready":final_state=="VERIFIED_COMPLETE",
        "pr147_ready":final_state=="VERIFIED_COMPLETE",
        "contract_gaps":sorted(set(contract_gaps)),
        "conflicts":sorted(set(conflicts)),
        "safety":{
            "blind_recrawl":False,
            "whole_day_rescan":False,
            "collector_restart":False,
            "publisher_restart":False,
            "checkpoint_reset":False,
        },
    }
    body["evidence_digest"]=_digest(body)
    return body


def finalize_previous_day(
    *,
    expected_contract: dict[str,Any],
    coverage_by_aid: dict[str,dict[str,Any]],
    now: datetime | None=None,
    repair_executor: Callable[[dict[str,Any]],dict[str,Any]] | None=None,
) -> dict[str,Any]:
    local_now=(now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    return finalize_day(
        day=previous_taipei_day(local_now),
        expected_contract=expected_contract,
        coverage_by_aid=coverage_by_aid,
        repair_executor=repair_executor,
        observed_at=local_now.isoformat(),
    )


def classify_collector_health(health: dict[str,Any] | None) -> dict[str,Any]:
    """Normalize the 07:30 Collector health gate without performing recovery."""
    required=("process_alive","heartbeat_fresh","live_context_valid","frontier_progressing")
    if not isinstance(health,dict):
        return {
            "status":"UNHEALTHY",
            "healthy":False,
            "failure_codes":["collector-health-unavailable"],
            "live_aid":None,
            "frontier":None,
        }
    failures=[]
    for key in required:
        if health.get(key) is not True:
            failures.append({
                "process_alive":"collector-process-dead",
                "heartbeat_fresh":"collector-heartbeat-stale",
                "live_context_valid":"collector-live-context-invalid",
                "frontier_progressing":"collector-frontier-stalled",
            }[key])
    return {
        "status":"HEALTHY" if not failures else "UNHEALTHY",
        "healthy":not failures,
        "failure_codes":failures,
        "live_aid":health.get("live_aid"),
        "frontier":health.get("frontier"),
    }


def run_0730_closeout(
    *,
    expected_contract: dict[str,Any],
    coverage_by_aid: dict[str,dict[str,Any]],
    collector_health_probe: Callable[[],dict[str,Any]],
    now: datetime | None=None,
    repair_executor: Callable[[dict[str,Any]],dict[str,Any]] | None=None,
    recovery_executor: Callable[[],dict[str,Any]] | None=None,
    return_to_live_executor: Callable[[dict[str,Any]],dict[str,Any]] | None=None,
) -> dict[str,Any]:
    """07:30 fail-closed orchestration with at most one Collector recovery.

    All runtime-affecting actions are injected. This function never logs in,
    starts/stops Collector, clears DB, resets checkpoints, or publishes archive.
    """
    local_now=(now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    observed_at=local_now.isoformat()

    raw_before=collector_health_probe()
    health_before=classify_collector_health(raw_before)
    saved_live_context={
        "live_aid":health_before.get("live_aid"),
        "frontier":health_before.get("frontier"),
    }

    restart_attempted=False
    restart_result=None
    raw_after=raw_before
    if not health_before["healthy"]:
        if recovery_executor is None:
            return {
                "schema_version":SCHEMA_VERSION,
                "day":previous_taipei_day(local_now),
                "state":"UNKNOWN",
                "observed_at":observed_at,
                "collector_health_before":health_before,
                "restart_attempted":False,
                "restart_result":"NOT_AVAILABLE",
                "collector_health_after":health_before,
                "resolved_live_aid":health_before.get("live_aid"),
                "resolved_live_frontier":health_before.get("frontier"),
                "previous_day_result":None,
                "repair_result":None,
                "return_to_live_result":"NOT_RUN",
                "archive_ready":False,
                "pr147_ready":False,
                "failure_code":"collector-unhealthy-no-controlled-recovery",
                "safety":{
                    "restart_attempts":0,
                    "checkpoint_reset":False,
                    "db_clear":False,
                    "duplicate_collector_launch":False,
                    "auto_login":False,
                },
            }
        restart_attempted=True
        try:
            recovery_result=recovery_executor()
        except Exception as exc:
            return {
                "schema_version":SCHEMA_VERSION,
                "day":previous_taipei_day(local_now),
                "state":"UNKNOWN",
                "observed_at":observed_at,
                "collector_health_before":health_before,
                "restart_attempted":True,
                "restart_result":"FAILED",
                "collector_health_after":None,
                "resolved_live_aid":None,
                "resolved_live_frontier":None,
                "previous_day_result":None,
                "repair_result":None,
                "return_to_live_result":"NOT_RUN",
                "archive_ready":False,
                "pr147_ready":False,
                "failure_code":"collector-recovery-"+type(exc).__name__,
                "safety":{
                    "restart_attempts":1,
                    "checkpoint_reset":False,
                    "db_clear":False,
                    "duplicate_collector_launch":False,
                    "auto_login":False,
                },
            }
        restart_result=(
            recovery_result.get("status")
            if isinstance(recovery_result,dict) else "ATTEMPTED"
        )
        raw_after=collector_health_probe()

    health_after=classify_collector_health(raw_after)
    if not health_after["healthy"]:
        return {
            "schema_version":SCHEMA_VERSION,
            "day":previous_taipei_day(local_now),
            "state":"UNKNOWN",
            "observed_at":observed_at,
            "collector_health_before":health_before,
            "restart_attempted":restart_attempted,
            "restart_result":restart_result,
            "collector_health_after":health_after,
            "resolved_live_aid":health_after.get("live_aid"),
            "resolved_live_frontier":health_after.get("frontier"),
            "previous_day_result":None,
            "repair_result":None,
            "return_to_live_result":"NOT_RUN",
            "archive_ready":False,
            "pr147_ready":False,
            "failure_code":"collector-health-not-restored",
            "safety":{
                "restart_attempts":1 if restart_attempted else 0,
                "checkpoint_reset":False,
                "db_clear":False,
                "duplicate_collector_launch":False,
                "auto_login":False,
            },
        }

    resolved_live_context={
        "live_aid":health_after.get("live_aid"),
        "frontier":health_after.get("frontier"),
    }
    finalization=finalize_previous_day(
        expected_contract=expected_contract,
        coverage_by_aid=coverage_by_aid,
        now=local_now,
        repair_executor=repair_executor,
    )

    repair_attempted=finalization.get("summary",{}).get("repair_attempts",0)>0
    return_result="NOT_REQUIRED"
    return_ok=True
    if repair_attempted:
        if return_to_live_executor is None:
            return_ok=False
            return_result="NOT_AVAILABLE"
        else:
            try:
                restored=return_to_live_executor(resolved_live_context)
            except Exception as exc:
                return_ok=False
                return_result="FAILED:"+type(exc).__name__
            else:
                restored_health=classify_collector_health(restored)
                same_live=(
                    restored_health.get("live_aid")==resolved_live_context.get("live_aid")
                    and restored_health.get("frontier") is not None
                )
                return_ok=restored_health["healthy"] and same_live
                return_result="PASS" if return_ok else "FAILED"

    archive_ready=bool(finalization.get("archive_ready")) and return_ok
    state=finalization.get("state") if archive_ready or finalization.get("state")!="VERIFIED_COMPLETE" else "UNKNOWN"
    failure_code=None
    if finalization.get("state")=="VERIFIED_COMPLETE" and not return_ok:
        failure_code="return-to-live-failed"

    return {
        "schema_version":SCHEMA_VERSION,
        "day":finalization.get("day"),
        "state":state,
        "observed_at":observed_at,
        "collector_health_before":health_before,
        "restart_attempted":restart_attempted,
        "restart_result":restart_result,
        "collector_health_after":health_after,
        "resolved_live_aid":resolved_live_context.get("live_aid"),
        "resolved_live_frontier":resolved_live_context.get("frontier"),
        "previous_day_result":finalization,
        "repair_result":{
            "attempts":finalization.get("summary",{}).get("repair_attempts",0),
            "state":finalization.get("state"),
        },
        "return_to_live_result":return_result,
        "archive_ready":archive_ready,
        "pr147_ready":archive_ready,
        "failure_code":failure_code,
        "safety":{
            "restart_attempts":1 if restart_attempted else 0,
            "checkpoint_reset":False,
            "db_clear":False,
            "duplicate_collector_launch":False,
            "auto_login":False,
        },
    }
