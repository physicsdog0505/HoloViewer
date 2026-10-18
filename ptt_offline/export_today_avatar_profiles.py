#!/usr/bin/env python3
"""Export verified YouTube channel avatars for the exact active Today approved roster.

Read-only against production D1. Fetches official channels.list metadata using the
existing local API-key loader. Produces a local JSON receipt for separate reviewed import.
No D1 writes, Worker deploys, secrets or flags are changed.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

WORKER="holoviewer-public-api"
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
CID=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HOSTS={"yt3.ggpht.com","yt3.googleusercontent.com","yt3.google.com"}

def run(cmd, *, capture=False):
    print("+"," ".join(map(str,cmd)))
    return subprocess.run(cmd,check=True,text=True,
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

def active_roster(config):
    sql=(
      "SELECT 'TODAY_META=' || roster_version || ',' || expected_channels AS marker "
      "FROM public_today_catalog_meta WHERE singleton=1;"
      "SELECT 'TODAY_CHANNEL=' || channel_id AS marker "
      "FROM public_today_approved_channels "
      "WHERE roster_version=(SELECT roster_version FROM public_today_catalog_meta WHERE singleton=1) "
      "ORDER BY channel_id;"
    )
    out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql],capture=True).stdout
    meta=re.search(r"TODAY_META=([A-Za-z0-9._:-]+),(\d+)",out)
    ids=re.findall(r"TODAY_CHANNEL=(UC[A-Za-z0-9_-]{22})",out)
    if not meta:
        raise SystemExit("could not read active Today roster metadata")
    version=meta.group(1); expected=int(meta.group(2))
    if expected<1 or expected>500 or len(ids)!=expected or len(set(ids))!=expected or any(not CID.fullmatch(x) for x in ids):
        raise SystemExit(f"active Today roster mismatch: expected {expected}, got {len(ids)} unique={len(set(ids))}")
    return version,ids

def api_key(explicit=None):
    if explicit:
        return explicit
    from os import environ
    key=environ.get("YOUTUBE_API_KEY") or environ.get("YOUTUBE_DATA_API_KEY")
    if key:
        return key
    private=Path.home()/"Downloads"/"Hololive-PTT-Viewer"
    sys.path.insert(0,str(private))
    from youtube_metadata import load_api_key
    return load_api_key()

def fetch_profiles(ids,key):
    items=[]
    for i in range(0,len(ids),50):
        query=urlencode({"part":"snippet","id":",".join(ids[i:i+50]),"key":key})
        req=Request("https://www.googleapis.com/youtube/v3/channels?"+query,
                    headers={"Accept":"application/json","User-Agent":"HoloViewer-avatar-export/1"})
        with urlopen(req,timeout=30) as response:
            payload=json.load(response)
        batch=payload.get("items")
        if not isinstance(batch,list):
            raise SystemExit("YouTube channels.list returned malformed items")
        items.extend(batch)
    byid={}
    for item in items:
        cid=item.get("id")
        if cid not in ids or cid in byid:
            raise SystemExit("unexpected/duplicate YouTube channel ID")
        snippet=item.get("snippet") or {}
        title=snippet.get("title")
        thumbs=snippet.get("thumbnails") or {}
        thumb=thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}
        avatar=thumb.get("url")
        if not isinstance(title,str) or not title.strip():
            raise SystemExit("missing verified title for "+str(cid))
        u=urlsplit(str(avatar or ""))
        if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port:
            raise SystemExit("missing/untrusted avatar for "+str(cid))
        byid[cid]={"channel_id":cid,"channel_title":title,"avatar_url":avatar}
    missing=[cid for cid in ids if cid not in byid]
    if missing:
        raise SystemExit("provider did not return approved IDs: "+",".join(missing))
    return [byid[cid] for cid in ids]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",required=True)
    p.add_argument("--output",default="/tmp/hv47-active-roster-avatars.json")
    p.add_argument("--api-key",default=None,help="Prefer env/Keychain; do not commit keys.")
    args=p.parse_args()
    config=str(Path(args.config).resolve())
    load_config(config)
    version,ids=active_roster(config)
    rows=fetch_profiles(ids,api_key(args.api_key))
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipt={
      "status":"PASS",
      "source":"youtube_channels_list",
      "roster_version":version,
      "count":len(rows),
      "avatar_count":sum(bool(x["avatar_url"]) for x in rows),
      "fetched_at":stamp,
      "channels":rows,
    }
    if receipt["avatar_count"]!=len(ids):
        raise SystemExit("avatar export did not produce exact N/N")
    out=Path(args.output)
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "status":"PASS","roster_version":version,"roster":len(ids),"avatars":receipt["avatar_count"],
      "output":str(out),"d1_mutated":False
    },ensure_ascii=False))

if __name__=="__main__":
    main()
