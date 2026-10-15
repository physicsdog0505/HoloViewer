"""#48 bounded publisher preparation CLI. NO LIVE PUBLISH PATH.

Requires explicit SQLite path, selected Taipei day, verified AID and dry-run.
This CLI only checks canonical source schema/evidence and writes a redacted
local receipt; it never sends D1 requests or changes source data.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .collector_source_preview import open_source, verify_schema
from .public_today_contract import ContractError

MAX_BATCH = 5
SCREEN_COLUMNS = {"article_id","source_page","total_pages",
                  "start_line","end_line","captured_at"}

@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("publisher already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def coverage_receipt(db, aid: str):
    columns={r[1] for r in db.execute("PRAGMA table_info(article_screens)")}
    if not SCREEN_COLUMNS <= columns:
        raise ContractError("source coverage schema missing")
    article=db.execute(
        "SELECT id FROM articles WHERE board='C_Chat' AND aid=?",(aid,)
    ).fetchone()
    if not article:
        raise ContractError("unverified article/AID")
    article_id=article[0]
    rows=db.execute("""
        SELECT source_page,total_pages,start_line,end_line FROM article_screens
        WHERE article_id=? ORDER BY start_line,end_line LIMIT 10
    """,(article_id,)).fetchall()
    # A screen set isn't necessarily proof of complete history.
    malformed=any(p<1 or total<p or start<1 or end<start
                  for p,total,start,end in rows)
    return {"article_verified":True,"screen_samples":len(rows),
            "malformed_screen_evidence":malformed,
            "complete":False,"has_gap":"UNKNOWN",
            "reason":"screens alone do not certify continuous 1..last-source-line coverage"}

def atomic_receipt(destination: Path, body: dict):
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,tmp=tempfile.mkstemp(prefix=".ptt48-",suffix=".tmp",dir=destination.parent)
    try:
        with os.fdopen(descriptor,"w",encoding="utf-8") as handle:
            json.dump(body,handle,ensure_ascii=False,indent=2,sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def prepare(*,source: str,day: str,aid: str,receipt_path: str,batch: int=5,
            dry_run: bool=True) -> dict:
    if not dry_run:
        raise ContractError("live Publisher is not authorized/implemented")
    try:
        if datetime.strptime(day,"%Y-%m-%d").strftime("%Y-%m-%d")!=day:
            raise ValueError
    except ValueError as exc:
        raise ContractError("invalid Taipei day") from exc
    if not re.fullmatch(r"[A-Za-z0-9_#-]{1,80}",aid):
        raise ContractError("invalid AID selector")
    if type(batch) is not int or batch<1 or batch>MAX_BATCH:
        raise ContractError("batch size exceeds first-window cap")
    receipt=Path(receipt_path).expanduser().resolve()
    with exclusive_lock(receipt.with_suffix(receipt.suffix+".lock")):
        with open_source(source) as db:
            verify_schema(db)
            scope=coverage_receipt(db,aid)
        result={"status":"BLOCKED_UNVERIFIED_TIMESTAMP","mode":"DRY_RUN",
                "day":day,"aid":aid,"batch_cap":batch,
                "publishable_rows":0,"d1_queries":0,"d1_rows_written":0,
                "retries":0,"coverage":scope,
                "timestamp_authority":"UNVERIFIED",
                "source_row_content":"REDACTED",
                "recorded_at":datetime.now(timezone.utc).isoformat()}
        atomic_receipt(receipt,result)
        return result

def main(argv=None):
    p=argparse.ArgumentParser(description="Offline-only bounded PTT Publisher preparation")
    p.add_argument("--source",required=True)
    p.add_argument("--day",required=True)
    p.add_argument("--aid",required=True)
    p.add_argument("--receipt",required=True)
    p.add_argument("--batch",type=int,default=5)
    p.add_argument("--dry-run",action="store_true",required=True)
    a=p.parse_args(argv)
    print(json.dumps(prepare(source=a.source,day=a.day,aid=a.aid,
                  receipt_path=a.receipt,batch=a.batch,dry_run=a.dry_run),
                  ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
