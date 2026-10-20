#!/usr/bin/env python3
"""Read-only canonical profile artifact exporter for PR #155 rollout.

Reads the already-live Today approved roster + verified legacy profile table from
the existing Production D1 and writes a deterministic local JSON artifact.
No D1/Worker mutation and no provider/API-key call.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from pathlib import Path
from urllib.parse import urlsplit

WORKER="holoviewer-public-api"
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
ROSTER="today85-20261016-d0e326c0496b"
COUNT=85
CID=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
GROUPS={"hololive","holostars","mekpark","other"}
HOSTS={"yt3.ggpht.com","yt3.googleusercontent.com","yt3.google.com"}

def run_json(config, sql):
    cmd=["npx","wrangler","d1","execute",DB_NAME,"--remote","--json",
         "--config",config,"--command",sql]
    cp=subprocess.run(cmd,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit("wrangler --json returned non-JSON output") from exc

def collect_results(node):
    rows=[]
    if isinstance(node,dict):
        if isinstance(node.get("results"),list):
            rows.extend(x for x in node["results"] if isinstance(x,dict))
        for value in node.values():
            rows.extend(collect_results(value))
    elif isinstance(node,list):
        for value in node:
            rows.extend(collect_results(value))
    return rows

def load_config(path):
    cfg=json.loads(Path(path).read_text(encoding="utf-8"))
    if cfg.get("name")!=WORKER:
        raise SystemExit("wrong Worker config")
    db=next((x for x in cfg.get("d1_databases",[]) if x.get("binding")=="DB"),None)
    if not db or db.get("database_name")!=DB_NAME or db.get("database_id")!=DB_ID:
        raise SystemExit("wrong D1 binding")

def safe_avatar(value):
    u=urlsplit(str(value or ""))
    if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port:
        raise SystemExit("untrusted/missing avatar_url")
    return value

def canonical_bytes(body):
    return (json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True)
    ap.add_argument("--output",default="/tmp/hv47-canonical-channel-profiles-85.json")
    args=ap.parse_args()
    config=str(Path(args.config).resolve())
    load_config(config)

    meta=collect_results(run_json(config,
      "SELECT roster_version,expected_channels FROM public_today_catalog_meta WHERE singleton=1;"))
    if len(meta)!=1 or meta[0].get("roster_version")!=ROSTER or int(meta[0].get("expected_channels") or 0)!=COUNT:
        raise SystemExit("active Today roster/version does not match reviewed 85-channel authority")

    sql="""SELECT ac.channel_id,ac.channel_group,p.channel_title,p.avatar_url,p.fetched_at,p.source
FROM public_today_approved_channels ac
LEFT JOIN public_today_channel_profiles p ON p.channel_id=ac.channel_id
WHERE ac.roster_version=(SELECT roster_version FROM public_today_catalog_meta WHERE singleton=1)
ORDER BY ac.channel_id;"""
    rows=collect_results(run_json(config,sql))
    if len(rows)!=COUNT:
        raise SystemExit(f"expected {COUNT} approved profile rows, got {len(rows)}")
    seen=set(); profiles=[]
    for row in rows:
        cid=row.get("channel_id"); group=row.get("channel_group")
        title=row.get("channel_title"); avatar=row.get("avatar_url")
        fetched=row.get("fetched_at"); source=row.get("source")
        if not isinstance(cid,str) or not CID.fullmatch(cid) or cid in seen:
            raise SystemExit("invalid/duplicate channel_id")
        seen.add(cid)
        if group not in GROUPS:
            raise SystemExit("invalid channel_group")
        if not isinstance(title,str) or not title.strip():
            raise SystemExit("missing verified channel_title")
        safe_avatar(avatar)
        if not isinstance(fetched,str) or not fetched:
            raise SystemExit("missing fetched_at")
        if source!="youtube_channels_list":
            raise SystemExit("unexpected legacy profile source")
        profiles.append({
          "channel_id":cid,
          "channel_name":title,
          "display_name":title,
          "avatar_url":avatar,
          "group":group,
          "member_accent":None,
          "member_accent_dual":None,
          "support_mode":"neutral",
          "support_color_source":None,
          "profile_revision":f"today-profile:{ROSTER}:{fetched}",
          "updated_at":fetched,
        })

    body={
      "schema_version":"holoviewer-channel-profile-import-v1",
      "authority":"production-readonly:public_today_approved_channels+public_today_channel_profiles",
      "roster_version":ROSTER,
      "profile_count":COUNT,
      "profiles":profiles,
    }
    raw=canonical_bytes(body)
    out=Path(args.output)
    out.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    print(json.dumps({
      "status":"PASS",
      "production_mutation":False,
      "artifact":str(out),
      "sha256":digest,
      "profile_count":len(profiles),
      "roster_version":ROSTER,
      "avatar_count":sum(bool(x["avatar_url"]) for x in profiles),
      "groups":{g:sum(x["group"]==g for x in profiles) for g in sorted(GROUPS)},
      "secrets_exported":False,
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
