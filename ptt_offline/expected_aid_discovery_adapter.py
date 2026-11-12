"""Pure adapter from sanitized Collector discovery receipts to expected-AID authority.

Consumes already-captured discovery metadata only. It never imports or calls the
networked thread_discovery module.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .data_lifecycle_evidence import build_expected_aid_contract


PERIOD_MAP={
    "日間":"day",
    "早間":"day",
    "晨間":"day",
    "晚間":"night",
    "夜間":"night",
    "本日":"all_day",
    "全日":"all_day",
    "全天":"all_day",
    "day":"day",
    "night":"night",
    "all_day":"all_day",
}


def expected_aids_from_discovery(*, day: str, targets: list[dict[str,Any]],
                                 authority: dict[str,Any]) -> dict[str,Any]:
    if not isinstance(targets,list):
        raise TypeError("sanitized discovery target list required")

    grouped=defaultdict(list)
    invalid=[]
    for raw in targets:
        if not isinstance(raw,dict):
            invalid.append(raw)
            continue
        period=PERIOD_MAP.get(raw.get("period"))
        if period is None:
            invalid.append(raw)
            continue
        grouped[period].append(raw)

    entries=[]
    for period in ("all_day","day","night"):
        ordered=sorted(
            grouped.get(period,[]),
            key=lambda row: (
                row.get("timestamp") if isinstance(row.get("timestamp"),int) else 0,
                str(row.get("aid") or ""),
            ),
        )
        for part,row in enumerate(ordered,start=1):
            entries.append({
                "period":period,
                "part":part,
                "aid":row.get("aid"),
                "source_url":row.get("url"),
                "authority_record_id":row.get("authority_record_id")
                    or f"discovery:{period}:{part}",
            })

    body=build_expected_aid_contract(day=day,entries=entries,authority=authority)
    if invalid:
        body["conflicts"]=sorted(set(body.get("conflicts",[])+[
            "unsupported-discovery-target"
        ]))
        body["status"]="CONFLICT"
    body["source_kind"]="sanitized-collector-discovery"
    body["discovery_target_count"]=len(targets)
    return body
