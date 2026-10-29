"""Read-only planner for delayed rows with full URL-epoch authority."""
import argparse
import json
from pathlib import Path

from .audit_baseline_gap import audit, _norm_aid
from .collector_source_preview import open_source
from .historical_baseline_authority import inspect_historical_article
from .plan_baseline_repair import DEFAULT_BATCH_CAP, _digest
from .public_today_contract import ContractError


def build_historical_plan(*,source,state,aid,remote_json,baseline_source_line,
                          batch_cap=DEFAULT_BATCH_CAP):
    if type(batch_cap) is not int or not 1<=batch_cap<=10:
        raise ContractError("repair batch cap must be 1..10")
    remote_body=json.loads(Path(remote_json).read_text(encoding="utf-8"))
    remote_lines=set()
    def collect_remote(value):
        if isinstance(value,dict):
            line=value.get("source_line")
            record_aid=value.get("aid")
            if (type(line) is int and line>0 and
                (record_aid is None or _norm_aid(record_aid)==_norm_aid(aid))):
                remote_lines.add(line)
            for child in value.values(): collect_remote(child)
        elif isinstance(value,list):
            for child in value: collect_remote(child)
    collect_remote(remote_body)
    # The generic audit remains useful for local/checkpoint classification,
    # but its legacy remote line set is not used for the historical plan:
    # source_line is unique only inside one AID.
    local=audit(source=source,state=state,aid=aid,remote_json=None,
                known_baseline_source_line=baseline_source_line)
    wanted=_norm_aid(aid)
    with open_source(source) as db:
        article=None
        for row in db.execute(
            "SELECT id,aid FROM articles WHERE board='C_Chat' ORDER BY id DESC"
        ).fetchall():
            if _norm_aid(row[1])==wanted:
                article=row
                break
        if article is None:
            raise ContractError("AID not found in Collector source")
        inspected=inspect_historical_article(db,article_id=article[0])

    ready={row["source_line"]:row for row in inspected["candidate_rows"]}
    local_lines={row["source_line"] for row in local["rows"]}
    missing=[line for line in range(local["collector_min_source_line"],
                                    baseline_source_line+1)
             if line in local_lines and line not in remote_lines]
    if any(line not in ready for line in missing):
        raise ContractError("missing baseline row lacks historical authority")
    batches=[]
    for index in range(0,len(missing),batch_cap):
        batch_rows=[{
            "source_line":line,
            "source_record_key":ready[line]["source_record_key"],
            "push_id":ready[line]["push_id"],
            "occurred_at":ready[line]["occurred_at"],
        } for line in missing[index:index+batch_cap]]
        batches.append({
            "batch_no":len(batches)+1,"rows":batch_rows,
            "row_count":len(batch_rows),"queue_digest":_digest(batch_rows),
        })
    return {
        "status":"READ_ONLY_HISTORICAL_REPAIR_PLAN",
        "authority":inspected["authority"],
        "aid":wanted,"source_identity":inspected["source_identity"],
        "baseline_source_line":baseline_source_line,
        "collector_rows":local["collector_rows"],
        "remote_source_lines":len(remote_lines),
        "missing_remote_baseline_rows":len(missing),
        "repairable_source_lines":missing,
        "batch_cap":batch_cap,"planned_batches":len(batches),"batches":batches,
        "coverage":{"start":inspected["coverage_start"],
                    "end":inspected["coverage_end"],
                    "source_rows":inspected["checked_source_rows"]},
        "preconditions":[
            "re-query remote D1 source evidence immediately before each approved batch",
            "re-verify full article coverage and URL-epoch chronology before send",
            "send at most one batch per explicit approval",
            "retry_cap=0; REMOTE_UNCERTAIN stops the repair",
            "do not alter the live Publisher checkpoint",
        ],
        "safety":{"remote_writes":0,"checkpoint_mutations":0,
                  "publisher_process_changes":0,"burst_enabled":False},
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only historical baseline repair planner")
    p.add_argument("--source",required=True); p.add_argument("--state",required=True)
    p.add_argument("--aid",required=True); p.add_argument("--remote-json",required=True)
    p.add_argument("--baseline-source-line",required=True,type=int)
    p.add_argument("--batch-cap",type=int,default=DEFAULT_BATCH_CAP)
    p.add_argument("--output")
    args=p.parse_args(argv)
    result=build_historical_plan(source=args.source,state=args.state,aid=args.aid,
        remote_json=args.remote_json,baseline_source_line=args.baseline_source_line,
        batch_cap=args.batch_cap)
    encoded=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)
    if args.output: Path(args.output).write_text(encoded+"\n",encoding="utf-8")
    print(encoded)


if __name__=="__main__": main()
