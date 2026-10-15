#!/usr/bin/env python3
"""Backend-only release helper for Today lifecycle cadence + verified legacy-66 avatars.

Targets only existing holoviewer-public-api / holoviewer-public-v1.
No frontend Worker, no site files, no UI mutation.
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile
from pathlib import Path

from .activate_today_profiles import WORKER, DB_NAME, DB_ID

PTT_SECRET_NAMES={
 "PTT_PUBLISH_HMAC_SECRET","PTT_TIME_AUTHORITY_SECRET","PTT_PUBLISH_ENABLED",
 "PTT_PUBLISH_MAX_ROWS","PTT_PUBLISH_MAX_BYTES","PTT_PUBLISH_MAX_QUERIES","PTT_PUBLISH_MAX_WRITES"
}
REQUIRED_SECRET_NAMES={"YOUTUBE_API_KEY","PTT_PUBLISH_HMAC_SECRET","PTT_TIME_AUTHORITY_SECRET","PTT_PUBLISH_ENABLED"}

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

def safe_deploy_config(config_path):
    cfg=load_config(config_path)
    cfg=json.loads(json.dumps(cfg))
    vars=dict(cfg.get("vars") or {})
    # PTT writer settings are now production secrets. Never let an old plaintext
    # config value overwrite those secret bindings during Today source deploy.
    for name in PTT_SECRET_NAMES:
        vars.pop(name,None)
    vars["TODAY_CADENCE_ENABLED"]="true"
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
    args=p.parse_args()
    if not args.apply:
        raise SystemExit("refusing backend release without --apply")
    repo_root=Path(__file__).resolve().parents[1]
    config=str(Path(args.config).resolve())
    load_config(config)
    secrets=secret_names(config)

    # 1) Activate verified legacy profiles on D1 + existing read path.
    run([__import__("sys").executable,"-B","-m","ptt_offline.activate_today_profiles",
         "--apply","--config",config,"--profiles-json",args.profiles_json])

    # 2) Deploy only the SAME existing API Worker with backend cadence source.
    td,deploy_cfg=safe_deploy_config(config)
    try:
        run(["npx","wrangler","deploy",str(repo_root/"ptt_offline"/"worker_host"/"index.mjs"),
             "--name",WORKER,"--config",str(deploy_cfg)])
    finally:
        td.cleanup()

    print(json.dumps({
      "status":"TODAY_BACKEND_RELEASE_DEPLOYED",
      "worker":WORKER,
      "database":DB_NAME,
      "frontend_changed":False,
      "api_contract_changed":False,
      "profile_rows_expected":66,
      "today_cadence_enabled":True,
      "preserved_secret_bindings":secrets
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
