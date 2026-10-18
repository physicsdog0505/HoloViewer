"""Owner-gated one-batch PTT floor enrichment sender.

This path only enriches existing canonical remote rows whose floor is NULL.
It never changes source identity, never replays a missing row, never mutates the
recurring Publisher checkpoint, and permits exactly one HTTP request with
retry_cap=0. A send is bound to an exact read-only floor plan batch digest.
"""
import argparse
import json
import os
from pathlib import Path

from .audit_baseline_gap import _norm_aid
from .collector_source_preview import open_source
from .floor_enrichment_plan import _remote_records
from .live_capture_publisher import inspect_latest_article, OUTPUT_KEYS
from .owner_publisher_once import sign_time_proof
from .owner_http_transport import owner_signed_http_executor
from .resumable_publisher import new_checkpoint, make_batch
from .d1_transport_contract import execute_once
from .public_today_contract import ContractError


def validate_batch(*,source,aid,plan_json,remote_json,batch_no,approved_digest):
    plan=json.loads(Path(plan_json).read_text(encoding="utf-8"))
    wanted=_norm_aid(aid)
    if plan.get("status")!="READ_ONLY_FLOOR_ENRICHMENT_PLAN" or _norm_aid(plan.get("aid"))!=wanted:
        raise ContractError("floor plan scope mismatch")
    batches=plan.get("batches")
    if not isinstance(batches,list) or type(batch_no) is not int or not 1<=batch_no<=len(batches):
        raise ContractError("floor batch outside approved plan")
    approved=batches[batch_no-1]
    if approved.get("batch_no")!=batch_no or approved.get("queue_digest")!=approved_digest:
        raise ContractError("explicit approved floor queue digest mismatch")
    planned=approved.get("rows")
    if not isinstance(planned,list) or not 1<=len(planned)<=10:
        raise ContractError("invalid bounded floor batch")

    remote=_remote_records(remote_json)
    remote_by_line={r.get("source_line"):r for r in remote if type(r.get("source_line")) is int}
    with open_source(source) as db:
        article=None
        for raw in db.execute("SELECT id,aid FROM articles WHERE board='C_Chat' ORDER BY id DESC"):
            if _norm_aid(raw[1])==wanted:
                article=raw[0]
                break
        if article is None:
            raise ContractError("AID not found in Collector source")
        current=inspect_latest_article(db,article_id=article)
    if current.get("source_identity")!=plan.get("source_identity"):
        raise ContractError("source identity changed since floor plan")
    if not current.get("floor_authoritative"):
        raise ContractError("floor authority no longer proven")
    ready={r["source_line"]:r for r in current.get("candidate_rows",[])}
    floor_map=current.get("floor_by_source_line",{})

    canonical=[]
    for expected in planned:
        line=expected.get("source_line")
        local=ready.get(line)
        remote_row=remote_by_line.get(line)
        if local is None or remote_row is None:
            raise ContractError("approved floor row no longer exists canonically")
        if remote_row.get("floor") is not None:
            if remote_row.get("floor")==expected.get("floor"):
                raise ContractError("approved floor row is already enriched remotely")
            raise ContractError("remote floor conflicts with approved floor")
        for key in ("source_record_key","push_id","occurred_at"):
            if local.get(key)!=expected.get(key):
                raise ContractError("approved floor row identity changed")
            if key in remote_row and remote_row.get(key) not in (None,expected.get(key)):
                raise ContractError("remote floor row identity conflict")
        floor=floor_map.get(line)
        if floor!=expected.get("floor"):
            raise ContractError("authoritative floor changed since plan")
        enriched=dict(local)
        enriched["floor"]=floor
        canonical.append(enriched)
    return plan,approved,current,canonical


def run_one(*,source,aid,plan_json,remote_json,batch_no,approved_digest,
            send=False,endpoint=None,receipt_path=None,executor=None,proof_secret=None):
    plan,approved,current,rows=validate_batch(
        source=source,aid=aid,plan_json=plan_json,remote_json=remote_json,
        batch_no=batch_no,approved_digest=approved_digest)
    result={
        "status":"READY_TO_ENRICH" if not send else "SEND_ATTEMPT",
        "aid":_norm_aid(aid),
        "source_identity":current["source_identity"],
        "batch_no":batch_no,
        "queue_digest":approved_digest,
        "rows":len(rows),
        "source_lines":[r["source_line"] for r in rows],
        "floors":[r["floor"] for r in rows],
        "retry_cap":0,
        "live_checkpoint_mutations":0,
        "http_requests":0,
    }
    if not send:
        return result
    if receipt_path is None:
        raise ContractError("isolated floor receipt path required for send")
    receipt=Path(receipt_path)
    if receipt.exists():
        previous=json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("status")=="REMOTE_UNCERTAIN":
            raise ContractError("previous floor enrichment outcome remote-uncertain")
        if previous.get("status")=="ACK":
            raise ContractError("approved floor enrichment batch already ACKed")
    if proof_secret is None:
        proof_secret=os.environ.get("PTT_TIME_AUTHORITY_SECRET","")
    if not isinstance(proof_secret,str) or len(proof_secret)<32:
        raise ContractError("time-proof secret unavailable")

    staged=[]
    for row in rows:
        signed=dict(row)
        signed["time_proof"]=sign_time_proof(signed,proof_secret)
        staged.append({k:signed.get(k) for k in OUTPUT_KEYS})
    checkpoint=new_checkpoint(source_identity=current["source_identity"],
                              day=staged[0]["day"],aids=[_norm_aid(aid)])
    batch=make_batch(checkpoint=checkpoint,rows=staged,batch_cap=len(staged))
    receipt.write_text(json.dumps({
        **result,"status":"REMOTE_UNCERTAIN",
        "transport_batch_id":batch["batch_id"],
        "transport_digest":batch["digest"],
    },ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")

    if executor is None:
        executor=owner_signed_http_executor(
            endpoint=endpoint or "",
            secret=os.environ.get("PTT_PUBLISH_HMAC_SECRET",""),
            allow_write=True,max_rows=10,max_bytes=131072)
    ack=execute_once(batch=batch,executor=executor,max_rows=10,max_queries=60,max_written=24)
    final={
        **result,"status":"ACK",
        "http_requests":ack["http_requests"],
        "logical_rows_acked":ack["logical_rows_acked"],
        "d1_query_count":ack["d1_query_count"],
        "d1_rows_written":ack["d1_rows_written"],
        "transport_batch_id":batch["batch_id"],
        "transport_digest":batch["digest"],
    }
    receipt.write_text(json.dumps(final,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return final


def main(argv=None):
    p=argparse.ArgumentParser(description="Owner-gated one-batch PTT display-floor enrichment")
    p.add_argument("--source",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--plan-json",required=True)
    p.add_argument("--remote-json",required=True)
    p.add_argument("--batch-no",required=True,type=int)
    p.add_argument("--approve-batch-digest",required=True)
    p.add_argument("--inspect",action="store_true")
    p.add_argument("--send",action="store_true")
    p.add_argument("--endpoint")
    p.add_argument("--receipt")
    args=p.parse_args(argv)
    if args.inspect==args.send:
        p.error("choose exactly one of --inspect or --send")
    result=run_one(source=args.source,aid=args.aid,plan_json=args.plan_json,
        remote_json=args.remote_json,batch_no=args.batch_no,
        approved_digest=args.approve_batch_digest,send=args.send,
        endpoint=args.endpoint,receipt_path=args.receipt)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
