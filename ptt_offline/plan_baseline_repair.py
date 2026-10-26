"""Read-only controlled repair planner for baseline-skipped PTT rows.

Builds an explicit queue from Collector rows that are absent from a supplied
remote D1 source-line export. It never sends, mutates Publisher checkpoints,
or changes Cloudflare. Rows that cannot currently establish canonical
occurred_at remain pending and are excluded from executable batches.
"""
import argparse
import json
from hashlib import sha256
from pathlib import Path

from .audit_baseline_gap import audit, load_remote_lines, _norm_aid
from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article
from .public_today_contract import ContractError

DEFAULT_BATCH_CAP=10


def _digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def build_plan(*,source,state,aid,remote_json,baseline_source_line,batch_cap=DEFAULT_BATCH_CAP):
    if type(batch_cap) is not int or not 1<=batch_cap<=10:
        raise ContractError("repair batch cap must be 1..10")
    remote_lines=load_remote_lines(remote_json)
    if remote_lines is None:
        raise ContractError("remote source-line evidence required")
    local=audit(source=source,state=state,aid=aid,remote_json=remote_json,
                known_baseline_source_line=baseline_source_line)
    wanted=_norm_aid(aid)
    with open_source(source) as db:
        article=None
        for row in db.execute(
            "SELECT id,aid,url FROM articles WHERE board='C_Chat' ORDER BY id DESC"
        ).fetchall():
            if _norm_aid(row[1])==wanted:
                article=row
                break
        if article is None:
            raise ContractError("AID not found in Collector source")
        plan=inspect_latest_article(db,article_id=article[0])

    ready_by_line={row["source_line"]:row for row in plan.get("candidate_rows",[])}
    missing_remote=[
        line for line in range(local["collector_min_source_line"],baseline_source_line+1)
        if line not in remote_lines
        and any(r["source_line"]==line for r in local["rows"])
    ]
    repairable=[line for line in missing_remote if line in ready_by_line]
    pending=[line for line in missing_remote if line not in ready_by_line]

    batches=[]
    for index in range(0,len(repairable),batch_cap):
        lines=repairable[index:index+batch_cap]
        batch_rows=[]
        for line in lines:
            row=ready_by_line[line]
            batch_rows.append({
                "source_line":line,
                "source_record_key":row["source_record_key"],
                "push_id":row["push_id"],
                "occurred_at":row["occurred_at"],
            })
        batches.append({
            "batch_no":len(batches)+1,
            "rows":batch_rows,
            "row_count":len(batch_rows),
            "queue_digest":_digest(batch_rows),
        })

    return {
        "status":"READ_ONLY_REPAIR_PLAN",
        "aid":wanted,
        "source_identity":plan["source_identity"],
        "baseline_source_line":baseline_source_line,
        "collector_rows":local["collector_rows"],
        "remote_source_lines":len(remote_lines),
        "missing_remote_baseline_rows":len(missing_remote),
        "repairable_ready_rows":len(repairable),
        "pending_rows":len(pending),
        "repairable_source_lines":repairable,
        "pending_source_lines":pending,
        "batch_cap":batch_cap,
        "planned_batches":len(batches),
        "batches":batches,
        "preconditions":[
            "re-query remote D1 source evidence immediately before each approved batch",
            "drop any row that already exists remotely by source_record_key/source_line",
            "send at most one batch per explicit approval",
            "retry_cap=0; REMOTE_UNCERTAIN stops the repair",
            "do not alter the live Publisher checkpoint",
            "do not send pending/non-canonical rows",
        ],
        "abort_conditions":[
            "remote source evidence conflicts with the planned push_id",
            "source identity changes",
            "Publisher enters REMOTE_UNCERTAIN",
            "approved batch exceeds 10 rows",
            "any row loses canonical occurred_at authority",
        ],
        "safety":{
            "remote_writes":0,
            "checkpoint_mutations":0,
            "publisher_process_changes":0,
            "burst_enabled":False,
        },
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only baseline repair queue planner")
    p.add_argument("--source",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--remote-json",required=True)
    p.add_argument("--baseline-source-line",required=True,type=int)
    p.add_argument("--batch-cap",type=int,default=DEFAULT_BATCH_CAP)
    p.add_argument("--output")
    args=p.parse_args(argv)
    result=build_plan(source=args.source,state=args.state,aid=args.aid,
                      remote_json=args.remote_json,
                      baseline_source_line=args.baseline_source_line,
                      batch_cap=args.batch_cap)
    encoded=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)
    if args.output:
        Path(args.output).write_text(encoded+"\n",encoding="utf-8")
    print(encoded)


if __name__=="__main__":
    main()
