#!/usr/bin/env python3
"""Issue #47: read-only 8501 Stream Catalog -> production Today recovery inventory.

Default behavior is strictly read-only:
- reads local Stream Catalog
- reads production D1 with Wrangler
- writes JSON artifact only
Never mutates D1.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI=ZoneInfo("Asia/Taipei")
VIDEO=re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
KNOWN_ROBOCO="TnijhHRqd5w"

def parse_time(value):
    if not value:return None
    d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("timezone-aware timestamp required")
    return d.astimezone(timezone.utc)

def z(value):
    d=parse_time(value)
    return d.isoformat(timespec="seconds").replace("+00:00","Z") if d else None

def selected_reference(row):
    return row["actual_start"] or row["scheduled_start"] or row["first_seen_at"]

def taipei_day(value):
    return parse_time(value).astimezone(TAIPEI).date().isoformat()

def open_catalog(path):
    p=Path(path).expanduser().resolve()
    con=sqlite3.connect(f"file:{p}?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con

def source_inventory(path, day):
    con=open_catalog(path)
    try:
        cols={r["name"] for r in con.execute("PRAGMA table_info(streams)")}
        required={"video_id","channel_id","title","scheduled_start","actual_start","actual_end",
                  "lifecycle_state","projection_observed_at","first_seen_at","is_livestream"}
        missing=required-cols
        if missing: raise SystemExit("Stream Catalog missing columns: "+",".join(sorted(missing)))
        has_channels=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='channels'").fetchone() is not None
        rows=con.execute("""SELECT video_id,channel_id,title,scheduled_start,actual_start,actual_end,
          lifecycle_state,projection_observed_at,first_seen_at,last_seen_at,last_checked_at,is_livestream,is_public
          FROM streams WHERE is_livestream=1 ORDER BY video_id""").fetchall()
        names={}
        if has_channels:
            for r in con.execute("SELECT channel_id,channel_name FROM channels"):
                names[r["channel_id"]]=r["channel_name"]
    finally:
        con.close()
    out=[]
    for raw in rows:
        r=dict(raw)
        ref=selected_reference(r)
        if not ref:
            continue
        try:
            if taipei_day(ref)!=day: continue
        except Exception:
            continue
        if not VIDEO.fullmatch(str(r.get("video_id") or "")): continue
        if not CHANNEL.fullmatch(str(r.get("channel_id") or "")): continue
        state=str(r.get("lifecycle_state") or "unknown")
        if state not in {"upcoming","live","ended","unknown"}: state="unknown"
        observed=r.get("projection_observed_at") or r.get("last_checked_at") or r.get("last_seen_at") or r.get("first_seen_at")
        item={
          "video_id":r["video_id"],"channel_id":r["channel_id"],"channel_name":names.get(r["channel_id"],""),
          "title":str(r.get("title") or ""),"lifecycle_state":state,
          "scheduled_start":z(r.get("scheduled_start")),"actual_start":z(r.get("actual_start")),
          "actual_end":z(r.get("actual_end")),"projection_observed_at":z(observed),
          "selection_basis":"actual_start" if r.get("actual_start") else "scheduled_start" if r.get("scheduled_start") else "first_seen_at",
          "first_seen_at":z(r.get("first_seen_at")),"is_public":r.get("is_public")
        }
        out.append(item)
    out.sort(key=lambda x:(x["actual_start"] or x["scheduled_start"] or x["first_seen_at"] or "",x["video_id"]))
    return out

def run_json(cmd):
    p=subprocess.run(cmd,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    text=p.stdout
    start=text.find("[")
    if start<0: raise SystemExit("Wrangler JSON result not found:\n"+text)
    body=json.loads(text[start:])
    return body

def d1_query(config, sql):
    body=run_json(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",str(config),"--command",sql,"--json"])
    results=[]
    for part in body if isinstance(body,list) else [body]:
        if isinstance(part,dict):
            results.extend(part.get("results") or part.get("result") or [])
    return results

def q(v):
    return "'" + str(v).replace("'","''") + "'"

def production_snapshot(config, ids):
    meta=d1_query(config,"SELECT roster_version FROM public_today_catalog_meta WHERE singleton=1;")
    if not meta or not meta[0].get("roster_version"): raise SystemExit("active Today roster unavailable")
    roster=meta[0]["roster_version"]
    approved=d1_query(config,"SELECT channel_id,channel_group FROM public_today_approved_channels WHERE roster_version="+q(roster)+";")
    group_by={r["channel_id"]:r["channel_group"] for r in approved}
    canonical=[]
    history=[]
    for i in range(0,len(ids),80):
        chunk=ids[i:i+80]
        if not chunk:continue
        inside=",".join(q(x) for x in chunk)
        canonical.extend(d1_query(config,
          "SELECT video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,"
          "lifecycle_observed_at,scheduled_start,actual_start,actual_end,source_label "
          "FROM public_today_canonical WHERE video_id IN ("+inside+");"))
        history.extend(d1_query(config,
          "SELECT video_id,actual_start,actual_end,source_revision FROM public_history WHERE video_id IN ("+inside+");"))
    return roster,group_by,canonical,history

def richness(r):
    return sum(bool(r.get(k)) for k in ("actual_start","actual_end","scheduled_start"))

def classify(source, prod):
    if not prod:return "missing"
    so=parse_time(source.get("projection_observed_at"))
    po=parse_time(prod.get("lifecycle_observed_at"))
    if po and so and po>so:return "production_richer_newer"
    if richness(prod)>richness(source):return "production_richer_newer"
    return "already_present"

def history_candidate(r):
    if r.get("lifecycle_state")!="ended":return False
    a=parse_time(r.get("actual_start")); b=parse_time(r.get("actual_end"))
    return bool(a and b and b>a)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--catalog",default="~/Downloads/Hololive-PTT-Viewer/hololive_stream_catalog.sqlite3")
    p.add_argument("--day",default="2026-10-18")
    p.add_argument("--config",required=True)
    p.add_argument("--out",default="/tmp/hv47-recovery-20261018.json")
    args=p.parse_args()
    rows=source_inventory(args.catalog,args.day)
    roster,groups,canonical,history=production_snapshot(args.config,[r["video_id"] for r in rows])
    by_prod={r["video_id"]:r for r in canonical}; hist_ids={r["video_id"] for r in history}
    counts=Counter(); life=Counter()
    for r in rows:
        life[r["lifecycle_state"]]+=1
        cls=classify(r,by_prod.get(r["video_id"])); counts[cls]+=1
        r["production_status"]=cls
        r["production"]=by_prod.get(r["video_id"])
        r["roster_version"]=roster
        r["group"]=groups.get(r["channel_id"],"other")
        r["today_import_candidate"]=cls=="missing" or cls=="already_present"
        r["history_missing_candidate"]=history_candidate(r) and r["video_id"] not in hist_ids
    roboco=next((r for r in rows if r["video_id"]==KNOWN_ROBOCO),None)
    artifact={
      "schema_version":"stream-catalog-recovery-inventory-v1",
      "recovery_source":"8501 Stream Catalog",
      "target_day_taipei":args.day,
      "source_db":str(Path(args.catalog).expanduser()),
      "production":{"worker":"holoviewer-public-api","db_name":DB_NAME,"db_id":DB_ID,"active_roster_version":roster},
      "summary":{
        "source_rows":len(rows),"distinct_channels":len({r["channel_id"] for r in rows}),
        "lifecycle":{"upcoming":life["upcoming"],"live":life["live"],"ended":life["ended"],"unknown_missing":life["unknown"]},
        "production_already_present":counts["already_present"],
        "production_missing":counts["missing"],
        "production_richer_newer_conflict":counts["production_richer_newer"],
        "today_import_candidates":sum(bool(r["today_import_candidate"]) for r in rows),
        "history_missing_candidates":sum(bool(r["history_missing_candidate"]) for r in rows),
      },
      "known_roboco":roboco,
      "rows":rows,
    }
    Path(args.out).write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(artifact["summary"],ensure_ascii=False,indent=2))
    print("roboco=",json.dumps(roboco,ensure_ascii=False))
    print("artifact=",args.out)
    print("production_mutation=false")

if __name__=="__main__":
    main()
