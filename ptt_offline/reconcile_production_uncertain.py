#!/usr/bin/env python3
"""Reconcile exactly one committed-but-unacknowledged production PTT batch, then restart.

This helper never retries the uncertain batch. It reconstructs the pending batch from
the canonical Collector source + persisted source identity, proves the same rows are
already visible through Public GET and D1 replay evidence, advances only local state,
then restarts the existing recurring Publisher with the existing aligned secrets.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from pathlib import Path
from urllib.request import Request, urlopen

from .activate_production_publisher import API, BROWSER_USER_AGENT, DB_NAME, start_publisher
from .collector_source_preview import open_source
from .live_capture_publisher import (
    OUTPUT_KEYS, active_article_ids, content_digest, inspect_latest_article, state_for_source,
)
from .owner_publisher_once import sign_time_proof
from .publisher_cli import atomic_receipt
from .resumable_publisher import make_batch, new_checkpoint
from .public_today_contract import ContractError

def shquote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def run(cmd):
    return subprocess.run(cmd,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)

def find_uncertain_state(state_dir: Path):
    states=[]
    for path in sorted(state_dir.glob("*.json")):
        try:
            body=json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if body.get("status")=="REMOTE_UNCERTAIN":
            states.append((path,body))
    if len(states)!=1:
        raise SystemExit(f"expected exactly one REMOTE_UNCERTAIN state, found {len(states)}")
    return states[0]

def reconstruct_pending(source: str, state: dict, time_secret: str, batch_cap=25):
    source_identity=state.get("source_identity")
    accepted=dict(state.get("accepted") or {})
    pending_id=state.get("pending_batch_id")
    if not isinstance(source_identity,str) or len(source_identity)!=64 or not isinstance(pending_id,str):
        raise SystemExit("invalid uncertain-state identity")

    with open_source(source) as db:
        matched=None
        for article_id in active_article_ids(db,limit=8):
            plan=inspect_latest_article(db,article_id=article_id)
            if plan.get("source_identity")==source_identity:
                matched=plan
                break
        if matched is None:
            raise SystemExit("uncertain source is no longer in bounded active-AID window")

    missing=[]
    for row in matched["candidate_rows"]:
        key=row["source_record_key"]
        digest=content_digest(row)
        if key in accepted and accepted[key]!=digest:
            raise SystemExit("ACKed local source row mutated; refusing reconcile")
        if key not in accepted:
            missing.append(dict(row))
    selected=missing[:batch_cap]
    if not selected:
        raise SystemExit("no local rows available to reconstruct uncertain batch")
    for row in selected:
        row["time_proof"]=sign_time_proof(row,time_secret)
    rows=[{k:r.get(k) for k in OUTPUT_KEYS} for r in selected]
    day=rows[0]["day"]
    rows=[r for r in rows if r["day"]==day]
    cp=new_checkpoint(source_identity=source_identity,day=day,aids=[matched["aid"]])
    batch=make_batch(checkpoint=cp,rows=rows,batch_cap=batch_cap)
    if batch["batch_id"]!=pending_id:
        raise SystemExit(f"reconstructed batch mismatch: expected {pending_id}, got {batch['batch_id']}")
    return matched,batch,accepted

def public_rows(day: str):
    req=Request(API+f"/v1/ptt/today?day={day}&limit=300",
                headers={"Accept":"application/json","User-Agent":BROWSER_USER_AGENT})
    with urlopen(req,timeout=30) as response:
        body=json.loads(response.read())
    rows=body.get("pushes")
    if not isinstance(rows,list):
        raise SystemExit("Public PTT response missing pushes")
    return {row.get("push_id"):row for row in rows if isinstance(row,dict)}

def verify_public(batch):
    got=public_rows(batch["day"])
    compare=("push_id","aid","source_line","kind","author","content","occurred_at","floor","source_url")
    for row in batch["rows"]:
        remote=got.get(row["push_id"])
        if remote is None:
            raise SystemExit("uncertain batch is not fully visible in Public GET")
        for key in compare:
            if remote.get(key)!=row.get(key):
                raise SystemExit(f"Public row mismatch for {row['push_id']} field {key}")

def parse_marker(output: str, name: str) -> int:
    match=re.search(rf"{re.escape(name)}=(\d+)",output)
    if not match:
        raise SystemExit("could not parse D1 reconcile marker "+name)
    return int(match.group(1))

def verify_d1_evidence(config: str, batch):
    push_ids=",".join(shquote(row["push_id"]) for row in batch["rows"])
    evidence_terms=" OR ".join(
        f"(day={shquote(row['day'])} AND aid={shquote(row['aid'])} AND source_record_key={shquote(row['source_record_key'])} AND push_id={shquote(row['push_id'])})"
        for row in batch["rows"]
    )
    sql=(
        f"SELECT 'PTT_RECON_PUSHES=' || COUNT(*) AS marker FROM ptt_pushes WHERE push_id IN ({push_ids});"
        f"SELECT 'PTT_RECON_EVIDENCE=' || COUNT(*) AS marker FROM ptt_source_evidence WHERE {evidence_terms};"
    )
    out=run(["npx","wrangler","d1","execute",DB_NAME,"--remote","--config",config,"--command",sql]).stdout
    expected=len(batch["rows"])
    if parse_marker(out,"PTT_RECON_PUSHES")!=expected or parse_marker(out,"PTT_RECON_EVIDENCE")!=expected:
        raise SystemExit("D1 reconcile counts do not prove the whole pending batch")

def reconcile_state(path: Path, matched, batch, accepted):
    for row in batch["rows"]:
        accepted[row["source_record_key"]]=content_digest(row)
    atomic_receipt(path,{
        "status":"ACKED",
        "source_identity":matched["source_identity"],
        "accepted":accepted,
        "last_batch_id":batch["batch_id"],
        "pending_count":len(matched.get("pending_source_lines") or []),
        "reconciled_from_remote_commit":True,
    })

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--config",required=True)
    p.add_argument("--source",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/"hololive_ptt.sqlite3"))
    p.add_argument("--state-root",default=str(Path.home()/"Downloads"/"Hololive-PTT-Viewer"/".ptt-publisher-state"))
    args=p.parse_args()
    if not args.apply:
        raise SystemExit("refusing local reconcile/restart without --apply")
    repo_root=Path(__file__).resolve().parents[1]
    state_root=Path(args.state_root).expanduser().resolve()
    state_dir=state_root/"state"
    secrets_path=state_root/".publisher-secrets.json"
    if not secrets_path.is_file():
        raise SystemExit("publisher secrets file missing")
    secrets=json.loads(secrets_path.read_text(encoding="utf-8"))
    time_secret=secrets.get("PTT_TIME_AUTHORITY_SECRET","")
    if not isinstance(time_secret,str) or len(time_secret)<32:
        raise SystemExit("time-authority secret unavailable")
    source=str(Path(args.source).expanduser().resolve(strict=True))
    config=str(Path(args.config).resolve())

    state_path,state=find_uncertain_state(state_dir)
    matched,batch,accepted=reconstruct_pending(source,state,time_secret,batch_cap=25)
    verify_public(batch)
    verify_d1_evidence(config,batch)
    reconcile_state(state_path,matched,batch,accepted)

    process=start_publisher(repo_root,source,state_root,secrets_path)
    print(json.dumps({
        "status":"RECONCILED_AND_RESTARTED",
        "reconciled_batch_id":batch["batch_id"],
        "rows_reconciled":len(batch["rows"]),
        "day":batch["day"],
        "aid":matched["aid"],
        "process":process,
        "remote_batch_retried":False,
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
