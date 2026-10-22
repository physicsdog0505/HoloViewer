"""Run one incremental PTT snapshot on a fixed cadence (default 60 seconds).

No auto-retry after uncertain write. Uses existing per-AID source checkpoints
and preserves disabled/dry-run default. Only explicitly approved --send invokes
a signed private POST. Writes append-only local operational metrics.
"""
import argparse
import json
import time
from collections import deque
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from .collector_source_preview import open_source
from .live_capture_publisher import active_article_ids,inspect_latest_article,run_live_once,state_for_source
from .owner_http_transport import owner_signed_http_executor
from .publisher_cli import exclusive_lock
from .publisher_telemetry import update_publisher_telemetry
from .public_today_contract import ContractError

TAIPEI=ZoneInfo('Asia/Taipei')
LIVE_INTERVAL_SECONDS=10
IDLE_INTERVAL_SECONDS=60
ROLLING_WINDOW_SECONDS=60
ROLLING_BATCH_CAP=6

def adaptive_live_pressure(result):
    """Use only Publisher-local evidence to decide whether to stay at 10s."""
    if not isinstance(result,dict):
        return False
    return bool(
        result.get("fresh_eligible",0)>0 or
        result.get("backlog_may_remain") or
        result.get("sent",0)>0
    )

def prune_rolling(window, now):
    cutoff=now-ROLLING_WINDOW_SECONDS
    while window and window[0][0]<=cutoff:
        window.popleft()

def rolling_totals(window):
    return {
        "batches":sum(item[1] for item in window),
        "rows":sum(item[2] for item in window),
        "modeled_queries":sum(item[3] for item in window),
        "modeled_writes":sum(item[4] for item in window),
    }

def rolling_budget_allows(window, now):
    prune_rolling(window,now)
    return rolling_totals(window)["batches"]<ROLLING_BATCH_CAP

def adaptive_interval(result):
    return LIVE_INTERVAL_SECONDS if adaptive_live_pressure(result) else IDLE_INTERVAL_SECONDS

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

def run_snapshot(*,source,state_dir,send=False,secret=None,executor=None,clock=time.time,batch_cap=5,max_batches=1,burst_max_batches=None,max_articles=4,rotation_interval_seconds=None):
    if type(max_batches) is not int or not 1<=max_batches<=16:
        raise ContractError('invalid bounded batches per snapshot')
    if burst_max_batches is None:
        burst_max_batches=max_batches
    if type(burst_max_batches) is not int or not max_batches<=burst_max_batches<=16:
        raise ContractError('invalid bounded burst batches per snapshot')
    started=clock()
    with open_source(source) as db:
        article_ids=active_article_ids(db,limit=max_articles)
        if send and len(article_ids)>1:
            # Fairly rotate the first AID at the active wall-clock cadence.
            # This lets a strict global max_batches=1 remain safe without a
            # permanently busy newest thread starving the other active AIDs.
            now=datetime.fromtimestamp(started,timezone.utc)
            rotation_seconds=(rotation_interval_seconds
                              if rotation_interval_seconds is not None
                              else snapshot_interval(now))
            if type(rotation_seconds) is not int or rotation_seconds<=0:
                raise ContractError("invalid rotation interval")
            slot=int(started//rotation_seconds)
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
            legacy_baseline_candidates=0
            retained_recovery_candidates=0
            baseline_skipped_candidates=0
            burst_safe_candidates=0
            fresh_eligible=0
            burst_activated=False
            burst_batches=0
            mutation_blocked_aids=[]
            mutation_blocked_count=0
            stale_fenced_rows=0
            for article_index,article_id in enumerate(article_ids):
                plan=inspect_latest_article(db,article_id=article_id)
                if plan["status"]!="READY":
                    continue
                state=state_for_source(state_dir,plan["source_identity"])
                if not send:
                    result=run_live_once(db,state_path=state,secret=secret,
                       executor=executor,send=False,batch_cap=batch_cap,article_id=article_id)
                    pending+=result.get("eligible",0)
                    legacy_baseline_candidates+=result.get("legacy_baseline_candidates",0)
                    retained_recovery_candidates+=result.get("retained_recovery_candidates",0)
                    baseline_skipped_candidates+=result.get("baseline_skipped_candidates",0)
                    burst_safe_candidates+=result.get("burst_safe_candidates",0)
                    fresh_eligible+=result.get("fresh_eligible",0)
                    stale_fenced_rows+=result.get("stale_fenced_rows",0)
                    if result.get("status")=="LOCAL_SOURCE_MUTATION_BLOCKED":
                        mutation_blocked_aids.append(result.get("aid"))
                        mutation_blocked_count+=result.get("mutation_count",0)
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
                    stale_fenced_rows+=batch.get("stale_fenced_rows",0)
                    pending+=batch.get("eligible",0)
                    legacy_baseline_candidates+=batch.get("legacy_baseline_candidates",0)
                    retained_recovery_candidates+=batch.get("retained_recovery_candidates",0)
                    baseline_skipped_candidates+=batch.get("baseline_skipped_candidates",0)
                    burst_safe_candidates+=batch.get("burst_safe_candidates",0)
                    fresh_eligible+=batch.get("fresh_eligible",0)
                    if batch.get("status")=="LOCAL_SOURCE_MUTATION_BLOCKED":
                        mutation_blocked_aids.append(batch.get("aid"))
                        mutation_blocked_count+=batch.get("mutation_count",0)
                        count=0
                        break
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
                    # thread + state + push/evidence writes, plus three bounded
                    # verification SELECT families per HTTP batch.
                    modeled_writes+=2+2*count
                    modeled_queries+=5+2*count
                    if count<batch_cap:
                        break
                backlog=backlog or (count==batch_cap)
                # Adaptive burst starts only when there is enough genuinely
                # fresh traffic to prove a live surge. Extra batches may drain
                # older FIFO rows only while run_live_once confirms every
                # remaining row has verified age within the <=2h recovery window.
                initial_eligible=batch.get("eligible",0) if isinstance(batch,dict) else 0
                initial_fresh=batch.get("fresh_eligible",0) if isinstance(batch,dict) else 0
                initial_burst_safe=batch.get("burst_safe_candidates",0) if isinstance(batch,dict) else 0
                if (send and count==batch_cap and burst_max_batches>max_batches and
                    initial_eligible>batch_cap and initial_fresh>=batch_cap and
                    initial_burst_safe==initial_eligible):
                    while total_posts<burst_max_batches:
                        burst=run_live_once(db,state_path=state,secret=secret,
                            executor=executor,send=True,batch_cap=batch_cap,
                            article_id=article_id,fresh_only=True)
                        stale_fenced_rows+=burst.get("stale_fenced_rows",0)
                        if burst.get("status")=="BURST_BLOCKED":
                            break
                        if burst.get("status")!="ACK":
                            break
                        burst_count=burst.get("sent",0)
                        total_posts+=1
                        burst_batches+=1
                        burst_activated=True
                        total_sent+=burst_count
                        modeled_writes+=2+2*burst_count
                        modeled_queries+=5+2*burst_count
                        backlog=backlog or (burst_count==batch_cap)
                        if burst_count<batch_cap:
                            break
            snapshot_status=last_status if send else "READ_ONLY"
            if mutation_blocked_aids:
                snapshot_status=("PARTIAL_SUCCESS" if total_posts
                                 else "LOCAL_SOURCE_MUTATION_BLOCKED")
            result={"status":snapshot_status,
                    "sent":total_sent,"eligible":pending,
                    "fresh_eligible":fresh_eligible,
                    "legacy_baseline_candidates":legacy_baseline_candidates,
                    "retained_recovery_candidates":retained_recovery_candidates,
                    "baseline_skipped_candidates":baseline_skipped_candidates,
                    "burst_safe_candidates":burst_safe_candidates,
                    "http_posts":total_posts,"batch_count":total_posts,
                    "modeled_d1_writes_ceiling":modeled_writes,
                    "modeled_d1_queries_ceiling":modeled_queries,
                    "articles_checked":len(article_ids),"backlog_may_remain":backlog,
                    "burst_activated":burst_activated,"burst_batches":burst_batches,
                    "mutation_blocked_articles":len(mutation_blocked_aids),
                    "mutation_blocked_aids":mutation_blocked_aids,
                    "mutation_blocked_count":mutation_blocked_count,
                    "stale_fenced_rows":stale_fenced_rows}
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
    p.add_argument("--adaptive-live-cadence",action="store_true",
                   help="owner-reviewed Phase A: 10s under live pressure, 60s idle, max 6 batches/rolling 60s")
    p.add_argument("--iterations",type=int,default=1,
                   help="number of snapshots; 0 means run until externally stopped")
    p.add_argument("--send",action="store_true")
    p.add_argument("--batch-cap",type=int,default=5)
    p.add_argument("--max-batches",type=int,default=1)
    p.add_argument("--burst-max-batches",type=int,default=None)
    p.add_argument("--max-articles",type=int,default=4)
    p.add_argument("--approve-live-capture-policy",action="store_true")
    p.add_argument("--endpoint",default="https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish")
    args=p.parse_args(argv)
    if not 0<=args.iterations<=1440:
        p.error("iterations must be 0 (continuous) or 1-1440")
    if not 1<=args.batch_cap<=25:
        p.error('batch cap must be 1-25 and match approved Worker configuration')
    if not 1<=args.max_articles<=8:
        p.error('max articles must be 1-8')
    if not 1<=args.max_batches<=16:
        p.error('max batches must be 1-16')
    if args.burst_max_batches is not None and not args.max_batches<=args.burst_max_batches<=16:
        p.error('burst max batches must be between max-batches and 16')
    if args.adaptive_live_cadence and args.max_batches!=1:
        p.error('adaptive Phase A requires max-batches=1')
    if args.adaptive_live_cadence and args.interval_seconds is not None:
        p.error('adaptive cadence cannot be combined with fixed interval override')
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
    telemetry=metric.parent/"publisher-telemetry.json"
    with exclusive_lock(Path(args.state_dir)/".single-publisher.lock"):
        iteration=0
        rolling=deque()
        previous_backlog=None
        while args.iterations==0 or iteration<args.iterations:
            started=time.monotonic()
            try:
                now_mono=time.monotonic()
                prune_rolling(rolling,now_mono)
                before=rolling_totals(rolling)
                budget_blocked=bool(args.adaptive_live_cadence and args.send and not rolling_budget_allows(rolling,now_mono))
                send_this_tick=args.send and not budget_blocked
                effective_burst=(args.max_batches if args.adaptive_live_cadence else args.burst_max_batches)
                result=run_snapshot(source=args.source,state_dir=args.state_dir,send=send_this_tick,
                                    secret=proof_secret,executor=executor,batch_cap=args.batch_cap,max_batches=args.max_batches,
                                    burst_max_batches=effective_burst,max_articles=args.max_articles,
                                    rotation_interval_seconds=(LIVE_INTERVAL_SECONDS if args.adaptive_live_cadence else None))
                posts=result.get("http_posts",0)
                sent_rows=result.get("sent",0)
                modeled_queries=result.get("modeled_d1_queries_ceiling",0)
                modeled_writes=result.get("modeled_d1_writes_ceiling",0)
                if send_this_tick and posts:
                    rolling.append((now_mono,posts,sent_rows,modeled_queries,modeled_writes))
                prune_rolling(rolling,now_mono)
                totals=rolling_totals(rolling)
                eligible=result.get("eligible",0)
                backlog_after=max(0,eligible-sent_rows) if isinstance(eligible,int) else 0
                backlog_delta=(None if previous_backlog is None else backlog_after-previous_backlog)
                previous_backlog=backlog_after
                retained=result.get("retained_recovery_candidates",0)
                fresh=result.get("fresh_eligible",0)
                recovery=max(0,retained-fresh) if isinstance(retained,int) and isinstance(fresh,int) else 0
                stop_reason=("ROLLING_60S_BATCH_CAP" if budget_blocked else None)
                result={**result,
                    "adaptive_live_cadence":bool(args.adaptive_live_cadence),
                    "live_pressure":adaptive_live_pressure(result),
                    "recovery_eligible":recovery,
                    "backlog_size":backlog_after,
                    "backlog_delta":backlog_delta,
                    "rolling_60s_batches":totals["batches"],
                    "rolling_60s_rows":totals["rows"],
                    "rolling_60s_modeled_queries":totals["modeled_queries"],
                    "rolling_60s_modeled_writes":totals["modeled_writes"],
                    "stop_reason":stop_reason,
                }
            except Exception as exc:
                failure={"status":"STOP_RECONCILE","error_class":type(exc).__name__,
                         "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "remote_outcome":"UNKNOWN_NO_RETRY"}
                with metric.open("a",encoding="utf-8") as handle:
                    handle.write(json.dumps(failure,sort_keys=True)+"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                update_publisher_telemetry(telemetry,failure)
                raise
            with metric.open("a",encoding="utf-8") as handle:
                handle.write(json.dumps(result,ensure_ascii=False,sort_keys=True)+"\n")
                handle.flush()
                os.fsync(handle.fileno())
            update_publisher_telemetry(telemetry,result)
            print(json.dumps(result,ensure_ascii=False,sort_keys=True),flush=True)
            iteration+=1
            if args.iterations!=0 and iteration>=args.iterations:
                break
            if args.adaptive_live_cadence:
                cadence=adaptive_interval(result)
                time.sleep(max(0,cadence-(time.monotonic()-started)))
            else:
                time.sleep(max(0,args.interval_seconds-(time.monotonic()-started))
                           if args.interval_seconds else seconds_until_next_snapshot())
if __name__=="__main__":main()
