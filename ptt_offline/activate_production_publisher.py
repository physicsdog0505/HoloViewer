#!/usr/bin/env python3
"""Owner-authorized production PTT Publisher activation helper.

Mutates only the existing holoviewer-public-api Worker and holoviewer-public-v1 D1.
Never deploys frontend, never creates a second Worker/D1, never modifies Collector DB.
"""
from __future__ import annotations
import argparse, json, os, secrets, subprocess, sys, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

WORKER="holoviewer-public-api"
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
API="https://holoviewer-public-api.singlebagel.workers.dev"
BROWSER_USER_AGENT="Mozilla/5.0"
REQUIRED_TABLES={
    "public_ptt_schema_migrations","ptt_threads","ptt_pushes",
    "ptt_provider_state","ptt_source_evidence","ptt_gap_repairs"
}
PRODUCTION_PROFILE={
    "rows":10,
    "bytes":131072,
    "queries":60,
    "writes":24,
    "max_batches":1,
    "burst_max_batches":3,
    "max_articles":4,
}
BINDINGS={
    "PTT_PUBLISH_ENABLED":"true",
    "PTT_PUBLISH_MAX_ROWS":str(PRODUCTION_PROFILE["rows"]),
    "PTT_PUBLISH_MAX_BYTES":str(PRODUCTION_PROFILE["bytes"]),
    "PTT_PUBLISH_MAX_QUERIES":str(PRODUCTION_PROFILE["queries"]),
    "PTT_PUBLISH_MAX_WRITES":str(PRODUCTION_PROFILE["writes"]),
}

def run(cmd, *, capture=False, input_text=None):
    print("+"," ".join(map(str,cmd)))
    return subprocess.run(cmd,check=True,text=True,input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None)

def load_config(path):
    cfg=json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("name")!=WORKER:
        raise SystemExit("wrong Worker config")
    db=next((x for x in cfg.get("d1_databases",[]) if x.get("binding")=="DB"),None)
    if not db or db.get("database_name")!=DB_NAME or db.get("database_id")!=DB_ID:
        raise SystemExit("wrong D1 binding")
    return cfg

def parse_table_names_output(stdout):
    # Wrangler may wrap long cells across multiple terminal lines. Parse only
    # the exact known schema identifiers from the complete captured output.
    found={name for name in REQUIRED_TABLES if name in stdout}
    if found:
        return found
    # Empty schema is a valid pre-migration state; distinguish it from a
    # Wrangler/query failure by requiring the column header to be present.
    if "name" in stdout and "sqlite_master" not in stdout:
        return set()
    raise SystemExit("could not parse D1 schema preflight")

def d1_table_names(config):
    sql=("SELECT name FROM sqlite_master WHERE type='table' AND "
         "(name LIKE 'ptt_%' OR name='public_ptt_schema_migrations') ORDER BY name;")
    r=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql],capture=True)
    return parse_table_names_output(r.stdout)

def ensure_schema(config, repo_root):
    present=d1_table_names(config)
    required_present=present & REQUIRED_TABLES
    if required_present==REQUIRED_TABLES:
        print(json.dumps({"ptt_schema":"already_present","tables":sorted(required_present)}))
        return

    legacy_without_gap=REQUIRED_TABLES-{"ptt_gap_repairs"}
    if required_present==legacy_without_gap:
        sql="""CREATE TABLE IF NOT EXISTS ptt_gap_repairs (
            repair_id TEXT PRIMARY KEY,
            day TEXT NOT NULL,
            aid TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            covered_through_cursor INTEGER NOT NULL,
            evidence_digest TEXT NOT NULL
        );"""
        run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql])
        after=d1_table_names(config)
        if not REQUIRED_TABLES.issubset(after):
            raise SystemExit("PTT additive gap-repair table readback incomplete")
        print(json.dumps({"ptt_schema":"added_gap_repairs_only","tables":sorted(REQUIRED_TABLES)}))
        return

    if required_present:
        raise SystemExit("unexpected partial PTT schema detected; refusing migration: "+",".join(sorted(required_present)))

    migration=repo_root/"ptt_offline"/"d1_migrations"/"0001_canonical_ptt.sql"
    run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--file",str(migration)])
    after=d1_table_names(config)
    if not REQUIRED_TABLES.issubset(after):
        raise SystemExit("PTT migration readback incomplete")
    print(json.dumps({"ptt_schema":"applied_v1","tables":sorted(REQUIRED_TABLES)}))

def put_secret(config,name,value):
    run(["npx","wrangler","secret","put",name,"--name",WORKER,"--config",config],input_text=value+"\n")

def write_local_secrets(state_root,hmac_secret,time_secret):
    state_root.mkdir(parents=True,exist_ok=True)
    path=state_root/".publisher-secrets.json"
    path.write_text(json.dumps({
        "PTT_PUBLISH_HMAC_SECRET":hmac_secret,
        "PTT_TIME_AUTHORITY_SECRET":time_secret,
    }),encoding="utf-8")
    os.chmod(path,0o600)
    return path

def assert_gate_open():
    req=Request(API+"/private/ptt/publish",data=b"{}",method="POST",
                headers={"Content-Type":"application/json","User-Agent":BROWSER_USER_AGENT})
    try:
        with urlopen(req,timeout=15) as r:
            code=r.status
            body=r.read(1024).decode("utf-8","replace")
    except HTTPError as e:
        code=e.code
        body=e.read(1024).decode("utf-8","replace")
    # Enabled + unsigned should fail authentication, not publisher_disabled.
    if code!=401:
        raise SystemExit(f"PTT gate verification failed: HTTP {code} {body[:200]}")
    print(json.dumps({"private_writer_gate":"enabled","unsigned_probe_http":401}))

def taipei_day():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    local=datetime.now(ZoneInfo("Asia/Taipei"))
    day=local.date()-timedelta(days=1) if local.hour<6 else local.date()
    return day.isoformat()

def public_readback():
    url=API+"/v1/ptt/today?day="+taipei_day()+"&limit=10"
    req=Request(url,headers={"Accept":"application/json","User-Agent":BROWSER_USER_AGENT})
    try:
        with urlopen(req,timeout=15) as r:
            data=json.loads(r.read())
            return {"http":r.status,"pushes":len(data.get("pushes",[])),
                    "freshness":data.get("freshness"),"completeness":data.get("completeness")}
    except HTTPError as e:
        return {"http":e.code,"body":e.read(300).decode("utf-8","replace")}

def start_publisher(repo_root, source, state_root, secrets_path):
    metrics=state_root/"minute-metrics.jsonl"
    log=state_root/"publisher.log"
    pidfile=state_root/"publisher.pid"
    if pidfile.exists():
        try:
            old=int(pidfile.read_text().strip())
            os.kill(old,0)
            raise SystemExit(f"Publisher already running PID={old}")
        except ProcessLookupError:
            pidfile.unlink(missing_ok=True)
        except ValueError:
            pidfile.unlink(missing_ok=True)

    secret_data=json.loads(secrets_path.read_text())
    env={**os.environ,
         "PTT_ALLOW_CAPTURE_TIME_POLICY":"true",
         "PTT_PUBLISH_HMAC_SECRET":secret_data["PTT_PUBLISH_HMAC_SECRET"],
         "PTT_TIME_AUTHORITY_SECRET":secret_data["PTT_TIME_AUTHORITY_SECRET"]}
    # One read-only inspection first. No network writes.
    run([sys.executable,"-B","-m","ptt_offline.recurring_publisher",
         "--source",source,"--state-dir",str(state_root/"state"),
         "--metrics",str(metrics),"--iterations","1"],capture=False)
    cmd=[sys.executable,"-B","-m","ptt_offline.recurring_publisher",
         "--source",source,"--state-dir",str(state_root/"state"),
         "--metrics",str(metrics),"--iterations","1440",
         "--batch-cap",str(PRODUCTION_PROFILE["rows"]),
         "--max-batches",str(PRODUCTION_PROFILE["max_batches"]),
         "--burst-max-batches",str(PRODUCTION_PROFILE["burst_max_batches"]),
         "--max-articles",str(PRODUCTION_PROFILE["max_articles"]),
         "--send","--approve-live-capture-policy"]
    with log.open("ab",buffering=0) as handle:
        p=subprocess.Popen(cmd,cwd=repo_root,env=env,stdout=handle,stderr=subprocess.STDOUT,
                           start_new_session=True)
    pidfile.write_text(str(p.pid)+"\n")
    os.chmod(pidfile,0o600)
    time.sleep(3)
    if p.poll() is not None:
        raise SystemExit("Publisher exited during startup; inspect "+str(log))
    return {"pid":p.pid,"log":str(log),"metrics":str(metrics),"state_dir":str(state_root/"state")}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--config",required=True)
    ap.add_argument("--source",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/"hololive_ptt.sqlite3"))
    ap.add_argument("--state-root",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/".ptt-publisher-state"))
    args=ap.parse_args()
    if not args.apply:
        raise SystemExit("refusing production activation without --apply")
    repo_root=Path(__file__).resolve().parents[1]
    source=str(Path(args.source).expanduser().resolve())
    if not Path(source).is_file():
        raise SystemExit("Collector SQLite missing: "+source)
    config=str(Path(args.config).resolve())
    load_config(config)
    ensure_schema(config,repo_root)

    state_root=Path(args.state_root).expanduser().resolve()
    hmac_secret=secrets.token_hex(32)
    time_secret=secrets.token_hex(32)
    secrets_path=write_local_secrets(state_root,hmac_secret,time_secret)

    # Rotate the two owner secrets so local Publisher and Worker are guaranteed aligned.
    put_secret(config,"PTT_PUBLISH_HMAC_SECRET",hmac_secret)
    put_secret(config,"PTT_TIME_AUTHORITY_SECRET",time_secret)
    for name,value in BINDINGS.items():
        put_secret(config,name,value)

    assert_gate_open()
    process=start_publisher(repo_root,source,state_root,secrets_path)
    receipt={
        "status":"PTT_PUBLISHER_STARTED",
        "worker":WORKER,
        "database":DB_NAME,
        "source":source,
        "cadence":"07:00-01:59 60s; 02:00-06:59 600s Asia/Taipei",
        "limits":dict(PRODUCTION_PROFILE),
        "process":process,
        "public_readback_after_start":public_readback(),
        "frontend_changed":False,
        "today_changed":False,
    }
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
