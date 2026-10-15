"""Run one incremental PTT snapshot on a fixed cadence (default 60 seconds).

No auto-retry after uncertain write. Uses existing per-AID source checkpoints
and preserves disabled/dry-run default. Only explicitly approved --send invokes
a signed private POST. Writes append-only local operational metrics.
"""
import argparse
import json
import time
from datetime import datetime,timezone
from pathlib import Path
from .collector_source_preview import open_source
from .live_capture_publisher import inspect_latest_article,run_live_once,state_for_source
from .owner_http_transport import owner_signed_http_executor
from .publisher_cli import exclusive_lock
from .public_today_contract import ContractError

def run_snapshot(*,source,state_dir,send=False,secret=None,executor=None,clock=time.time,batch_cap=5):
    started=clock()
    with open_source(source) as db:
        discovered=inspect_latest_article(db)
        if discovered["status"]!="READY":
            result={"status":discovered["status"],"sent":0,"eligible":0}
        else:
            state=state_for_source(state_dir,discovered["source_identity"])
            result=run_live_once(db,state_path=state,secret=secret,executor=executor,send=send,batch_cap=batch_cap)
    return {**result,"elapsed_ms":round((clock()-started)*1000),
        "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "publisher_mode":"OWNER_APPROVED_SEND" if send else "DRY_RUN",
        "http_posts":1 if send and result.get("status")=="ACK" else 0}

def main(argv=None):
    p=argparse.ArgumentParser(description="Controlled 60-second incremental PTT snapshot trial")
    p.add_argument("--source",required=True)
    p.add_argument("--state-dir",required=True)
    p.add_argument("--metrics",required=True)
    p.add_argument("--interval-seconds",type=int,default=60)
    p.add_argument("--iterations",type=int,default=1)
    p.add_argument("--send",action="store_true")
    p.add_argument("--batch-cap",type=int,default=5)
    p.add_argument("--approve-live-capture-policy",action="store_true")
    p.add_argument("--endpoint",default="https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish")
    args=p.parse_args(argv)
    if args.interval_seconds not in (60,120) or not 1<=args.iterations<=1440:
        p.error("only 60 or 120 second cadence and <=1440 bounded iterations allowed")
    if not 1<=args.batch_cap<=25:
        p.error('batch cap must be 1-25 and match approved Worker configuration')
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
                                    secret=proof_secret,executor=executor,batch_cap=args.batch_cap)
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
                time.sleep(max(0,args.interval_seconds-(time.monotonic()-started)))
if __name__=="__main__":main()
