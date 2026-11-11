#!/usr/bin/env python3
"""#47 legacy channel avatar export: read-only YouTube fetch -> reviewed SQL artifact.

No Cloudflare operation. API key sourced from existing private app Keychain loader.
Output is local; do not commit raw URLs until owner approves release snapshot.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen, Request
from datetime import datetime, timezone

CID = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
HOSTS = {"yt3.ggpht.com", "yt3.googleusercontent.com", "yt3.google.com"}

def quote(v):
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default=str(Path(__file__).with_name("legacy-66.roster.json")))
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--json-output", type=Path)
    ap.add_argument("--api-key", default=None, help="Avoid this: prefer env/Keychain")
    ap.add_argument("--roster-version", default="legacy-66-avatar-release-20261016")
    args = ap.parse_args()
    raw = json.loads(Path(args.roster).read_text())
    ids = [x["channel_id"] for x in raw["channels"]]
    if len(ids)!=66 or len(set(ids))!=66 or any(not CID.fullmatch(x) for x in ids):
        raise SystemExit("FAIL: expected 66 unique valid channel IDs")
    key = args.api_key
    if not key:
        from os import environ
        key = environ.get("YOUTUBE_API_KEY") or environ.get("YOUTUBE_DATA_API_KEY")
    if not key:
        # Uses the existing private application's macOS Keychain integration.
        private = Path.home()/"Downloads"/"Hololive-PTT-Viewer"
        sys.path.insert(0,str(private))
        from youtube_metadata import load_api_key
        key = load_api_key()
    items=[]
    for i in range(0,len(ids),50):
        q=urlencode({"part":"snippet","id":",".join(ids[i:i+50]),"key":key})
        with urlopen(Request("https://www.googleapis.com/youtube/v3/channels?"+q,
                             headers={"Accept":"application/json"}),timeout=20) as r:
            batch=json.load(r).get("items",[])
        items.extend(batch)
    byid={}
    for item in items:
        id=item.get("id")
        if id not in ids or id in byid: raise SystemExit("FAIL: unexpected/duplicate YouTube ID")
        snippet=item.get("snippet") or {}
        thumb=(snippet.get("thumbnails") or {}).get("default") or {}
        url=thumb.get("url")
        if url:
            u=urlsplit(url)
            if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port:
                raise SystemExit("FAIL: untrusted avatar host for "+id)
        title=snippet.get("title")
        if not isinstance(title,str) or not title.strip():
            raise SystemExit("FAIL: missing verified title for "+id)
        byid[id]={"channel_id":id,"channel_title":title,"avatar_url":url}
    missing=[id for id in ids if id not in byid]
    if missing: raise SystemExit("FAIL: provider did not return IDs: "+",".join(missing))
    populated=sum(bool(v["avatar_url"]) for v in byid.values())
    if populated<65: raise SystemExit(f"FAIL: only {populated}/66 avatars; release floor is 65")
    stamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines=["-- #47 verified official YouTube channels.list export; generated "+stamp,
           "-- Apply ONLY after profile table migration and #45 owner approval.",
           "-- Uses source='youtube_channels_list'; never touch public_catalog.",
           "BEGIN TRANSACTION;"]
    for id in ids:
        row=byid[id]
        lines.append("INSERT INTO public_today_channel_profiles(channel_id,roster_version,channel_title,avatar_url,fetched_at,source) "
                     "VALUES ("+",".join(map(quote,[id,args.roster_version,row["channel_title"],row["avatar_url"],stamp,"youtube_channels_list"]))+") "
                     "ON CONFLICT(channel_id) DO UPDATE SET roster_version=excluded.roster_version,"
                     "channel_title=excluded.channel_title,avatar_url=excluded.avatar_url,"
                     "fetched_at=excluded.fetched_at,source=excluded.source;")
    lines.append("COMMIT;")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text("\n".join(lines)+"\n")
    if args.json_output:
        args.json_output.write_text(json.dumps({"fetched_at":stamp,"roster_version":args.roster_version,
             "count":len(byid),"avatar_count":populated,"channels":[byid[x] for x in ids]},ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"status":"PASS","roster":len(ids),"avatars":populated,
                      "sql":str(args.output),"json":str(args.json_output) if args.json_output else None}))

if __name__=="__main__": main()
