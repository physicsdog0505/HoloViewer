"""Resumable, transport-neutral Publisher contract for #48.

Pure/offline state machine only. It creates bounded batch envelopes and advances
checkpoints only after an exact ACK. No network, D1 binding, retry loop or live
source access exists here.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from .public_today_contract import ContractError, normalize_public_aid

MAX_ROWS_PER_BATCH = 5
MAX_REQUESTS_PER_BATCH = 1
MAX_WRITES_PER_BATCH = 5


def _stable_json(value) -> bytes:
    return json.dumps(value,separators=(",",":"),sort_keys=True,
                      ensure_ascii=False).encode("utf-8")


def new_checkpoint(*, source_identity: str, day: str, aids) -> dict:
    if not isinstance(source_identity,str) or not source_identity:
        raise ContractError("explicit source identity required")
    canonical=sorted({normalize_public_aid(a) for a in aids})
    if not canonical:
        raise ContractError("verified AID scope required")
    return {"version":1,"source_identity":source_identity,"day":day,
            "aids":{aid:0 for aid in canonical},"last_batch_id":None}


def make_batch(*, checkpoint: dict, rows: list[dict], batch_cap: int=5) -> dict:
    if type(batch_cap) is not int or batch_cap < 1 or batch_cap > MAX_ROWS_PER_BATCH:
        raise ContractError("batch cap exceeded")
    if not isinstance(rows,list):
        raise ContractError("rows must be explicit list")
    selected=set(checkpoint.get("aids",{}))
    day=checkpoint.get("day")
    staged=[]
    for row in rows:
        aid=normalize_public_aid(row.get("aid"))
        line=row.get("source_line")
        if aid not in selected:
            raise ContractError("row outside selected AID scope")
        if row.get("day") != day:
            raise ContractError("row outside selected Taipei day")
        if type(line) is not int or line < 1:
            raise ContractError("invalid source line")
        if line <= checkpoint["aids"][aid]:
            continue
        staged.append(dict(row))
    staged.sort(key=lambda x:(x["aid"],x["source_line"],x.get("push_id","")))
    staged=staged[:batch_cap]
    payload={"source_identity":checkpoint["source_identity"],"day":day,
             "rows":staged,"request_cap":MAX_REQUESTS_PER_BATCH,
             "write_cap":min(MAX_WRITES_PER_BATCH,batch_cap),"retry_cap":0}
    digest=sha256(_stable_json(payload)).hexdigest()
    return {"batch_id":"ptt48:"+digest[:24],"digest":digest,**payload}


def apply_ack(*, checkpoint: dict, batch: dict, ack: dict) -> dict:
    """Advance only for an exact, all-row ACK; otherwise fail without mutation."""
    expected={
        "batch_id":batch.get("batch_id"),
        "digest":batch.get("digest"),
        "rows_acked":len(batch.get("rows",[])),
        "status":"ACK",
    }
    if any(ack.get(k) != v for k,v in expected.items()):
        raise ContractError("write ACK mismatch; checkpoint not advanced")
    updated=deepcopy(checkpoint)
    for row in batch["rows"]:
        aid=row["aid"]
        updated["aids"][aid]=max(updated["aids"][aid],row["source_line"])
    updated["last_batch_id"]=batch["batch_id"]
    return updated
