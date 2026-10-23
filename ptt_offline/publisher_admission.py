"""Durable rolling admission ledger for #48 Publisher.

Persists the reviewed rolling 6-batch / 60-second budget across process
restart. Single-writer ownership is enforced by recurring_publisher; this
module only maintains the durable budget receipt.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .publisher_cli import atomic_receipt
from .public_today_contract import ContractError

WINDOW_SECONDS=60
BATCH_CAP=6
MAX_LEDGER_ENTRIES=64

def _load(path):
    p=Path(path)
    if not p.exists():
        return {"version":1,"entries":[]}
    try:
        value=json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError("publisher admission ledger unreadable") from exc
    if value.get("version")!=1 or not isinstance(value.get("entries"),list):
        raise ContractError("publisher admission ledger invalid")
    return value

def _pruned(entries,now):
    cutoff=now-WINDOW_SECONDS
    clean=[]
    for item in entries:
        if not isinstance(item,dict):
            raise ContractError("publisher admission entry invalid")
        at=item.get("at")
        batches=item.get("batches")
        if not isinstance(at,(int,float)) or not isinstance(batches,int) or batches<0:
            raise ContractError("publisher admission entry invalid")
        if at>now+5:
            raise ContractError("publisher admission ledger from future")
        if at>cutoff:
            clean.append(item)
    return clean[-MAX_LEDGER_ENTRIES:]

def snapshot(path,*,now=None):
    current=float(time.time() if now is None else now)
    value=_load(path)
    entries=_pruned(value["entries"],current)
    return {
        "entries":entries,
        "batches":sum(int(x.get("batches",0)) for x in entries),
        "rows":sum(int(x.get("rows",0)) for x in entries),
        "modeled_queries":sum(int(x.get("modeled_queries",0)) for x in entries),
        "modeled_writes":sum(int(x.get("modeled_writes",0)) for x in entries),
    }

def allows_batch(path,*,now=None):
    return snapshot(path,now=now)["batches"]<BATCH_CAP

def record(path,*,batches,rows,modeled_queries,modeled_writes,now=None):
    if type(batches) is not int or not 0<=batches<=BATCH_CAP:
        raise ContractError("invalid durable admission batch count")
    for value in (rows,modeled_queries,modeled_writes):
        if type(value) is not int or value<0:
            raise ContractError("invalid durable admission accounting")
    current=float(time.time() if now is None else now)
    value=_load(path)
    entries=_pruned(value["entries"],current)
    if batches:
        entries.append({
            "at":current,
            "batches":batches,
            "rows":rows,
            "modeled_queries":modeled_queries,
            "modeled_writes":modeled_writes,
        })
    totals={
        "batches":sum(int(x.get("batches",0)) for x in entries),
        "rows":sum(int(x.get("rows",0)) for x in entries),
        "modeled_queries":sum(int(x.get("modeled_queries",0)) for x in entries),
        "modeled_writes":sum(int(x.get("modeled_writes",0)) for x in entries),
    }
    if totals["batches"]>BATCH_CAP:
        raise ContractError("durable rolling batch cap exceeded")
    atomic_receipt(Path(path),{"version":1,"entries":entries})
    return totals
