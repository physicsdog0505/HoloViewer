"""Incident-scoped canonical remap planner and one-shot repair coordinator.

Replacement rows are always reloaded from the explicit read-only Collector DB.
The remote snapshot supplies only the expected old identity. There is no caller
input for replacement content. A send uses one owner-HMAC request, retry_cap=0,
an isolated durable receipt, and never reads or writes the recurring checkpoint.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

from .collector_source_preview import open_source
from .d1_publisher import canonical_record
from .live_capture_publisher import inspect_latest_article
from .owner_http_transport import owner_signed_canonical_remap_executor, RemoteOutcomeUnknown
from .publisher_cli import atomic_receipt
from .public_today_contract import ContractError, normalize_public_aid

MAX_BATCH=5
INCIDENT_SCOPE={
    "1gwHM4TF": tuple(range(383,401)),
    "1gwRrK3P": tuple(range(1269,1291)),
}
IDENTITY_KEYS=("push_id","aid","day","source_line","kind","author","content",
               "occurred_at","floor","source_url","source_priority","source_record_key")


def _digest(value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _canonical_proof(row,source_identity,secret):
    if not isinstance(secret,str) or len(secret)<32:
        raise ContractError("canonical remap proof secret unavailable")
    message=json.dumps(["CANONICAL_SOURCE_LINE_REMAP_V1",source_identity,
        [row.get(key) for key in IDENTITY_KEYS]],ensure_ascii=False,
        separators=(",",":"))
    return hmac.new(secret.encode(),message.encode(),hashlib.sha256).hexdigest()


def _remote_snapshot(path):
    body=json.loads(Path(path).read_text(encoding="utf-8"))
    pushes=body.get("ptt_pushes")
    evidence=body.get("ptt_source_evidence")
    if not isinstance(pushes,list) or not isinstance(evidence,list):
        raise ContractError("exact remote push/evidence snapshot required")
    return pushes,evidence


def _old_identities(path,aid,lines):
    pushes,evidence=_remote_snapshot(path)
    by_push={row.get("push_id"):row for row in pushes if isinstance(row,dict)}
    by_key={(row.get("day"),row.get("aid"),row.get("source_record_key")):row
            for row in evidence if isinstance(row,dict)}
    old=[]
    for line in lines:
        matches=[row for key,row in by_key.items()
                 if key[1]==aid and key[2]==f"{aid}:{line}"]
        if len(matches)!=1:
            raise ContractError("expected one old remote evidence identity")
        ev=matches[0]
        push=by_push.get(ev.get("push_id"))
        if push is None:
            raise ContractError("old remote push identity missing")
        identity={key:push.get(key) for key in IDENTITY_KEYS}
        if (identity["aid"]!=aid or identity["source_line"]!=line or
            identity["source_record_key"]!=f"{aid}:{line}" or
            ev.get("day")!=identity["day"] or ev.get("source_line")!=line):
            raise ContractError("old remote identity scope mismatch")
        if any(key not in push for key in IDENTITY_KEYS):
            raise ContractError("old remote identity incomplete")
        old.append(identity)
    return old


def build_batches(*,source,remote_json,aid,source_lines,proof_secret):
    aid=normalize_public_aid(aid)
    allowed=INCIDENT_SCOPE.get(aid)
    lines=tuple(source_lines)
    if allowed is None or not lines or len(set(lines))!=len(lines) or any(line not in allowed for line in lines):
        raise ContractError("AID/source-line outside exact incident allowlist")
    if tuple(sorted(lines))!=lines:
        raise ContractError("source lines must be unique ascending")
    old=_old_identities(remote_json,aid,lines)
    with open_source(source) as db:
        article=db.execute("SELECT id FROM articles WHERE board='C_Chat' AND REPLACE(aid,'#','')=?",
                           (aid,)).fetchone()
        if article is None:
            raise ContractError("AID not found in canonical Collector")
        plan=inspect_latest_article(db,article_id=article[0])
    if plan.get("status")!="READY" or plan.get("aid")!=aid:
        raise ContractError("canonical Collector article not ready")
    ready={row["source_line"]:row for row in plan.get("candidate_rows",[])}
    floors=plan.get("floor_by_source_line",{}) if plan.get("floor_authoritative") else {}
    pairs=[]
    for expected,line in zip(old,lines):
        raw=ready.get(line)
        if raw is None:
            raise ContractError("allowlisted row is not canonical/ready")
        candidate=dict(raw)
        candidate["floor"]=floors.get(line)
        candidate["origin"]="collector"
        normalized=canonical_record(candidate)
        new={key:normalized.get(key) for key in IDENTITY_KEYS}
        if expected["day"]!=new["day"]:
            raise ContractError("old/new day scope mismatch")
        if expected["push_id"]==new["push_id"]:
            raise ContractError("row is not a canonical remap")
        new["canonical_proof"]=_canonical_proof(new,plan["source_identity"],proof_secret)
        pairs.append({"old":expected,"new":new})
    batches=[]
    for offset in range(0,len(pairs),MAX_BATCH):
        rows=pairs[offset:offset+MAX_BATCH]
        batch={"repair_type":"CANONICAL_SOURCE_LINE_REMAP_V1",
               "source_identity":plan["source_identity"],"day":rows[0]["new"]["day"],
               "aid":aid,"source_lines":[row["new"]["source_line"] for row in rows],
               "rows":rows,"request_cap":1,"write_cap":2*len(rows),"retry_cap":0}
        payload={key:batch[key] for key in ("repair_type","source_identity","day","aid",
            "source_lines","rows","request_cap","write_cap","retry_cap")}
        batch["digest"]=_digest(payload)
        batch["batch_id"]="ptt-remap-v1:"+batch["digest"][:24]
        batches.append(batch)
    return {"status":"LOCAL_CANDIDATE","repair_type":"CANONICAL_SOURCE_LINE_REMAP_V1",
            "aid":aid,"source_identity":plan["source_identity"],"source_lines":list(lines),
            "row_count":len(pairs),"batch_count":len(batches),"batch_cap":MAX_BATCH,
            "retry_cap":0,"live_checkpoint_mutations":0,"batches":batches}


def execute_batch(*,candidate,batch_number,receipt_path,executor):
    batches=candidate.get("batches") if isinstance(candidate,dict) else None
    if (not isinstance(batches,list) or type(batch_number) is not int or
            not 1<=batch_number<=len(batches) or not callable(executor)):
        raise ContractError("invalid canonical remap execution request")
    batch=batches[batch_number-1]
    receipt=Path(receipt_path)
    if receipt.exists():
        prior=json.loads(receipt.read_text(encoding="utf-8"))
        if prior.get("status") in ("ACK","ALREADY_APPLIED"):
            raise ContractError("canonical remap batch already completed")
        raise ContractError("previous remap outcome uncertain; reconcile before replay")
    base={"repair_type":batch["repair_type"],"batch_id":batch["batch_id"],
          "digest":batch["digest"],"aid":batch["aid"],"day":batch["day"],
          "source_lines":batch["source_lines"],"retry_cap":0,
          "http_requests":1,"live_checkpoint_mutations":0}
    atomic_receipt(receipt,{**base,"status":"REMOTE_UNCERTAIN"})
    try:
        ack=executor(batch)
    except Exception:
        raise
    if (not isinstance(ack,dict) or ack.get("batch_id")!=batch["batch_id"] or
            ack.get("digest")!=batch["digest"] or
            ack.get("status") not in ("ACK","ALREADY_APPLIED") or
            ack.get("rows_verified")!=len(batch["rows"]) or
            ack.get("live_checkpoint_mutations")!=0):
        raise RemoteOutcomeUnknown("canonical remap ACK mismatch")
    final={**base,**ack}
    atomic_receipt(receipt,final)
    return final


def main(argv=None):
    parser=argparse.ArgumentParser(description="Build incident-scoped canonical remap candidate")
    parser.add_argument("--source",required=True)
    parser.add_argument("--remote-json",required=True)
    parser.add_argument("--aid",required=True,choices=sorted(INCIDENT_SCOPE))
    parser.add_argument("--source-lines",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    lines=tuple(int(value) for value in args.source_lines.split(",") if value)
    candidate=build_batches(source=args.source,remote_json=args.remote_json,aid=args.aid,
        source_lines=lines,proof_secret=os.environ.get("PTT_CANONICAL_REMAP_PROOF_SECRET",""))
    atomic_receipt(Path(args.output),candidate)
    print(json.dumps({key:candidate[key] for key in ("status","aid","row_count","batch_count",
        "batch_cap","retry_cap","live_checkpoint_mutations")},sort_keys=True))


if __name__=="__main__":
    main()
