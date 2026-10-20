"""Sanitized read-only PTT Data Lifecycle evidence contracts for PR #147.

This module validates already-sanitized evidence only. It performs no network,
SQLite, Publisher, Collector, D1 or R2 I/O and owns no production writer path.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any

SYNC_SCHEMA="holoviewer-sync-job-evidence-v1"
AID_SCHEMA="holoviewer-ptt-expected-aids-v1"
COVERAGE_SCHEMA="holoviewer-ptt-source-coverage-v1"
COLLECTOR_SCHEMA="holoviewer-collector-semantic-evidence-v1"
PERIODS=("day","night")
AID_RE=re.compile(r"^#?[A-Za-z0-9_-]{6,32}$")


def _iso(value: object) -> bool:
    if not isinstance(value,str):
        return False
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _digest(value: object) -> str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return sha256(raw).hexdigest()


def build_expected_aid_contract(*, day: str, entries: list[dict[str,Any]],
                                authority: dict[str,Any]) -> dict[str,Any]:
    """Require one authoritative day and one night AID for the Taipei day."""
    gaps=[]
    conflicts=[]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day):
        conflicts.append("invalid-day")
    if not isinstance(authority,dict) or authority.get("verified") is not True:
        gaps.append("expected-aid-authority-unverified")
    if not isinstance(authority.get("evidence_id") if isinstance(authority,dict) else None,str):
        gaps.append("expected-aid-authority-evidence-id-missing")
    normalized=[]
    seen_period=Counter()
    seen_aid=Counter()
    for item in entries if isinstance(entries,list) else []:
        if not isinstance(item,dict):
            conflicts.append("invalid-entry")
            continue
        period=item.get("period")
        aid=item.get("aid")
        seen_period[period]+=1
        seen_aid[aid]+=1
        if period not in PERIODS:
            conflicts.append("unsupported-period")
        if not isinstance(aid,str) or not AID_RE.fullmatch(aid):
            conflicts.append("invalid-aid")
        normalized.append({
            "day":day,
            "period":period,
            "aid":aid,
            "source_url":item.get("source_url"),
            "authority_record_id":item.get("authority_record_id"),
        })
    for period in PERIODS:
        if seen_period[period]==0:gaps.append(f"expected-{period}-aid-missing")
        elif seen_period[period]>1:conflicts.append(f"duplicate-{period}-aid")
    if any(n>1 for aid,n in seen_aid.items() if aid is not None):
        conflicts.append("duplicate-aid-across-periods")
    status="CONFLICT" if conflicts else "UNKNOWN" if gaps else "COMPLETE"
    body={
        "schema_version":AID_SCHEMA,
        "day":day,
        "status":status,
        "planning_key":["day","aid","source_line"],
        "expected":normalized,
        "authority":{
            "kind":authority.get("kind") if isinstance(authority,dict) else None,
            "evidence_id":authority.get("evidence_id") if isinstance(authority,dict) else None,
            "observed_at":authority.get("observed_at") if isinstance(authority,dict) else None,
            "verified":authority.get("verified") is True if isinstance(authority,dict) else False,
        },
        "contract_gaps":sorted(set(gaps)),
        "conflicts":sorted(set(conflicts)),
    }
    body["evidence_digest"]=_digest(body)
    return body


def build_source_coverage(*, day: str, aid: str, article_start_line: int,
                          final_source_line: int | None,
                          lines: list[dict[str,Any]]) -> dict[str,Any]:
    """Validate sanitized line-by-line evidence from article start to final line.

    record_type is push|non_push. Empty push content is legal only when
    legal_empty_push is explicitly true. Content itself is never required here.
    """
    conflicts=[]
    gaps=[]
    if article_start_line!=1:
        conflicts.append("article-start-not-line-1")
    if not isinstance(final_source_line,int) or final_source_line<article_start_line:
        gaps.append("final-source-line-unavailable")
        final_source_line=None
    by_line={}
    duplicate_lines=[]
    legal_empty=[]
    non_push=[]
    push=[]
    for row in lines if isinstance(lines,list) else []:
        if not isinstance(row,dict) or not isinstance(row.get("source_line"),int):
            conflicts.append("invalid-line-evidence")
            continue
        line=row["source_line"]
        if line in by_line:
            duplicate_lines.append(line)
            if by_line[line]!=row:
                conflicts.append("conflicting-duplicate-source-line")
            continue
        by_line[line]=row
        kind=row.get("record_type")
        if kind=="non_push":
            non_push.append(line)
        elif kind=="push":
            push.append(line)
            if row.get("content_empty") is True:
                if row.get("legal_empty_push") is True:
                    legal_empty.append(line)
                else:
                    conflicts.append("unclassified-empty-push")
        else:
            conflicts.append("unclassified-source-line")
    missing=[]
    if final_source_line is not None:
        missing=[n for n in range(article_start_line,final_source_line+1) if n not in by_line]
        if missing:gaps.append("source-line-gap")
        extras=[n for n in by_line if n<article_start_line or n>final_source_line]
        if extras:conflicts.append("source-line-outside-authoritative-range")
    complete=final_source_line is not None and not gaps and not conflicts
    body={
        "schema_version":COVERAGE_SCHEMA,
        "day":day,"aid":aid,
        "article_start_line":article_start_line,
        "final_source_line":final_source_line,
        "status":"COMPLETE" if complete else "CONFLICT" if conflicts else "REPAIR_NEEDED",
        "line_counts":{"total":len(by_line),"push":len(push),"non_push":len(non_push),
                       "legal_empty_push":len(legal_empty)},
        "missing_source_lines":missing,
        "duplicate_source_lines":sorted(set(duplicate_lines)),
        "legal_empty_push_source_lines":sorted(legal_empty),
        "non_push_source_lines":sorted(non_push),
        "contract_gaps":sorted(set(gaps)),
        "conflicts":sorted(set(conflicts)),
    }
    body["evidence_digest"]=_digest(body)
    return body


def build_collector_semantic_evidence(*, observed_at: str | None,
                                      active_aid: str | None,
                                      watermark_source_line: int | None,
                                      final_source_line: int | None,
                                      source_line_gaps: list[list[int]] | None,
                                      scan_truncated: bool | None,
                                      process_alive: bool | None=None) -> dict[str,Any]:
    gaps=[]
    if not _iso(observed_at):gaps.append("collector-observed-at-unavailable")
    if active_aid is None:gaps.append("collector-active-aid-unavailable")
    if watermark_source_line is None:gaps.append("collector-watermark-unavailable")
    if final_source_line is None:gaps.append("collector-final-source-line-unavailable")
    if source_line_gaps is None:gaps.append("collector-gap-evidence-unavailable")
    if scan_truncated is None:gaps.append("collector-scan-truncation-unknown")
    semantic_status=(
        "healthy" if not gaps and source_line_gaps==[] and scan_truncated is False
        else "degraded" if source_line_gaps
        else "unknown"
    )
    return {
        "schema_version":COLLECTOR_SCHEMA,
        "component":"Collector",
        "observed_at":observed_at,
        "process_alive":process_alive,
        "semantic_check":{
            "status":semantic_status,
            "active_aid":active_aid,
            "watermark_source_line":watermark_source_line,
            "final_source_line":final_source_line,
            "source_line_gaps":source_line_gaps,
            "scan_truncated":scan_truncated,
        },
        "contract_gaps":gaps,
    }
