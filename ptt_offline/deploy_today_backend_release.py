#!/usr/bin/env python3
"""Backend-only release helper for Today lifecycle cadence + verified legacy-66 avatars.

Targets only existing holoviewer-public-api / holoviewer-public-v1.
No frontend Worker, no site files, no UI mutation.
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .activate_today_profiles import WORKER, DB_NAME, DB_ID

PTT_SECRET_NAMES={
 "PTT_PUBLISH_HMAC_SECRET","PTT_TIME_AUTHORITY_SECRET","PTT_PUBLISH_ENABLED",
 "PTT_PUBLISH_MAX_ROWS","PTT_PUBLISH_MAX_BYTES","PTT_PUBLISH_MAX_QUERIES","PTT_PUBLISH_MAX_WRITES"
}
REQUIRED_SECRET_NAMES={"YOUTUBE_API_KEY","PTT_PUBLISH_HMAC_SECRET","PTT_TIME_AUTHORITY_SECRET","PTT_PUBLISH_ENABLED"}
API="https://holoviewer-public-api.singlebagel.workers.dev"

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

def secret_names(config):
    out=run(["npx","wrangler","secret","list","--name",WORKER,"--config",config],capture=True).stdout
    found={name for name in REQUIRED_SECRET_NAMES|PTT_SECRET_NAMES|{"TODAY_PROFILES_ENABLED"} if name in out}
    missing=REQUIRED_SECRET_NAMES-found
    if missing:
        raise SystemExit("required production secrets missing: "+",".join(sorted(missing)))
    return sorted(found)

def ptt_operational_day(now=None):
    local=(now or datetime.now(ZoneInfo("Asia/Taipei"))).astimezone(ZoneInfo("Asia/Taipei"))
    day=local.date()-timedelta(days=1) if local.hour<6 else local.date()
    return day.isoformat()

def verify_ptt_rollout(state_root, config):
    metrics=Path(state_root)/"minute-metrics.jsonl"
    if not metrics.is_file():
        raise SystemExit("PTT metrics missing; refusing Today release")
    ack=None
    for line in metrics.read_text(encoding="utf-8").splitlines()[-200:]:
        try: row=json.loads(line)
        except Exception: continue
        if row.get("status")=="ACK" and row.get("publisher_mode")=="OWNER_APPROVED_SEND":
            ack=row
    if ack is None:
        raise SystemExit("no post-restart PTT ACK receipt yet; refusing Today release")

    # Do not infer the validation day from wall clock near the 06:00 Taipei
    # operational rollover. Read the most recent successfully published day
    # from canonical production provider state instead.
    sql=("SELECT 'PTT_LAST_DAY=' || day AS marker FROM ptt_provider_state "
         "WHERE last_success_at IS NOT NULL ORDER BY last_success_at DESC LIMIT 1;")
    out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql],
            capture=True).stdout
    match=__import__("re").search(r"PTT_LAST_DAY=(\d{4}-\d{2}-\d{2})",out)
    if not match:
        raise SystemExit("could not resolve latest successful PTT provider day")
    day=match.group(1)

    req=Request(API+"/v1/ptt/today?day="+day+"&limit=10",
                headers={"Accept":"application/json","User-Agent":"Mozilla/5.0"})
    with urlopen(req,timeout=30) as response:
        body=json.load(response)
        if response.status!=200:
            raise SystemExit("PTT Public GET not healthy")
    pushes=body.get("pushes")
    if not isinstance(pushes,list) or not pushes:
        raise SystemExit("PTT Public GET returned no pushes")
    return {"ack":ack,"day":day,"public_http":200,"public_pushes":len(pushes)}

def validated_support_colors(path):
    body=json.loads(Path(path).read_text(encoding="utf-8"))
    if body.get("schema_version")!=1 or body.get("fallback")!="neutral":
        raise SystemExit("invalid support-color export header")
    rows=body.get("channels")
    if not isinstance(rows,list) or len(rows)!=66:
        raise SystemExit("support-color export must contain exact legacy 66 rows")
    ids=[row.get("channel_id") for row in rows]
    if len(set(ids))!=66 or any(not isinstance(x,str) or not x.startswith("UC") or len(x)!=24 for x in ids):
        raise SystemExit("invalid support-color channel identities")
    colored=0; neutral=0; dual=0
    for row in rows:
        mode=row.get("display_mode")
        if mode=="dual_color":
            colors=row.get("color_hexes")
            if not isinstance(colors,list) or len(colors)!=2:
                raise SystemExit("invalid dual support-color row")
            dual+=1; colored+=1
        elif mode=="solid":
            if not isinstance(row.get("color_hex"),str):
                raise SystemExit("invalid solid support-color row")
            colored+=1
        elif mode=="neutral":
            neutral+=1
        else:
            raise SystemExit("invalid support-color display mode")
    if (colored,neutral,dual)!=(57,9,1):
        raise SystemExit("support-color receipt mismatch")
    return json.dumps(body,ensure_ascii=False,separators=(",",":"))

def safe_deploy_config(config_path, support_colors_path):
    cfg=load_config(config_path)
    cfg=json.loads(json.dumps(cfg))
    vars=dict(cfg.get("vars") or {})
    # PTT writer settings are now production secrets. Never let an old plaintext
    # config value overwrite those secret bindings during Today source deploy.
    for name in PTT_SECRET_NAMES:
        vars.pop(name,None)
    vars["TODAY_CADENCE_ENABLED"]="true"
    vars["TODAY_DISCOVERY_ENABLED"]="false"
    # Cloudflare deploy replaces Worker vars from this config. Re-materialize the
    # owner-verified legacy-66 support-color payload on every backend release so
    # later backend deploys cannot silently erase card/channel styling metadata.
    for name in list(vars):
        if name=="TODAY_SUPPORT_COLORS_JSON" or name.startswith("TODAY_SUPPORT_COLORS_JSON_"):
            vars.pop(name,None)
    color_payload=validated_support_colors(support_colors_path)
    chunk_size=7000
    chunks=[color_payload[i:i+chunk_size] for i in range(0,len(color_payload),chunk_size)]
    for i,chunk in enumerate(chunks):
        vars[f"TODAY_SUPPORT_COLORS_JSON_{i}"]=chunk
    cfg["vars"]=vars
    td=tempfile.TemporaryDirectory(prefix="holoviewer-today-release-")
    path=Path(td.name)/"wrangler.json"
    path.write_text(json.dumps(cfg,ensure_ascii=True,indent=2)+"\n",encoding="utf-8")
    return td,path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--config",required=True)
    p.add_argument("--profiles-json",default="/tmp/hv47-legacy-avatars.json")
    p.add_argument("--support-colors-json",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/"holoviewer-channel-support-colors.json"))
    p.add_argument("--ptt-state-root",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/".ptt-publisher-state"))
    args=p.parse_args()
    if not args.apply:
        raise SystemExit("refusing backend release without --apply")
    repo_root=Path(__file__).resolve().parents[1]
    config=str(Path(args.config).resolve())
    load_config(config)
    secrets=secret_names(config)
    ptt=verify_ptt_rollout(args.ptt_state_root, config)

    # 1) Activate verified legacy profiles on D1 + existing read path.
    run([__import__("sys").executable,"-B","-m","ptt_offline.activate_today_profiles",
         "--apply","--config",config,"--profiles-json",args.profiles_json])

    # 2) Apply only the isolated additive discovery queue/cursor schema.
    discovery_schema=repo_root/"ptt_offline"/"worker_host"/"today"/"discovery-only.sql"
    run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,
         "--file",str(discovery_schema)])

    # 3) Deploy only the SAME existing API Worker with backend cadence/discovery source.
    td,deploy_cfg=safe_deploy_config(config,args.support_colors_json)
    try:
        run(["npx","wrangler","deploy",str(repo_root/"ptt_offline"/"worker_host"/"index.mjs"),
             "--name",WORKER,"--config",str(deploy_cfg)])
    finally:
        td.cleanup()

    # 4) After the fixed Worker is live, remove only #96 non-livestream
    # canonical pollution. Idempotent and scoped to processed discovery events.
    cleanup=repo_root/"ptt_offline"/"worker_host"/"today"/"cleanup-discovery-nonlive.sql"
    run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,
         "--file",str(cleanup)])
    verify_sql=("SELECT 'NONLIVE_DISCOVERY_ROWS=' || COUNT(*) AS marker "
                "FROM public_today_canonical c "
                "WHERE c.video_id IN (SELECT e.video_id FROM public_today_websub_events e "
                "WHERE e.status='processed' AND e.video_id IS NOT NULL) "
                "AND c.lifecycle_state='unknown' "
                "AND c.scheduled_start IS NULL AND c.actual_start IS NULL AND c.actual_end IS NULL "
                "AND c.lifecycle_observed_at>='2026-10-15T22:22:00Z';")
    verify_out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,
                    "--command",verify_sql],capture=True).stdout
    marker=__import__("re").search(r"NONLIVE_DISCOVERY_ROWS=(\d+)",verify_out)
    if not marker or int(marker.group(1))!=0:
        raise SystemExit("non-live discovery cleanup did not converge to zero")

    print(json.dumps({
      "status":"TODAY_BACKEND_RELEASE_DEPLOYED",
      "worker":WORKER,
      "database":DB_NAME,
      "frontend_changed":False,
      "api_contract_changed":False,
      "profile_rows_expected":66,
      "support_colors_expected":{"rows":66,"colored":57,"neutral":9,"dual":1},
      "today_cadence_enabled":True,
      "today_discovery_enabled":False,
      "nonlive_discovery_rows_after_cleanup":0,
      "preserved_secret_bindings":secrets,
      "ptt_preflight":ptt
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
