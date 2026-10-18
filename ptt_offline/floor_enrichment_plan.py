"""Read-only planner for authoritative PTT floor enrichment.

Floor means the 1-based push ordinal within one PTT article/AID. It is derived
only when Collector proves article-start coverage (page 1), the full scan is
not truncated, and source_line ordering is unique/monotonic. source_line itself
is never exposed as floor.

The planner compares current Collector identity against a fresh remote D1 JSON
snapshot and produces bounded, digest-bound batches for rows whose remote floor
is still NULL. It performs no remote writes and does not mutate the recurring
Publisher checkpoint.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from .audit_baseline_gap import _norm_aid
from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article
from .public_today_contract import ContractError


def _remote_records(path):
    body=json.loads(Path(path).read_text(encoding="utf-8"))
    records=[]
    def walk(value):
        if isinstance(value,dict):
            if type(value.get("source_line")) is int:
                records.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value,list):
            for child in value:
                walk(child)
    walk(body)
    return records


def _queue_digest(aid,source_identity,rows):
    material=[aid,source_identity,[
        [r["source_line"],r["source_record_key"],r["push_id"],r["occurred_at"],r["floor"]]
        for r in rows
    ]]
    return sha256(json.dumps(material,ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()


def build_plan(*,source,aid,remote_json,batch_cap=10):
    if type(batch_cap) is not int or not 1<=batch_cap<=10:
        raise ContractError("floor enrichment batch cap must be 1..10")
    wanted=_norm_aid(aid)
    with open_source(source) as db:
        article=None
        for row in db.execute("SELECT id,aid FROM articles WHERE board='C_Chat' ORDER BY id DESC"):
            if _norm_aid(row[1])==wanted:
                article=row[0]
                break
        if article is None:
            raise ContractError("AID not found in Collector source")
        current=inspect_latest_article(db,article_id=article)
    if not current.get("floor_authoritative"):
        raise ContractError("Collector article-start coverage is insufficient for floor authority")

    ready={row["source_line"]:row for row in current.get("candidate_rows",[])}
    floor_map=current.get("floor_by_source_line",{})
    remote=_remote_records(remote_json)
    candidates=[]
    already=0
    skipped_noncanonical=0
    seen=set()
    for remote_row in remote:
        if "aid" in remote_row and _norm_aid(remote_row.get("aid"))!=wanted:
            continue
        line=remote_row.get("source_line")
        if line in seen:
            raise ContractError("duplicate remote source_line in floor snapshot")
        seen.add(line)
        local=ready.get(line)
        if local is None:
            skipped_noncanonical+=1
            continue
        expected_floor=floor_map.get(line)
        if type(expected_floor) is not int or expected_floor<1:
            raise ContractError("authoritative floor missing for canonical row")
        if remote_row.get("push_id") not in (None,local["push_id"]):
            raise ContractError("remote push identity conflicts with Collector")
        if remote_row.get("source_record_key") not in (None,local["source_record_key"]):
            raise ContractError("remote source-record identity conflicts with Collector")
        remote_floor=remote_row.get("floor")
        if remote_floor is None:
            candidates.append({
                "source_line":line,
                "source_record_key":local["source_record_key"],
                "push_id":local["push_id"],
                "occurred_at":local["occurred_at"],
                "floor":expected_floor,
            })
        elif remote_floor==expected_floor:
            already+=1
        else:
            raise ContractError("remote floor conflicts with authoritative Collector ordinal")

    candidates.sort(key=lambda row:row["source_line"])
    batches=[]
    for offset in range(0,len(candidates),batch_cap):
        rows=candidates[offset:offset+batch_cap]
        batches.append({
            "batch_no":len(batches)+1,
            "rows":rows,
            "queue_digest":_queue_digest(wanted,current["source_identity"],rows),
        })
    return {
        "status":"READ_ONLY_FLOOR_ENRICHMENT_PLAN",
        "aid":wanted,
        "source_identity":current["source_identity"],
        "floor_authoritative":True,
        "remote_rows_examined":len(remote),
        "already_enriched":already,
        "skipped_noncanonical":skipped_noncanonical,
        "enrichment_rows":len(candidates),
        "batch_cap":batch_cap,
        "planned_batches":len(batches),
        "batches":batches,
        "remote_writes":0,
        "checkpoint_mutations":0,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only PTT display-floor enrichment planner")
    p.add_argument("--source",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--remote-json",required=True)
    p.add_argument("--batch-cap",type=int,default=10)
    p.add_argument("--output")
    args=p.parse_args(argv)
    result=build_plan(source=args.source,aid=args.aid,remote_json=args.remote_json,batch_cap=args.batch_cap)
    text=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if args.output:
        Path(args.output).write_text(text,encoding="utf-8")
    print(text,end="")


if __name__=="__main__":
    main()
