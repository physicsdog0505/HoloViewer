"""Optional owner-gated near-live Collector -> existing Cloudflare API one-shot Publisher.

This is a separate LIVE cursor, never a claim of complete historical lines.
Only first-seen pushes matching PTT displayed Taipei minute within 180 seconds
can be signed. Uncertain remote outcomes persist a stop latch: never retry
automatically. No synthetic content or public write endpoints.
"""
import argparse
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector_source_preview import open_source,verify_schema
from .ptt_aid_identity import identity_receipt
from .d1_publisher import canonical_record
from .owner_publisher_once import sign_time_proof
from .owner_http_transport import owner_signed_http_executor
from .publisher_cli import atomic_receipt,exclusive_lock
from .resumable_publisher import new_checkpoint,make_batch,apply_ack
from .d1_transport_contract import execute_once
from .public_today_contract import ContractError

TPE=ZoneInfo("Asia/Taipei")
OUTPUT_KEYS=("push_id","aid","day","source_line","kind","author","content",
             "occurred_at","floor","source_url","source_record_key","time_proof")

def recent_observed_utc(row):
    try:
        observed=datetime.fromisoformat(row["collected_at"].replace("Z","+00:00"))
        if observed.tzinfo is None:return None
        observed=observed.astimezone(timezone.utc)
        base=observed.astimezone(TPE).replace(second=0,microsecond=0)
        for minute in range(4):
            possible=base-timedelta(minutes=minute)
            if (possible.strftime("%m/%d")==row["ptt_date"] and
                possible.strftime("%H:%M")==row["ptt_time"] and
                0<=(observed-possible.astimezone(timezone.utc)).total_seconds()<=180):
                return possible.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        return None
    return None

def inspect_latest_article(db,*,max_rows=100):
    verify_schema(db)
    if type(max_rows) is not int or not 1<=max_rows<=100:
        raise ContractError("bounded live source scan required")
    article=db.execute("""
        SELECT a.id,a.board,a.aid,a.url,MAX(p.collected_at) AS latest
        FROM articles a JOIN pushes p ON p.article_id=a.id
        WHERE a.board='C_Chat'
        GROUP BY a.id ORDER BY latest DESC LIMIT 1
    """).fetchone()
    if article is None:return {"status":"NO_REAL_COLLECTOR_ROWS","candidate_rows":[]}
    article_id,board,raw_aid,url,_=article
    receipt=identity_receipt(board,raw_aid,url)
    epoch=int(url.split("/M.",1)[1].split(".A.",1)[0])
    keys=("source_line","kind","author","content","ptt_date","ptt_time","collected_at")
    raw=db.execute("""
        SELECT source_line,kind,author,content,ptt_date,ptt_time,collected_at
        FROM pushes WHERE article_id=? ORDER BY source_line DESC LIMIT ?
    """,(article_id,max_rows)).fetchall()
    ready=[];pending=[]
    for record in reversed(raw):
        row=dict(zip(keys,record))
        observed=recent_observed_utc(row)
        if observed is None:
            pending.append(row["source_line"])
            continue
        if datetime.fromisoformat(observed.replace("Z","+00:00")).timestamp()+60<epoch:
            pending.append(row["source_line"])
            continue
        normalized=canonical_record({**row,"aid":receipt["aid"],"source_url":url,
             "occurred_at":observed,"origin":"collector",
             "source_record_key":f'{receipt["aid"]}:{row["source_line"]}',
             "floor":None})
        ready.append(normalized)
    source_identity=sha256(json.dumps([receipt["aid"],url],sort_keys=True,
        separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return {"status":"READY","aid":receipt["aid"],"url":url,
            "source_identity":source_identity,"candidate_rows":ready,
            "pending_source_lines":pending,"checked_source_rows":len(raw),
            "scan_truncated":len(raw)==max_rows,
            "earliest_scanned_source_line":min((r[0] for r in raw),default=None)}

def content_digest(row):
    return sha256(json.dumps([row.get(k) for k in OUTPUT_KEYS if k!="time_proof"],
          ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()

def run_live_once(db,*,state_path,secret=None,executor=None,send=False):
    path=Path(state_path)
    with exclusive_lock(path.with_suffix(path.suffix+".lock")):
        plan=inspect_latest_article(db)
        if plan["status"]!="READY":
            return {"status":plan["status"],"sent":0}
        current={}
        if path.exists():
            current=json.loads(path.read_text(encoding="utf-8"))
            if current.get("status")=="REMOTE_UNCERTAIN":
                raise ContractError("remote ACK unresolved; inspect D1 before any replay")
            if current.get("source_identity")!=plan["source_identity"]:
                raise ContractError("live source identity changed; separate state needed")
        accepted=dict(current.get("accepted",{}))
        # Last-N scanning cannot establish that older source rows were ever
        # inspected. Refuse first-time live publication from a truncated scan;
        # otherwise an old backlog could disappear without gap evidence.
        if plan["scan_truncated"] and not current:
            raise ContractError("initial live source scan truncated; inspect full coverage before publishing")
        missing=[]
        for row in plan["candidate_rows"]:
            key=row["source_record_key"]
            digest=content_digest(row)
            if key in accepted and accepted[key]!=digest:
                raise ContractError("ACKed source line mutated since publication")
            if key not in accepted:missing.append(row)
        receipt={"status":"READ_ONLY","aid":plan["aid"],
                 "eligible":len(missing),"pending":len(plan["pending_source_lines"]),
                 "source_identity":plan["source_identity"],"sent":0}
        if not send:return receipt
        if not isinstance(secret,str) or len(secret)<32 or not callable(executor):
            raise ContractError("separate trusted source proof and transport required")
        if not missing:return {**receipt,"status":"NO_NEW_ROWS"}
        selected=missing[:5]
        for row in selected:
            row["time_proof"]=sign_time_proof(row,secret)
        rows=[{k:r.get(k) for k in OUTPUT_KEYS} for r in selected]
        day=rows[0]["day"]
        rows=[r for r in rows if r["day"]==day]
        checkpoint=new_checkpoint(source_identity=plan["source_identity"],day=day,aids=[plan["aid"]])
        batch=make_batch(checkpoint=checkpoint,rows=rows)
        atomic_receipt(path,{"status":"REMOTE_UNCERTAIN","source_identity":plan["source_identity"],
                            "accepted":accepted,"pending_batch_id":batch["batch_id"]})
        ack=execute_once(batch=batch,executor=executor)
        apply_ack(checkpoint=checkpoint,batch=batch,ack=ack)
        for row in rows:
            accepted[row["source_record_key"]]=content_digest(row)
        atomic_receipt(path,{"status":"ACKED","source_identity":plan["source_identity"],
                            "accepted":accepted,"last_batch_id":batch["batch_id"],
                            "pending_count":len(plan["pending_source_lines"])})
        return {**receipt,"status":"ACK","sent":len(rows),"batch_id":batch["batch_id"]}

def main(argv=None):
    p=argparse.ArgumentParser(description="One bounded near-live genuine PTT Publisher attempt")
    p.add_argument("--source",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--endpoint")
    p.add_argument("--inspect",action="store_true")
    p.add_argument("--send",action="store_true")
    p.add_argument("--approve-live-capture-policy",action="store_true")
    args=p.parse_args(argv)
    if args.inspect==args.send:p.error("choose exactly one of --inspect or --send")
    if args.send and (not args.approve_live_capture_policy or
                      os.environ.get("PTT_ALLOW_CAPTURE_TIME_POLICY")!="true"):
        raise ContractError("explicit owner-approved near-live capture policy required")
    secret=os.environ.get("PTT_TIME_AUTHORITY_SECRET","")
    executor=None
    if args.send:
        executor=owner_signed_http_executor(endpoint=args.endpoint or "",
            secret=os.environ.get("PTT_PUBLISH_HMAC_SECRET",""),allow_write=True)
    with open_source(args.source) as db:
        result=run_live_once(db,state_path=args.state,secret=secret,executor=executor,send=args.send)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
