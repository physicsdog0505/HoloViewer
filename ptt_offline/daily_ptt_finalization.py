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
    if (coverage.get("status")=="COMPLETE" and start_line==1
            and type(final_line) is int and final_line>=1 and not missing and not gaps):
        base["state"]="VERIFIED_COMPLETE"
        return base
    if (coverage.get("status")=="REPAIR_NEEDED" and start_line==1
            and type(final_line) is int and final_line>=1 and valid_missing and missing
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
    if expected_contract.get("day")!=day:
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
                refreshed=repair_executor(request)
                after=_classify_coverage(day=day,aid=aid,coverage=refreshed)
                result={
                    **after,
                    "repair_attempted":True,
                    "repair_request":request,
                    "repair_result":after["state"],
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
