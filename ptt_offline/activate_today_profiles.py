#!/usr/bin/env python3
"""Activate verified legacy-66 Today channel profiles on existing production API.

No Worker source deploy. Uses existing holoviewer-public-api code path already
supporting TODAY_PROFILES_ENABLED and public_today_channel_profiles.
"""
from __future__ import annotations
import argparse, json, re, subprocess, tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

WORKER="holoviewer-public-api"
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
API="https://holoviewer-public-api.singlebagel.workers.dev"
CID=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HOSTS={"yt3.ggpht.com","yt3.googleusercontent.com","yt3.google.com"}

def run(cmd, *, capture=False, input_text=None):
    print("+"," ".join(map(str,cmd)))
    return subprocess.run(cmd,check=True,text=True,input=input_text,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None)

def q(value):
    return "'" + str(value).replace("'","''") + "'"

def load_config(path):
    cfg=json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("name")!=WORKER:
        raise SystemExit("wrong Worker config")
    db=next((x for x in cfg.get("d1_databases",[]) if x.get("binding")=="DB"),None)
    if not db or db.get("database_name")!=DB_NAME or db.get("database_id")!=DB_ID:
        raise SystemExit("wrong D1 binding")
    return cfg

def validated_profiles(path):
    body=json.loads(Path(path).read_text(encoding="utf-8"))
    rows=body.get("channels")
    if body.get("count")!=66 or body.get("avatar_count")!=66 or not isinstance(rows,list) or len(rows)!=66:
        raise SystemExit("avatar receipt must be exact 66/66")
    seen=set()
    clean=[]
    for row in rows:
        cid=row.get("channel_id"); title=row.get("channel_title"); avatar=row.get("avatar_url")
        if not isinstance(cid,str) or not CID.fullmatch(cid) or cid in seen:
            raise SystemExit("invalid/duplicate profile channel")
        seen.add(cid)
        if not isinstance(title,str) or not title.strip():
            raise SystemExit("missing verified profile title")
        u=urlsplit(str(avatar or ""))
        if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port:
            raise SystemExit("untrusted profile avatar")
        clean.append((cid,title,avatar))
    return clean, body.get("fetched_at")

def active_roster_version(config):
    sql="SELECT 'TODAY_ROSTER=' || roster_version AS marker FROM public_today_catalog_meta WHERE singleton=1;"
    out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql],capture=True).stdout
    m=re.search(r"TODAY_ROSTER=([A-Za-z0-9._:-]+)",out)
    if not m:
        raise SystemExit("could not read active Today roster version")
    return m.group(1)

def ensure_schema(config):
    sql="""CREATE TABLE IF NOT EXISTS public_today_channel_profiles (
 channel_id TEXT PRIMARY KEY,
 roster_version TEXT NOT NULL,
 channel_title TEXT NOT NULL,
 avatar_url TEXT,
 fetched_at TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source='youtube_channels_list')
);"""
    run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql])

def import_profiles(config,rows,fetched_at,roster_version):
    if not isinstance(fetched_at,str) or not fetched_at:
        raise SystemExit("avatar export missing fetched_at")
    lines=["BEGIN TRANSACTION;"]
    for cid,title,avatar in rows:
        lines.append(
          "INSERT INTO public_today_channel_profiles(channel_id,roster_version,channel_title,avatar_url,fetched_at,source) VALUES ("+
          ",".join(map(q,[cid,roster_version,title,avatar,fetched_at,"youtube_channels_list"]))+
          ") ON CONFLICT(channel_id) DO UPDATE SET roster_version=excluded.roster_version,"
          "channel_title=excluded.channel_title,avatar_url=excluded.avatar_url,"
          "fetched_at=excluded.fetched_at,source=excluded.source;"
        )
    lines.append("COMMIT;")
    with tempfile.NamedTemporaryFile("w",suffix=".sql",delete=False,encoding="utf-8") as f:
        f.write("\n".join(lines)+"\n"); sql_path=f.name
    try:
        run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--file",sql_path])
    finally:
        Path(sql_path).unlink(missing_ok=True)

def verify_rows(config, roster_version):
    sql=(
      "SELECT 'PROFILE_COUNTS=' || COUNT(*) || ',' || "
      "SUM(CASE WHEN avatar_url IS NOT NULL AND avatar_url<>'' THEN 1 ELSE 0 END) AS marker "
      "FROM public_today_channel_profiles WHERE roster_version="+q(roster_version)+";"
    )
    out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql],capture=True).stdout
    m=re.search(r"PROFILE_COUNTS=(\d+),(\d+)",out)
    if not m or tuple(map(int,m.groups()))!=(66,66):
        raise SystemExit("profile readback is not exact 66/66")
    return {"rows":66,"avatars":66}

def enable_profiles(config):
    run(["npx","wrangler","secret","put","TODAY_PROFILES_ENABLED","--name",WORKER,"--config",config],
        input_text="true\n")

def verify_public():
    req=Request(API+"/v1/catalog/today",headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with urlopen(req,timeout=30) as r:
        body=json.load(r)
    streams=body.get("streams")
    if not isinstance(streams,list):
        raise SystemExit("Today API missing streams")
    return {
      "http":200,
      "streams":len(streams),
      "streams_with_avatar":sum(bool(x.get("avatar_url")) for x in streams if isinstance(x,dict)),
      "freshness":body.get("freshness"),
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--config",required=True)
    p.add_argument("--profiles-json",default="/tmp/hv47-legacy-avatars.json")
    args=p.parse_args()
    if not args.apply:
        raise SystemExit("refusing production profile activation without --apply")
    config=str(Path(args.config).resolve())
    load_config(config)
    rows,fetched_at=validated_profiles(args.profiles_json)
    roster_version=active_roster_version(config)
    ensure_schema(config)
    import_profiles(config,rows,fetched_at,roster_version)
    receipt=verify_rows(config,roster_version)
    enable_profiles(config)
    public=verify_public()
    print(json.dumps({
      "status":"TODAY_PROFILES_ENABLED",
      "active_roster_version":roster_version,
      "profile_readback":receipt,
      "public_readback":public,
      "worker_source_deployed":False,
      "public_catalog_touched":False
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
