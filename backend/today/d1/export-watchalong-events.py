#!/usr/bin/env python3
"""Export minimal Public Watchalong event rows from the existing complete PTT Web DB.

Read-only source. Does not publish PTT article bodies, translations, transcripts,
telemetry, or private Watchalong source mappings.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

def q(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--database",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--json-output",type=Path)
    ap.add_argument("--days",type=int,default=90)
    ap.add_argument("--source-root",type=Path,default=Path.home()/"Downloads"/"Hololive-PTT-Viewer")
    args=ap.parse_args()
    if not 1<=args.days<=3660:
        raise SystemExit("days outside safe range")
    sys.path.insert(0,str(args.source_root.expanduser().resolve()))
    from watchalong_ptt_catalog import load_recent_events
    events=load_recent_events(args.database.expanduser().resolve(),days=args.days)
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
        accepted = "(SELECT 1 FROM public_watchalong_events WHERE event_id="+q(event["event_id"])+" AND imported_at="+q(imported)+")"
        lines.append("DELETE FROM public_watchalong_streams WHERE event_id="+q(event["event_id"])+" AND EXISTS "+accepted+";")
        for i,s in enumerate(event["streams"]):
            values=",".join(q(x) for x in [event["event_id"],i,s["label"],s["video_id"]])
            lines.append("INSERT INTO public_watchalong_streams(event_id,ordinal,label,video_id) SELECT "+values+" WHERE EXISTS "+accepted+";")
    lines.append("COMMIT;")
    args.output.write_text("\n".join(lines)+"\n")
    payload={"schema_version":"public-watchalong-export-v1","imported_at":imported,"event_count":len(out),"events":out}
    if args.json_output: args.json_output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"PASS","events":len(out),"streams":sum(len(x["streams"]) for x in out),"sql":str(args.output),"json":str(args.json_output) if args.json_output else None}))

if __name__=="__main__": main()
