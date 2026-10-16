#!/usr/bin/env python3
"""Read-only, fail-closed release audit of a #47 Watchalong SQL+JSON export."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

EVENT_KEYS={"event_id","aid","article_title","source_url","article_datetime","day","scheduled_time","description","member_only","streams"}
HOST_KEYS={"label","video_id"}
ROOT_KEYS={"schema_version","imported_at","event_count","events"}
URL=re.compile(r"https://www\.ptt\.cc/bbs/C_Chat/M\.[0-9]{9,11}\.A\.[0-9A-Fa-f]+\.html")
VIDEO=re.compile(r"[A-Za-z0-9_-]{11}")
SQL_TABLE=re.compile(r"\b(?:INSERT\s+INTO|DELETE\s+FROM|REPLACE\s+INTO|CREATE\s+TABLE|DROP\s+TABLE|ALTER\s+TABLE)\s+([a-z_][a-z0-9_]*)",re.I)
ALLOWED_TABLES={"public_watchalong_events","public_watchalong_streams"}
FORBIDDEN=re.compile(r"(?i)\b(?:transcript|translation|telemetry|source_mapping|prompt|api_key|private_mapping|body_text|article_body|raw_body|a_b_translation)\b")
EXPECTED_DAYS={"2026-10-01","2026-10-08","2026-10-15"}
CALIBRATION=re.compile(r"無職転生|無職轉生|mushoku",re.I)

def audit(sql_path, json_path):
    problems=[]
    def fail(msg):
        if len(problems)<30: problems.append(msg)
    raw=json.loads(json_path.read_text(encoding="utf-8"))
    if set(raw)!=ROOT_KEYS: fail("unexpected_root_fields")
    if raw.get("schema_version")!="public-watchalong-export-v1":fail("wrong_schema_version")
    events=raw.get("events")
    if not isinstance(events,list):raise ValueError("events must be an array")
    if raw.get("event_count")!=len(events):fail("event_count_mismatch")
    event_ids=set()
    streams=0
    matches={day:[] for day in EXPECTED_DAYS}
    for i,event in enumerate(events):
        if not isinstance(event,dict):fail(f"event_{i}_not_object");continue
        if set(event)!=EVENT_KEYS:fail(f"event_{i}_unexpected_fields")
        eid=event.get("event_id")
        if not isinstance(eid,str) or not re.fullmatch(r"watch:[0-9a-f]{20}",eid):fail(f"event_{i}_id_invalid")
        if eid in event_ids:fail(f"event_{i}_duplicate")
        event_ids.add(eid)
        if not isinstance(event.get("source_url"),str) or not URL.fullmatch(event["source_url"]):fail(f"event_{i}_invalid_provenance")
        hosts=event.get("streams")
        if not isinstance(hosts,list) or not hosts:fail(f"event_{i}_orphan");continue
        streams+=len(hosts)
        for j,host in enumerate(hosts):
            if not isinstance(host,dict) or set(host)!=HOST_KEYS:fail(f"event_{i}_host_{j}_fields");continue
            if not isinstance(host.get("video_id"),str) or not VIDEO.fullmatch(host["video_id"]):fail(f"event_{i}_host_{j}_video")
        if event.get("day") in matches and CALIBRATION.search(str(event.get("description",""))):
            matches[event["day"]].append(eid)
    for day,ids in matches.items():
        if len(ids)!=1:fail(f"mushoku_{day}_count_{len(ids)}")
    if len({v[0] for v in matches.values() if len(v)==1})!=len(EXPECTED_DAYS):
        fail("mushoku_not_three_distinct_events")
    if streams<len(events):fail("streams_less_than_events")
    sql=sql_path.read_text(encoding="utf-8")
    if not sql.rstrip().endswith("COMMIT;"):fail("sql_no_commit")
    if "BEGIN TRANSACTION;" not in sql:fail("sql_no_begin")
    tables=set(SQL_TABLE.findall(sql))
    if tables != ALLOWED_TABLES:fail("sql_write_tables_mismatch")
    if FORBIDDEN.search(sql) or FORBIDDEN.search(json.dumps(raw,ensure_ascii=False)):
        fail("forbidden_internal_payload_marker")
    result={"status":"PASS" if not problems else "BLOCKED","events":len(events),
        "streams":streams,"unique_event_ids":len(event_ids)==len(events),
        "mushoku_3_of_3":all(len(v)==1 for v in matches.values()),
        "sql_tables":sorted(tables),"issues":problems,
        "sha256_sql":hashlib.sha256(sql_path.read_bytes()).hexdigest(),
        "sha256_json":hashlib.sha256(json_path.read_bytes()).hexdigest(),
        "sql":str(sql_path),"json":str(json_path)}
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--sql",type=Path,required=True)
    p.add_argument("--json",type=Path,required=True)
    args=p.parse_args()
    try:
        receipt=audit(args.sql,args.json)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        receipt={"status":"BLOCKED","issues":[f"unreadable_or_invalid_artifact: {type(exc).__name__}"]}
    print(json.dumps(receipt,ensure_ascii=False,sort_keys=True))
    return 0 if receipt["status"]=="PASS" else 2

if __name__=="__main__":
    sys.exit(main())
