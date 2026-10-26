#!/usr/bin/env python3
"""Owner-authorized one-shot Today backend data/deploy helper.

Scope:
- existing holoviewer-public-api only
- existing holoviewer-public-v1 / DB only
- legacy-66 support colors from verified 4174 runtime export
- existing legacy avatar rows from local hololive_stream_catalog.sqlite3
- PTT Publisher remains disabled
No frontend deploy and no schema migration.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

WORKER="holoviewer-public-api"
DB_NAME="holoviewer-public-v1"
DB_ID="64e1a0ee-1455-4377-9640-3922e8f4d061"
CID=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
AVATAR_HOSTS={"yt3.ggpht.com","yt3.googleusercontent.com","yt3.google.com"}
MAX_CHUNK=4500

def die(msg): raise SystemExit(msg)

def run(cmd, *, capture=False):
    print("+", " ".join(map(str,cmd)))
    return subprocess.run(cmd, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None)

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def validate_config(cfg):
    if cfg.get("name")!=WORKER: die("wrong Worker config")
    db=next((x for x in cfg.get("d1_databases",[]) if x.get("binding")=="DB"),None)
    if not db or db.get("database_name")!=DB_NAME or db.get("database_id")!=DB_ID:
        die("wrong D1 binding")
    if str(cfg.get("vars",{}).get("PTT_PUBLISH_ENABLED","false")).lower()=="true":
        die("PTT Publisher must remain disabled")

def load_roster(repo_root):
    p=repo_root/"ptt_offline"/"legacy-66.roster.json"
    data=load_json(p)
    ids=[x.get("channel_id") for x in data.get("channels",[])]
    if len(ids)!=66 or len(set(ids))!=66 or any(not CID.fullmatch(x or "") for x in ids):
        die("legacy-66 roster invalid")
    return ids

def load_colors(path, roster):
    data=load_json(path)
    rows=data.get("channels")
    if data.get("schema_version")!=1 or data.get("fallback")!="neutral" or not isinstance(rows,list):
        die("support-color export schema invalid")
    ids=[x.get("channel_id") for x in rows]
    if len(ids)!=66 or len(set(ids))!=66 or set(ids)!=set(roster):
        die("support-color export is not exact 66/66 legacy coverage")
    raw=json.dumps(data,ensure_ascii=True,separators=(",",":"))
    encoded=raw.encode("utf-8")
    chunks=[]
    pos=0
    while pos<len(encoded):
        end=min(pos+MAX_CHUNK,len(encoded))
        chunks.append(encoded[pos:end].decode("ascii"))
        pos=end
    if len(chunks)>16: die("support-color payload needs too many chunks")
    return data,chunks

def load_avatars(db_path, roster):
    con=sqlite3.connect(db_path)
    try:
        rows=con.execute("SELECT channel_id,avatar_url FROM channels WHERE avatar_url IS NOT NULL AND avatar_url<>''").fetchall()
    finally:
        con.close()
    allowed=set(roster); out={}
    for cid,url in rows:
        if cid not in allowed or not CID.fullmatch(cid or ""): continue
        try: u=urlparse(url)
        except Exception: continue
        if u.scheme!="https" or u.hostname not in AVATAR_HOSTS or u.username or u.password or u.port:
            continue
        out[cid]=url
    if len(out)<65: die(f"only {len(out)} verified legacy avatars found; expected at least 65")
    return out

def sql_quote(s): return "'" + s.replace("'","''") + "'"

def write_avatar_sql(path, avatars):
    lines=["-- owner-authorized legacy avatar refresh; existing public_catalog only"]
    for cid,url in sorted(avatars.items()):
        lines.append(f"UPDATE public_catalog SET avatar_url={sql_quote(url)} WHERE channel_id={sql_quote(cid)};")
    Path(path).write_text("\n".join(lines)+"\n",encoding="utf-8")

def make_config(base, chunks, out):
    cfg=json.loads(json.dumps(base))
    vars=dict(cfg.get("vars") or {})
    vars.pop("TODAY_SUPPORT_COLORS_JSON",None)
    for k in list(vars):
        if k.startswith("TODAY_SUPPORT_COLORS_JSON_"): vars.pop(k,None)
    for i,chunk in enumerate(chunks): vars[f"TODAY_SUPPORT_COLORS_JSON_{i}"]=chunk
    cfg["vars"]=vars
    Path(out).write_text(json.dumps(cfg,ensure_ascii=True,indent=2)+"\n",encoding="utf-8")

def verify_public():
    req=Request("https://holoviewer-public-api.singlebagel.workers.dev/v1/catalog/today",
                headers={"Accept":"application/json"})
    with urlopen(req,timeout=20) as r:
        body=json.load(r)
        if r.status!=200: die(f"Today readback HTTP {r.status}")
    streams=body.get("streams")
    if not isinstance(streams,list): die("Today readback missing streams")
    return {
        "http_status":200,
        "schema_version":body.get("schema_version"),
        "streams":len(streams),
        "streams_with_avatar":sum(bool(x.get("avatar_url")) for x in streams if isinstance(x,dict)),
        "streams_with_accent":sum(bool(x.get("member_accent")) for x in streams if isinstance(x,dict)),
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--existing-config",required=True)
    ap.add_argument("--runtime-root",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"))
    args=ap.parse_args()
    if not args.apply: die("refusing mutation without --apply")
    repo_root=Path(__file__).resolve().parents[1]
    runtime=Path(args.runtime_root)
    colors_path=runtime/"holoviewer-channel-support-colors.json"
    db_path=runtime/"hololive_stream_catalog.sqlite3"
    if not colors_path.is_file() or not db_path.is_file(): die("runtime color export/catalog DB missing")
    cfg=load_json(args.existing_config); validate_config(cfg)
    roster=load_roster(repo_root)
    _,chunks=load_colors(colors_path,roster)
    avatars=load_avatars(db_path,roster)
    head=run(["git","rev-parse","HEAD"],capture=True).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="holoviewer-today-final-") as td:
        td=Path(td); sql=td/"avatars.sql"; deploy_cfg=td/"wrangler.json"
        write_avatar_sql(sql,avatars); make_config(cfg,chunks,deploy_cfg)
        # Mutate only existing avatar column; no migration/table creation.
        run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--file",str(sql),"--config",str(deploy_cfg)])
        # Deploy only existing API Worker entrypoint.
        run(["npx","wrangler","deploy",str(repo_root/"ptt_offline"/"worker_host"/"index.mjs"),
             "--name",WORKER,"--config",str(deploy_cfg)])
    receipt={
        "status":"DEPLOYED",
        "git_head":head,
        "worker":WORKER,
        "database":DB_NAME,
        "legacy_support_color_rows":66,
        "support_color_chunks":len(chunks),
        "legacy_avatar_rows_written":len(avatars),
        "ptt_publisher_enabled":False,
        "public_readback":verify_public(),
    }
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
