"""Owner-gated one-batch baseline repair sender.

Default is read-only validation. A real send requires:
- an exact planner batch digest approved on the command line;
- a freshly exported remote D1 JSON snapshot;
- the exact current Collector row identities to match the approved plan;
- existing owner HMAC/time-proof secrets;
- exactly one HTTP request, retry_cap=0.

This path never mutates the live recurring Publisher checkpoint. It writes only
an isolated repair receipt when --send is explicitly approved.
"""
import argparse
import json
import os
from pathlib import Path

from .audit_baseline_gap import _collect_source_lines, _norm_aid
from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article, OUTPUT_KEYS
from .historical_baseline_authority import inspect_historical_article
from .owner_publisher_once import sign_time_proof
from .owner_http_transport import owner_signed_http_executor
from .resumable_publisher import new_checkpoint, make_batch
from .d1_transport_contract import execute_once
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


def validate_approved_batch(*,source,aid,plan_json,remote_json,batch_no,approved_digest):
    if type(batch_no) is not int or batch_no<1:
        raise ContractError("positive repair batch number required")
    plan=json.loads(Path(plan_json).read_text(encoding="utf-8"))
    plan_status=plan.get("status")
    if (plan_status not in ("READ_ONLY_REPAIR_PLAN","READ_ONLY_HISTORICAL_REPAIR_PLAN") or
        _norm_aid(plan.get("aid"))!=_norm_aid(aid)):
        raise ContractError("repair plan scope mismatch")
    batches=plan.get("batches")
    if not isinstance(batches,list) or batch_no>len(batches):
        raise ContractError("repair batch outside approved plan")
    approved=batches[batch_no-1]
    if approved.get("batch_no")!=batch_no or approved.get("queue_digest")!=approved_digest:
        raise ContractError("explicit approved queue digest mismatch")
    planned=approved.get("rows")
    if not isinstance(planned,list) or not 1<=len(planned)<=10:
        raise ContractError("invalid approved bounded repair batch")

    wanted=_norm_aid(aid)
    remote=[r for r in _remote_records(remote_json)
            if r.get("aid") is None or _norm_aid(r.get("aid"))==wanted]
    remote_by_line={r.get("source_line"):r for r in remote if type(r.get("source_line")) is int}
    remote_by_key={r.get("source_record_key"):r for r in remote if isinstance(r.get("source_record_key"),str)}
    for row in planned:
        line=row.get("source_line")
        key=row.get("source_record_key")
        pid=row.get("push_id")
        if line in remote_by_line:
            existing=remote_by_line[line]
            if existing.get("push_id") not in (None,pid):
                raise ContractError("remote source-line identity conflict")
            raise ContractError("approved repair row already exists remotely")
        if key in remote_by_key:
            existing=remote_by_key[key]
            if existing.get("push_id") not in (None,pid):
                raise ContractError("remote source-record identity conflict")
            raise ContractError("approved repair source record already exists remotely")

    with open_source(source) as db:
        article=None
        for raw in db.execute(
            "SELECT id,aid,url FROM articles WHERE board='C_Chat' ORDER BY id DESC"
        ).fetchall():
            if _norm_aid(raw[1])==wanted:
                article=raw
                break
        if article is None:
            raise ContractError("AID not found in Collector source")
        if plan_status=="READ_ONLY_HISTORICAL_REPAIR_PLAN":
            if plan.get("authority")!="verified_url_epoch_full_article_v1":
                raise ContractError("historical repair authority mismatch")
            current=inspect_historical_article(db,article_id=article[0])
        else:
            current=inspect_latest_article(db,article_id=article[0])
    if current.get("source_identity")!=plan.get("source_identity"):
        raise ContractError("source identity changed since repair plan")
    ready={row["source_line"]:row for row in current.get("candidate_rows",[])}
    canonical=[]
    for expected in planned:
        line=expected["source_line"]
        row=ready.get(line)
        if row is None:
            raise ContractError("approved repair row is no longer canonical/ready")
        for key in ("source_record_key","push_id","occurred_at"):
            if row.get(key)!=expected.get(key):
                raise ContractError("approved repair row identity changed")
        canonical.append(row)
    return plan,approved,current,canonical


def run_one(*,source,aid,plan_json,remote_json,batch_no,approved_digest,
            send=False,endpoint=None,receipt_path=None,executor=None,
            proof_secret=None):
    plan,approved,current,rows=validate_approved_batch(
        source=source,aid=aid,plan_json=plan_json,remote_json=remote_json,
        batch_no=batch_no,approved_digest=approved_digest)

    result={
        "status":"READY_TO_SEND" if not send else "SEND_ATTEMPT",
        "aid":_norm_aid(aid),
        "source_identity":current["source_identity"],
        "batch_no":batch_no,
        "queue_digest":approved_digest,
        "rows":len(rows),
        "source_lines":[r["source_line"] for r in rows],
        "retry_cap":0,
        "live_checkpoint_mutations":0,
        "http_requests":0,
    }
    if not send:
        return result

    if receipt_path is None:
        raise ContractError("isolated repair receipt path required for send")
    receipt=Path(receipt_path)
    if receipt.exists():
        previous=json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("status")=="REMOTE_UNCERTAIN":
            raise ContractError("previous repair outcome remote-uncertain; reconcile before replay")
        if previous.get("status")=="ACK":
            raise ContractError("approved repair batch already ACKed")

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
    # make_batch's digest is the transport digest, while approved_digest binds
    # the human-reviewed queue. Keep both in the isolated receipt.
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
    ack=execute_once(batch=batch,executor=executor,max_rows=10,
                     max_queries=60,max_written=24)
    final={
        **result,
        "status":"ACK",
        "http_requests":ack["http_requests"],
        "logical_rows_acked":ack["logical_rows_acked"],
        "d1_query_count":ack["d1_query_count"],
        "d1_rows_written":ack["d1_rows_written"],
        "transport_batch_id":batch["batch_id"],
        "transport_digest":batch["digest"],
    }
    receipt.write_text(json.dumps(final,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
                       encoding="utf-8")
    return final


def main(argv=None):
    p=argparse.ArgumentParser(description="Owner-gated one-batch PTT baseline repair")
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
    result=run_one(
        source=args.source,aid=args.aid,plan_json=args.plan_json,
        remote_json=args.remote_json,batch_no=args.batch_no,
        approved_digest=args.approve_batch_digest,send=args.send,
        endpoint=args.endpoint,receipt_path=args.receipt)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
