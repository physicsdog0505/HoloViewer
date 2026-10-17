"""Optional owner-gated near-live Collector -> existing Cloudflare API one-shot Publisher.

This is a separate LIVE cursor, never a claim of complete historical lines.
First-seen pushes can be signed after a strong 180-second observed-time match,
or a verified source-chronology reconstruction with an at-most-two-hour Collector
delay. Rows without explicit timezone authority stay pending. Uncertain remote
outcomes persist a stop latch: never retry automatically. No synthetic content or public write endpoints.
"""
import argparse
from datetime import datetime,timezone,timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector_source_preview import open_source,verify_schema
from .ptt_aid_identity import identity_receipt, verify_aid_url
from .url_epoch_authority import reconstruct_events
from .d1_publisher import canonical_record
from .owner_publisher_once import sign_time_proof
from .owner_http_transport import owner_signed_http_executor
from .publisher_cli import atomic_receipt,exclusive_lock
from .resumable_publisher import new_checkpoint,make_batch,apply_ack
from .d1_transport_contract import execute_once
from .public_today_contract import ContractError

TPE=ZoneInfo("Asia/Taipei")
RECOVERY_MAX_DELAY_SECONDS=2*60*60
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

def active_article_ids(db,limit=4):
    """Recent independent AIDs; bounded fair sweep rather than latest only."""
    if type(limit) is not int or not 1<=limit<=8:
        raise ContractError('invalid bounded article window')
    return [r[0] for r in db.execute('''
        SELECT a.id FROM articles a JOIN pushes p ON p.article_id=a.id
        WHERE a.board='C_Chat'
        GROUP BY a.id ORDER BY MAX(p.collected_at) DESC,a.id DESC LIMIT ?
    ''',(limit,)).fetchall()]

def inspect_latest_article(db,*,max_rows=50000,article_id=None):
    verify_schema(db)
    if type(max_rows) is not int or not 1<=max_rows<=50000:
        raise ContractError("bounded live source scan required")
    if article_id is None:
        ids=active_article_ids(db,limit=1)
        article_id=ids[0] if ids else None
    article=(db.execute('''SELECT id,board,aid,url,last_seen_at FROM articles
        WHERE id=? AND board='C_Chat' ''',(article_id,)).fetchone()
        if article_id is not None else None)
    if article is None:return {"status":"NO_REAL_COLLECTOR_ROWS","candidate_rows":[]}
    article_id,board,raw_aid,url,_=article
    receipt=identity_receipt(board,raw_aid,url)
    epoch=int(url.split("/M.",1)[1].split(".A.",1)[0])
    keys=("source_line","kind","author","content","ptt_date","ptt_time","collected_at")
    raw=db.execute("""
        SELECT source_line,kind,author,content,ptt_date,ptt_time,collected_at
        FROM pushes WHERE article_id=? ORDER BY source_line DESC LIMIT ?
    """,(article_id,max_rows+1)).fetchall()
    truncated=len(raw)>max_rows
    chronological_raw=[dict(zip(keys,record)) for record in reversed(raw[:max_rows])]
    recovered_by_line={}
    if not truncated and chronological_raw:
        try:
            rebuilt=reconstruct_events(
                board=board,aid=receipt["aid"],url=url,
                identity_verifier=verify_aid_url,pushes=chronological_raw,
            )
            recovered_by_line={row["source_line"]:row["occurred_at"] for row in rebuilt}
        except ContractError:
            recovered_by_line={}
    ready=[];pending=[]
    for row in chronological_raw:
        observed=recent_observed_utc(row)
        if observed is None:
            recovered=recovered_by_line.get(row["source_line"])
            try:
                collected=datetime.fromisoformat(row["collected_at"].replace("Z","+00:00"))
                if collected.tzinfo is None:
                    raise ValueError("collected_at timezone missing")
                collected=collected.astimezone(timezone.utc)
                canonical=(datetime.fromisoformat(recovered.replace("Z","+00:00")).astimezone(timezone.utc)
                           if recovered else None)
                delay=(collected-canonical).total_seconds() if canonical else None
            except (TypeError,ValueError,AttributeError):
                delay=None
            observed=recovered if delay is not None and 0<=delay<=RECOVERY_MAX_DELAY_SECONDS else None
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
            "scan_truncated":truncated,
            "earliest_scanned_source_line":min((r[0] for r in raw[:max_rows]),default=None)}

def content_digest(row):
    return sha256(json.dumps([row.get(k) for k in OUTPUT_KEYS if k!="time_proof"],
          ensure_ascii=False,separators=(",",":")).encode("utf-8")).hexdigest()

def _row_age_seconds(row, *, now=None):
    current=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        occurred=datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00")).astimezone(timezone.utc)
    except (KeyError,TypeError,ValueError,AttributeError):
        return None
    return (current-occurred).total_seconds()

def _fresh_for_burst(row, *, now=None, max_age_seconds=180):
    age=_row_age_seconds(row,now=now)
    return age is not None and 0<=age<=max_age_seconds

def run_live_once(db,*,state_path,secret=None,executor=None,send=False,batch_cap=5,article_id=None,
                  fresh_only=False,now=None):
    if type(batch_cap) is not int or not 1<=batch_cap<=25:
        raise ContractError('invalid bounded live batch cap')
    path=Path(state_path)
    with exclusive_lock(path.with_suffix(path.suffix+".lock")):
        plan=inspect_latest_article(db,article_id=article_id)
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
        # First activation for an already-populated AID establishes a LOCAL
        # live baseline instead of promoting all pre-existing eligible rows
        # into an implicit historical catch-up. This receipt performs no
        # remote write. Subsequent rows are compared against this baseline.
        if not current and plan["candidate_rows"]:
            baseline={row["source_record_key"]:content_digest(row)
                      for row in plan["candidate_rows"]}
            atomic_receipt(path,{"status":"BASELINED",
                "source_identity":plan["source_identity"],
                "accepted":baseline,
                "baseline_source_line":max(row["source_line"] for row in plan["candidate_rows"]),
                "pending_count":len(plan["pending_source_lines"])})
            return {"status":"BASELINED","aid":plan["aid"],"eligible":0,
                    "baselined":len(baseline),"pending":len(plan["pending_source_lines"]),
                    "source_identity":plan["source_identity"],"sent":0}
        missing=[]
        for row in plan["candidate_rows"]:
            key=row["source_record_key"]
            digest=content_digest(row)
            if key in accepted and accepted[key]!=digest:
                raise ContractError("ACKed source line mutated since publication")
            if key not in accepted:missing.append(row)

        # One-time upgrade fence for legacy Publisher state created before the
        # safe baseline semantics existed. Historical missing rows older than
        # the accepted <=2h recovery window are local backlog, not near-live
        # delivery. Mark only those stale rows accepted locally; preserve all
        # rows from the last two hours so fresh and verified delayed recovery
        # continue normally. This fence never performs a remote write.
        legacy_baselined=0
        if send and current and not current.get("legacy_backlog_fence_v2"):
            stale=[]
            keep=[]
            for row in missing:
                age=_row_age_seconds(row,now=now)
                if age is not None and age>RECOVERY_MAX_DELAY_SECONDS:
                    stale.append(row)
                else:
                    keep.append(row)
            for row in stale:
                accepted[row["source_record_key"]]=content_digest(row)
            legacy_baselined=len(stale)
            atomic_receipt(path,{"status":"ACKED",
                "source_identity":plan["source_identity"],
                "accepted":accepted,
                "legacy_backlog_fence_v2":True,
                "legacy_baselined":legacy_baselined,
                "pending_count":len(plan["pending_source_lines"])})
            current={**current,"legacy_backlog_fence_v2":True}
            missing=keep

        fresh_eligible=sum(1 for row in missing if _fresh_for_burst(row,now=now))
        receipt={"status":"READ_ONLY","aid":plan["aid"],
                 "eligible":len(missing),"fresh_eligible":fresh_eligible,
                 "legacy_baselined":legacy_baselined,
                 "pending":len(plan["pending_source_lines"]),
                 "source_identity":plan["source_identity"],"sent":0}
        if not send:return receipt
        if not isinstance(secret,str) or len(secret)<32 or not callable(executor):
            raise ContractError("separate trusted source proof and transport required")
        if not missing:return {**receipt,"status":"NO_NEW_ROWS"}
        if fresh_only and fresh_eligible!=len(missing):
            return {**receipt,"status":"BURST_BLOCKED"}
        selected=missing[:batch_cap]
        for row in selected:
            row["time_proof"]=sign_time_proof(row,secret)
        rows=[{k:r.get(k) for k in OUTPUT_KEYS} for r in selected]
        day=rows[0]["day"]
        rows=[r for r in rows if r["day"]==day]
        checkpoint=new_checkpoint(source_identity=plan["source_identity"],day=day,aids=[plan["aid"]])
        batch=make_batch(checkpoint=checkpoint,rows=rows,batch_cap=batch_cap)
        atomic_receipt(path,{"status":"REMOTE_UNCERTAIN","source_identity":plan["source_identity"],
                            "accepted":accepted,"pending_batch_id":batch["batch_id"]})
        ack=execute_once(batch=batch,executor=executor,max_rows=batch_cap,
            max_queries=min(150,2+5*batch_cap),max_written=min(80,2+2*batch_cap))
        apply_ack(checkpoint=checkpoint,batch=batch,ack=ack)
        for row in rows:
            accepted[row["source_record_key"]]=content_digest(row)
        atomic_receipt(path,{"status":"ACKED","source_identity":plan["source_identity"],
                            "accepted":accepted,"last_batch_id":batch["batch_id"],
                            "legacy_backlog_fence_v2":Boolean(current.get("legacy_backlog_fence_v2")),
                            "pending_count":len(plan["pending_source_lines"])})
        return {**receipt,"status":"ACK","sent":len(rows),"batch_id":batch["batch_id"]}

def state_for_source(state_dir,source_identity):
    if not isinstance(source_identity,str) or len(source_identity)!=64 or any(c not in "0123456789abcdef" for c in source_identity):
        raise ContractError("invalid canonical source identity for state isolation")
    return str(Path(state_dir)/(source_identity+".json"))


def main(argv=None):
    p=argparse.ArgumentParser(description="One bounded near-live genuine PTT Publisher attempt")
    p.add_argument("--source",required=True)
    state_group=p.add_mutually_exclusive_group(required=True)
    state_group.add_argument("--state")
    state_group.add_argument("--state-dir")
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
        state=args.state
        if args.state_dir:
            observed=inspect_latest_article(db)
            if observed["status"]!="READY":
                print(json.dumps({"status":observed["status"],"sent":0}))
                return
            state=state_for_source(args.state_dir,observed["source_identity"])
        result=run_live_once(db,state_path=state,secret=secret,executor=executor,send=args.send)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
if __name__=="__main__":main()
