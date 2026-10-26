"""Read-only Collector SQLite -> sanitized PTT integrity evidence for PR #147.

This exporter reads only local Collector tables. It never logs in, contacts PTT,
starts/stops Collector/Publisher, or writes D1/R2. Raw article/push content and
authors are intentionally not emitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .collector_source_preview import open_source, verify_schema
from .data_lifecycle_evidence import (
    build_collector_semantic_evidence,
    build_source_coverage,
)
from .public_today_contract import ContractError, normalize_public_aid


SCHEMA_VERSION="holoviewer-ptt-collector-integrity-export-v1"


def _table_columns(db, table: str) -> set[str]:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def _merge_ranges(ranges: list[tuple[int,int]]) -> tuple[int|None,int|None,list[list[int]]]:
    if not ranges:
        return None,None,[]
    ordered=sorted((int(a),int(b)) for a,b in ranges)
    start=ordered[0][0]
    end=ordered[0][1]
    gaps=[]
    for a,b in ordered[1:]:
        if a>end+1:
            gaps.append([end+1,a-1])
        end=max(end,b)
    return start,end,gaps


def export_article_integrity(db, *, day: str, aid: str) -> dict[str,Any]:
    verify_schema(db)
    article_cols=_table_columns(db,"articles")
    screen_cols=_table_columns(db,"article_screens")
    required_screen={"article_id","start_line","end_line","captured_at"}
    if not required_screen.issubset(screen_cols):
        raise ContractError("article_screens coverage schema required")

    canonical=normalize_public_aid(aid)
    matches=db.execute(
        """SELECT id,aid,last_seen_at"""
        + (",last_source_line" if "last_source_line" in article_cols else "")
        + """ FROM articles WHERE board='C_Chat' AND aid IN (?,?)""",
        (canonical,"#"+canonical),
    ).fetchall()
    if len(matches)!=1:
        raise ContractError("exactly one Collector C_Chat article required")

    row=matches[0]
    article_id=int(row[0])
    stored_aid=row[1]
    last_seen_at=row[2]
    stored_final=row[3] if len(row)>3 else None

    ranges=db.execute(
        """SELECT start_line,end_line FROM article_screens
           WHERE article_id=? ORDER BY start_line,end_line""",
        (article_id,),
    ).fetchall()
    coverage_start,coverage_end,coverage_gaps=_merge_ranges(ranges)

    push_rows=db.execute(
        """SELECT source_line,kind,content FROM pushes
           WHERE article_id=? ORDER BY source_line""",
        (article_id,),
    ).fetchall()
    push_by_line={}
    duplicate_push_lines=[]
    for source_line,kind,content in push_rows:
        line=int(source_line)
        if line in push_by_line:
            duplicate_push_lines.append(line)
            continue
        push_by_line[line]={
            "kind":kind,
            "content_empty":content=="",
        }

    contract_gaps=[]
    conflicts=[]
    final_source_line=int(stored_final) if isinstance(stored_final,int) else coverage_end
    if stored_final is None:
        contract_gaps.append("collector-article-last-source-line-unavailable")
    if coverage_start is None:
        contract_gaps.append("collector-article-screen-coverage-unavailable")
    elif coverage_start!=1:
        contract_gaps.append("collector-coverage-does-not-start-at-line-1")
    if coverage_gaps:
        contract_gaps.append("collector-source-line-gap")
    if (isinstance(stored_final,int) and coverage_end is not None
            and coverage_end<stored_final):
        contract_gaps.append("collector-screen-coverage-behind-final-source-line")
    if (isinstance(stored_final,int) and coverage_end is not None
            and coverage_end>stored_final):
        conflicts.append("collector-screen-coverage-exceeds-final-source-line")
    if duplicate_push_lines:
        conflicts.append("duplicate-push-source-line")

    line_evidence=[]
    if coverage_start==1 and final_source_line is not None:
        gap_lines=set()
        for a,b in coverage_gaps:
            gap_lines.update(range(a,b+1))
        for line in range(1,final_source_line+1):
            if line in gap_lines or (coverage_end is not None and line>coverage_end):
                continue
            push=push_by_line.get(line)
            if push is None:
                line_evidence.append({
                    "source_line":line,
                    "record_type":"non_push",
                    "content_empty":None,
                    "legal_empty_push":False,
                })
            else:
                empty=bool(push["content_empty"])
                line_evidence.append({
                    "source_line":line,
                    "record_type":"push",
                    "content_empty":empty,
                    "legal_empty_push":empty,
                    "push_kind":push["kind"],
                })

    coverage=build_source_coverage(
        day=day,
        aid=canonical,
        article_start_line=1,
        final_source_line=final_source_line,
        lines=line_evidence,
    )
    coverage["contract_gaps"]=sorted(set(
        coverage.get("contract_gaps",[])+contract_gaps
    ))
    coverage["conflicts"]=sorted(set(
        coverage.get("conflicts",[])+conflicts
    ))
    if coverage["conflicts"]:
        coverage["status"]="CONFLICT"
    elif coverage["contract_gaps"]:
        coverage["status"]="REPAIR_NEEDED"

    observed_at=last_seen_at if isinstance(last_seen_at,str) else None
    semantic=build_collector_semantic_evidence(
        observed_at=observed_at,
        active_aid=canonical,
        watermark_source_line=coverage_end,
        final_source_line=final_source_line,
        source_line_gaps=coverage_gaps,
        scan_truncated=False,
        process_alive=None,
    )
    semantic["contract_gaps"]=sorted(set(
        semantic.get("contract_gaps",[])+contract_gaps
    ))
    if semantic["contract_gaps"] and semantic["semantic_check"]["status"]=="healthy":
        semantic["semantic_check"]["status"]="unknown"

    return {
        "schema_version":SCHEMA_VERSION,
        "sanitized":True,
        "day":day,
        "aid":canonical,
        "source_identity":{
            "board":"C_Chat",
            "aid":canonical,
            "article_id":article_id,
        },
        "source_coverage":coverage,
        "collector_semantic":semantic,
        "line_classification":{
            "raw_content_included":False,
            "raw_author_included":False,
            "total_classified":len(line_evidence),
            "push_count":sum(1 for x in line_evidence if x["record_type"]=="push"),
            "non_push_count":sum(1 for x in line_evidence if x["record_type"]=="non_push"),
            "legal_empty_push_count":sum(
                1 for x in line_evidence if x.get("legal_empty_push") is True
            ),
            "lines":line_evidence,
        },
        "contract_gaps":coverage["contract_gaps"],
        "conflicts":coverage["conflicts"],
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only sanitized Collector integrity export")
    p.add_argument("--source",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)
    with open_source(args.source) as db:
        body=export_article_integrity(db,day=args.day,aid=args.aid)
    out=Path(args.out)
    with out.open("x",encoding="utf-8") as handle:
        json.dump(body,handle,ensure_ascii=False,sort_keys=True,indent=2)
        handle.write("\n")
    print(json.dumps({
        "schema_version":body["schema_version"],
        "status":body["source_coverage"]["status"],
        "contract_gaps":body["contract_gaps"],
        "out":str(out),
    },ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
