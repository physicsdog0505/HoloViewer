#!/usr/bin/env python3
"""Read-only canonical profile artifact exporter for PR #155 rollout.

Reads the already-live Today approved roster + verified legacy profile table from
the existing Production D1 and merges the already-reviewed support-color export
into one deterministic local canonical-profile artifact.

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
SUPPORT_COUNT=66
SUPPORT_COLORED=57
SUPPORT_NEUTRAL=9
SUPPORT_DUAL=1
SUPPORT_SEMANTICS="2025_6th_fes_penlight"
CID=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HEX=re.compile(r"^#[0-9A-Fa-f]{6}$")
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

def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_support_colors(path):
    """Mirror worker_host/today/support-colors.mjs validation/projection.

    The input is the already-reviewed 4174/8501 legacy-66 support-color export.
    Invalid color evidence fails closed to neutral; channel identity is never
    inferred from a name/title/label.
    """
    payload=json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version")!=1 or payload.get("fallback")!="neutral":
        raise SystemExit("invalid support-color export header")
    rows=payload.get("channels")
    if not isinstance(rows,list) or len(rows)!=SUPPORT_COUNT:
        raise SystemExit(f"support-color export must contain exact {SUPPORT_COUNT} rows")

    output={}
    seen=set()
    colored=neutral=dual=0
    for row in rows:
        cid=row.get("channel_id")
        if not isinstance(cid,str) or not CID.fullmatch(cid) or cid in seen:
            raise SystemExit("invalid/duplicate support-color channel identity")
        seen.add(cid)

        community=(row.get("verification_status")=="community"
                   and row.get("color_semantics")==SUPPORT_SEMANTICS)
        verified=row.get("verification_status")=="verified"
        mode=row.get("display_mode")
        projected={
          "member_accent":None,
          "member_accent_dual":None,
          "support_mode":"neutral",
          "support_color_source":None,
        }

        if mode=="dual_color" and community:
            colors=row.get("color_hexes")
            if (isinstance(colors,list) and len(colors)==2
                    and all(isinstance(v,str) and HEX.fullmatch(v) for v in colors)):
                projected={
                  "member_accent":colors[0].upper(),
                  "member_accent_dual":[v.upper() for v in colors],
                  "support_mode":"dual_color",
                  "support_color_source":SUPPORT_SEMANTICS,
                }
                colored+=1
                dual+=1
            else:
                raise SystemExit("invalid reviewed dual support-color row")
        elif mode=="solid" and (verified or community):
            color=row.get("color_hex")
            if not isinstance(color,str) or not HEX.fullmatch(color):
                raise SystemExit("invalid reviewed solid support-color row")
            projected={
              "member_accent":color.upper(),
              "member_accent_dual":None,
              "support_mode":"solid",
              "support_color_source":"verified" if verified else SUPPORT_SEMANTICS,
            }
            colored+=1
        elif mode=="neutral":
            neutral+=1
        else:
            # A reviewed export must not contain an untrusted mode/evidence pair.
            raise SystemExit("unsupported reviewed support-color row")

        output[cid]=projected

    if (colored,neutral,dual)!=(SUPPORT_COLORED,SUPPORT_NEUTRAL,SUPPORT_DUAL):
        raise SystemExit("support-color receipt mismatch")
    return output,{
      "rows":len(rows),
      "colored":colored,
      "neutral":neutral,
      "dual":dual,
      "sha256":file_sha256(path),
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--config",required=True)
    ap.add_argument("--support-colors-json",required=True)
    ap.add_argument("--output",default="/tmp/hv47-canonical-channel-profiles-85.json")
    args=ap.parse_args()
    config=str(Path(args.config).resolve())
    support_path=str(Path(args.support_colors_json).resolve())
    load_config(config)
    colors,color_receipt=load_support_colors(support_path)

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
    color_revision=color_receipt["sha256"][:16]
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

        support=colors.get(cid,{
          "member_accent":None,
          "member_accent_dual":None,
          "support_mode":"neutral",
          "support_color_source":None,
        })
        profiles.append({
          "channel_id":cid,
          "channel_name":title,
          "display_name":title,
          "avatar_url":avatar,
          "group":group,
          **support,
          "profile_revision":f"today-profile:{ROSTER}:{fetched}:support-colors:{color_revision}",
          "updated_at":fetched,
        })

    body={
      "schema_version":"holoviewer-channel-profile-import-v1",
      "authority":(
        "production-readonly:public_today_approved_channels+public_today_channel_profiles"
        f"+reviewed_support_colors:{color_receipt['sha256']}"
      ),
      "roster_version":ROSTER,
      "profile_count":COUNT,
      "support_color_receipt":color_receipt,
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
      "support_color_rows":color_receipt["rows"],
      "support_colored_profiles":sum(x["support_mode"]!="neutral" for x in profiles),
      "support_dual_profiles":sum(x["support_mode"]=="dual_color" for x in profiles),
      "support_color_sha256":color_receipt["sha256"],
      "groups":{g:sum(x["group"]==g for x in profiles) for g in sorted(GROUPS)},
      "secrets_exported":False,
    },ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
