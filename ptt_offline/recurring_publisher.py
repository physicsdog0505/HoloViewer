"""Run one incremental PTT snapshot on a fixed cadence (default 60 seconds).

No auto-retry after uncertain write. Uses existing per-AID source checkpoints
and preserves disabled/dry-run default. Only explicitly approved --send invokes
a signed private POST. Writes append-only local operational metrics.
"""
import argparse
import json
import time
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from .collector_source_preview import open_source
from .live_capture_publisher import active_article_ids,inspect_latest_article,run_live_once,state_for_source
from .owner_http_transport import owner_signed_http_executor
from .publisher_cli import exclusive_lock
from .public_today_contract import ContractError

TAIPEI=ZoneInfo('Asia/Taipei')

def snapshot_interval(now=None):
    """02:00 through 06:59 Taipei: 10 min; otherwise: 1 min."""
    local=(now or datetime.now(timezone.utc)).astimezone(TAIPEI)
    return 600 if 2<=local.hour<7 else 60

def seconds_until_next_snapshot(now=None):
    """Wall-clock aligned, including 02:00 and 07:00 boundaries."""
    local=(now or datetime.now(timezone.utc)).astimezone(TAIPEI)
    cadence=snapshot_interval(local)
    minute_of_day=local.hour*60+local.minute
    next_minute=((minute_of_day//(cadence//60))+1)*(cadence//60)
    if next_minute>=1440:
        target=(local+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
    else:
        target=local.replace(hour=next_minute//60,minute=next_minute%60,second=0,microsecond=0)
    return max(0,(target-local).total_seconds())

def run_snapshot(*,source,state_dir,send=False,secret=None,executor=None,clock=time.time,batch_cap=5,max_batches=1,max_articles=4):
    if type(max_batches) is not int or not 1<=max_batches<=16:
        raise ContractError('invalid bounded batches per snapshot')
    started=clock()
    with open_source(source) as db:
        article_ids=active_article_ids(db,limit=max_articles)
        if send and len(article_ids)>1:
            # Fairly rotate the first AID at the active wall-clock cadence.
            # This lets a strict global max_batches=1 remain safe without a
            # permanently busy newest thread starving the other active AIDs.
            now=datetime.fromtimestamp(started,timezone.utc)
            slot=int(started//snapshot_interval(now))
            offset=slot%len(article_ids)
            article_ids=article_ids[offset:]+article_ids[:offset]
        if not article_ids:
            result={"status":"NO_REAL_COLLECTOR_ROWS","sent":0,"eligible":0,"http_posts":0}
        else:
            total_sent=0
            total_posts=0
            modeled_queries=0
            modeled_writes=0
            last_status="NO_NEW_ROWS"
            backlog=False
            pending=0
            for article_index,article_id in enumerate(article_ids):
                plan=inspect_latest_article(db,article_id=article_id)
                if plan["status"]!="READY":
                    continue
                state=state_for_source(state_dir,plan["source_identity"])
                if not send:
                    result=run_live_once(db,state_path=state,secret=secret,
                       executor=executor,send=False,batch_cap=batch_cap,article_id=article_id)
                    pending+=result.get("eligible",0)
                    continue
                # max_batches is a GLOBAL per-snapshot network/write budget.
                # Never turn a zero share into one: that previously allowed
                # max_batches=1 to send once for every active AID.
                remaining=max_batches-total_posts
                if remaining<=0:
                    backlog=True
                    break
                remaining_articles=max(1,len(article_ids)-article_index)
                per_article_cap=max(1,remaining//remaining_articles)
                count=0
                for _ in range(per_article_cap):
                    batch=run_live_once(db,state_path=state,secret=secret,
                        executor=executor,send=True,batch_cap=batch_cap,article_id=article_id)
                    last_status=batch.get("status",last_status)
                    if batch.get("status")=="BASELINED":
                        # Local first-seen baseline is a successful zero-write
                        # activation outcome, not a remote failure.
                        count=0
                        last_status="BASELINED"
                        break
                    if batch.get("status")!="ACK":
                        count=0
                        break
                    total_posts+=1
                    count=batch.get("sent",0)
                    total_sent+=count
                    # Mirrors d1_owner_writer's conservative one-AID budget:
                    # thread + state + push/evidence, plus pre/post readbacks.
                    modeled_writes+=2+2*count
                    modeled_queries+=2+5*count
                    if count<batch_cap:
                        break
                backlog=backlog or (count==batch_cap)
            result={"status":last_status if send else "READ_ONLY",
                    "sent":total_sent,"eligible":pending,
                    "http_posts":total_posts,"batch_count":total_posts,
                    "modeled_d1_writes_ceiling":modeled_writes,
                    "modeled_d1_queries_ceiling":modeled_queries,
                    "articles_checked":len(article_ids),"backlog_may_remain":backlog}
    return {**result,"elapsed_ms":round((clock()-started)*1000),
        "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher_mode":"OWNER_APPROVED_SEND" if send else "DRY_RUN",
        "http_posts":result.get("http_posts",0)}

def main(argv=None):
    p=argparse.ArgumentParser(description="Controlled 60-second incremental PTT snapshot trial")
    p.add_argument("--source",required=True)
    p.add_argument("--state-dir",required=True)
    p.add_argument("--metrics",required=True)
    p.add_argument("--interval-seconds",type=int,choices=(60,120),default=None,
                   help="optional fixed interval override; default 1min daytime / 10min 02-07 Asia/Taipei")
    p.add_argument("--iterations",type=int,default=1)
    p.add_argument("--send",action="store_true")
    p.add_argument("--batch-cap",type=int,default=5)
    p.add_argument("--max-batches",type=int,default=1)
    p.add_argument("--max-articles",type=int,default=4)
    p.add_argument("--approve-live-capture-policy",action="store_true")
    p.add_argument("--endpoint",default="https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish")
    args=p.parse_args(argv)
    if not 1<=args.iterations<=1440:
        p.error("maximum 1440 bounded iterations allowed")
    if not 1<=args.batch_cap<=25:
        p.error('batch cap must be 1-25 and match approved Worker configuration')
    if not 1<=args.max_articles<=8:
        p.error('max articles must be 1-8')
    if not 1<=args.max_batches<=16:
        p.error('max batches must be 1-16')
    import os
    if args.send and (not args.approve_live_capture_policy or
       os.environ.get("PTT_ALLOW_CAPTURE_TIME_POLICY")!="true"):
        raise ContractError("explicit owner authorization for ongoing Publisher required")
    proof_secret=os.environ.get("PTT_TIME_AUTHORITY_SECRET","") if args.send else None
    executor=(owner_signed_http_executor(endpoint=args.endpoint,
             secret=os.environ.get("PTT_PUBLISH_HMAC_SECRET",""),allow_write=True,
             max_rows=args.batch_cap,max_bytes=131072 if args.batch_cap>5 else 65536)
              if args.send else None)
    metric=Path(args.metrics)
    metric.parent.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(Path(args.state_dir)/".single-publisher.lock"):
        for iteration in range(args.iterations):
            started=time.monotonic()
            try:
                result=run_snapshot(source=args.source,state_dir=args.state_dir,send=args.send,
                                    secret=proof_secret,executor=executor,batch_cap=args.batch_cap,max_batches=args.max_batches,max_articles=args.max_articles)
            except Exception as exc:
                failure={"status":"STOP_RECONCILE","error_class":type(exc).__name__,
                         "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "remote_outcome":"UNKNOWN_NO_RETRY"}
                with metric.open("a",encoding="utf-8") as handle:
                    handle.write(json.dumps(failure,sort_keys=True)+"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                raise
            with metric.open("a",encoding="utf-8") as handle:
                handle.write(json.dumps(result,ensure_ascii=False,sort_keys=True)+"\n")
                handle.flush()
                os.fsync(handle.fileno())
            print(json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
            if iteration+1<args.iterations:
                time.sleep(max(0,args.interval_seconds-(time.monotonic()-started))
                           if args.interval_seconds else seconds_until_next_snapshot())
if __name__=="__main__":main()
