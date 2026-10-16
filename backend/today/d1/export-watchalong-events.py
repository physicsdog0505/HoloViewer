#!/usr/bin/env python3
"""Export minimal Public Watchalong event rows from the existing complete PTT Web DB.

Read-only source. Does not publish PTT article bodies, translations, transcripts,
telemetry, or private Watchalong source mappings.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def q(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--database",type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--json-output",type=Path)
    ap.add_argument("--days",type=int,default=90)
    ap.add_argument("--refresh-missing-recent",type=int,default=0,metavar="DAYS",help="Owner-Mac only: discover PTT Hololive threads for the most recent DAYS and fetch only cache-missing article bodies before export")
    ap.add_argument("--source-root",type=Path,default=Path.home()/"Downloads"/"Hololive-PTT-Viewer")
    args=ap.parse_args()
    if not 1<=args.days<=3660:
        raise SystemExit("days outside safe range")
    if not 0<=args.refresh_missing_recent<=min(args.days,60):
        raise SystemExit("refresh-missing-recent must be 0..min(days,60)")
    source_root=args.source_root.expanduser().resolve()
    sys.path.insert(0,str(source_root))
    from client_runtime import client_runtime_root
    from frontend_config import database_paths
    from frontend_time import TAIPEI
    from live_stream_discovery import LiveDiscoveryCache, fetch_body_via_pttweb, refresh_target
    from thread_discovery import discover_for_date
    from watchalong_ptt_catalog import load_recent_events, parse_watchalong_events

    runtime_root=client_runtime_root()
    if args.database is not None:
        database=args.database.expanduser().resolve()
    else:
        # Reuse the accepted 4174 runtime DB resolver; do not invent another path.
        _collector, web_database=database_paths(root=runtime_root)
        database=Path(web_database).expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"PTT Web history DB not found: {database}")

    # Match accepted 4174 Watchalong landing semantics exactly:
    # fresh/current discovery cache + body-complete historical Web DB.
    current=datetime.now(TAIPEI)
    events=[]
    cache=LiveDiscoveryCache(runtime_root/".ptt_stream_discovery_cache.json")
    refresh_stats={"days":args.refresh_missing_recent,"targets":0,"already_cached":0,"fetched":0,"errors":[]}
    if args.refresh_missing_recent:
        # Explicit owner-side coverage repair. This mutates only the rebuildable
        # local discovery cache; it does not write the Web History DB or any cloud service.
        for offset in range(args.refresh_missing_recent):
            value=current.date()-timedelta(days=offset)
            try:
                targets=discover_for_date(value,max_pages=10)
            except Exception as exc:
                refresh_stats["errors"].append({"day":value.isoformat(),"stage":"discover","error":str(exc)})
                continue
            refresh_stats["targets"]+=len(targets)
            for target in targets:
                try:
                    if cache.get(target.aid) is not None:
                        refresh_stats["already_cached"]+=1
                        continue
                except ValueError:
                    pass
                result=refresh_target(target,fetch_body=fetch_body_via_pttweb,cache=cache)
                if result.fresh:
                    refresh_stats["fetched"]+=1
                else:
                    refresh_stats["errors"].append({
                        "day":value.isoformat(),"aid":target.aid,"stage":"fetch",
                        "error":result.error or "unknown refresh failure",
                    })
    try:
        for offset in range(args.days):
            day=(current.date()-timedelta(days=offset)).isoformat()
            for snapshot in cache.for_day(day):
                events.extend(parse_watchalong_events(
                    aid=snapshot.aid,
                    article_title=snapshot.title,
                    source_url=snapshot.source_url,
                    body_text=snapshot.body_text,
                ))
    except (OSError, ValueError, TypeError):
        pass

    events.extend(load_recent_events(database,days=args.days,now=current))
    events.sort(
        key=lambda event:(event.article_datetime,event.scheduled_time,event.aid),
        reverse=True,
    )
    deduped=[]
    seen=set()
    for event in events:
        signature=tuple(sorted(stream.video_id for stream in event.streams))
        if not signature or signature in seen:
            continue
        seen.add(signature)
        deduped.append(event)
    events=deduped
    imported=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out=[]
    for event in events:
        ids=sorted({s.video_id for s in event.streams if s.video_id})
        if not ids: continue
        digest=hashlib.sha256("\n".join(ids).encode()).hexdigest()[:20]
        event_id="watch:"+digest
        out.append({
            "event_id":event_id,"aid":event.aid,"article_title":event.article_title,
            "source_url":event.source_url,"article_datetime":event.article_datetime,
            "day":event.day,"scheduled_time":event.scheduled_time,
            "description":event.description,"member_only":bool(event.member_only),
            "streams":[{"label":s.label,"video_id":s.video_id} for s in event.streams],
        })
    lines=["-- Generated minimal Watchalong event projection; no PTT article body is included.","BEGIN TRANSACTION;"]
    for event in out:
        vals=[event["event_id"],event["aid"],event["article_title"],event["source_url"],
              event["article_datetime"],event["day"],event["scheduled_time"],event["description"],
              1 if event["member_only"] else 0,imported,"ptt_watchalong_parser"]
        lines.append("INSERT INTO public_watchalong_events(event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,imported_at,source) VALUES("+",".join(q(x) for x in vals)+") ON CONFLICT(event_id) DO UPDATE SET aid=excluded.aid,article_title=excluded.article_title,source_url=excluded.source_url,article_datetime=excluded.article_datetime,day=excluded.day,scheduled_time=excluded.scheduled_time,description=excluded.description,member_only=excluded.member_only,imported_at=excluded.imported_at,source=excluded.source WHERE excluded.article_datetime>=public_watchalong_events.article_datetime;")
        accepted = "(SELECT 1 FROM public_watchalong_events WHERE event_id="+q(event["event_id"])+" AND article_datetime="+q(event["article_datetime"])+" AND imported_at="+q(imported)+")"
        lines.append("DELETE FROM public_watchalong_streams WHERE event_id="+q(event["event_id"])+" AND EXISTS "+accepted+";")
        for i,s in enumerate(event["streams"]):
            values=",".join(q(x) for x in [event["event_id"],i,s["label"],s["video_id"]])
            lines.append("INSERT INTO public_watchalong_streams(event_id,ordinal,label,video_id) SELECT "+values+" WHERE EXISTS "+accepted+";")
    lines.append("COMMIT;")
    args.output.write_text("\n".join(lines)+"\n")
    payload={"schema_version":"public-watchalong-export-v1","imported_at":imported,"event_count":len(out),"events":out}
    if args.json_output: args.json_output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"PASS","events":len(out),"streams":sum(len(x["streams"]) for x in out),"refresh":refresh_stats,"sql":str(args.output),"json":str(args.json_output) if args.json_output else None}))

if __name__=="__main__": main()
