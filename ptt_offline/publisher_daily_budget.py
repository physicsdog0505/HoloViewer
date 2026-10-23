"""Durable daily soft budget for the #48 Publisher.

This is a Publisher-attributable safety guard, not Cloudflare account billing
telemetry. It persists conservative modeled D1 write/query ceilings across
process restart and rolls over by Asia/Taipei calendar day.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .publisher_cli import atomic_receipt
from .public_today_contract import ContractError

TAIPEI=ZoneInfo("Asia/Taipei")
DEFAULT_MODELED_WRITE_CAP=25_000
DEFAULT_MODELED_QUERY_CAP=60_000

def _day(now):
    stamp=float(time.time() if now is None else now)
    return datetime.fromtimestamp(stamp,timezone.utc).astimezone(TAIPEI).date().isoformat()

def _load(path):
    p=Path(path)
    if not p.exists():
        return {"version":1,"days":{}}
    try:
        value=json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError("publisher daily budget unreadable") from exc
    if value.get("version")!=1 or not isinstance(value.get("days"),dict):
        raise ContractError("publisher daily budget invalid")
    return value

def _caps(write_cap,query_cap):
    write_cap=DEFAULT_MODELED_WRITE_CAP if write_cap is None else write_cap
    query_cap=DEFAULT_MODELED_QUERY_CAP if query_cap is None else query_cap
    if type(write_cap) is not int or write_cap<1:
        raise ContractError("invalid daily modeled write cap")
    if type(query_cap) is not int or query_cap<1:
        raise ContractError("invalid daily modeled query cap")
    return write_cap,query_cap

def snapshot(path,*,now=None,write_cap=None,query_cap=None):
    write_cap,query_cap=_caps(write_cap,query_cap)
    value=_load(path)
    day=_day(now)
    current=value["days"].get(day,{})
    writes=current.get("modeled_writes",0)
    queries=current.get("modeled_queries",0)
    batches=current.get("batches",0)
    rows=current.get("rows",0)
    for item in (writes,queries,batches,rows):
        if type(item) is not int or item<0:
            raise ContractError("publisher daily budget entry invalid")
    return {
        "day":day,
        "modeled_writes":writes,
        "modeled_queries":queries,
        "batches":batches,
        "rows":rows,
        "modeled_write_cap":write_cap,
        "modeled_query_cap":query_cap,
        "write_remaining":max(0,write_cap-writes),
        "query_remaining":max(0,query_cap-queries),
        "write_over_cap":max(0,writes-write_cap),
        "query_over_cap":max(0,queries-query_cap),
        "blocked":bool(writes>=write_cap or queries>=query_cap),
    }

def allows(path,*,projected_writes,projected_queries,now=None,write_cap=None,query_cap=None):
    if type(projected_writes) is not int or projected_writes<0:
        raise ContractError("invalid projected daily writes")
    if type(projected_queries) is not int or projected_queries<0:
        raise ContractError("invalid projected daily queries")
    current=snapshot(path,now=now,write_cap=write_cap,query_cap=query_cap)
    allowed=(current["modeled_writes"]+projected_writes<=current["modeled_write_cap"] and
             current["modeled_queries"]+projected_queries<=current["modeled_query_cap"])
    reason=None
    if not allowed:
        if current["modeled_writes"]+projected_writes>current["modeled_write_cap"]:
            reason="DAILY_MODELED_WRITE_CAP"
        else:
            reason="DAILY_MODELED_QUERY_CAP"
    return allowed,reason,current

def record(path,*,batches,rows,modeled_writes,modeled_queries,now=None,
           write_cap=None,query_cap=None):
    for name,value in (
        ("batches",batches),("rows",rows),("modeled_writes",modeled_writes),
        ("modeled_queries",modeled_queries),
    ):
        if type(value) is not int or value<0:
            raise ContractError("invalid daily budget "+name)
    current_day=_day(now)
    write_cap,query_cap=_caps(write_cap,query_cap)
    value=_load(path)
    days=value["days"]
    existing=days.get(current_day,{})
    updated={
        "batches":int(existing.get("batches",0))+batches,
        "rows":int(existing.get("rows",0))+rows,
        "modeled_writes":int(existing.get("modeled_writes",0))+modeled_writes,
        "modeled_queries":int(existing.get("modeled_queries",0))+modeled_queries,
    }
    # Accounting may discover a remote commit only after an ambiguous outcome.
    # Never reject truthful durable accounting because the soft cap was crossed
    # by a write that already happened. The next admission snapshot will expose
    # zero remaining budget and block any new Publisher-attributable write.
    days={k:v for k,v in days.items() if k>=current_day}
    days[current_day]=updated
    atomic_receipt(Path(path),{"version":1,"days":days})
    return snapshot(path,now=now,write_cap=write_cap,query_cap=query_cap)
