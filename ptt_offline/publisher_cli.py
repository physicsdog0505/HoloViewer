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
ARTICLE_COVERAGE_COLUMNS = {"last_page","total_pages","last_source_line"}

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
    """Return canonical Collector line-coverage evidence for exactly one AID.

    Completeness is positive only when article_screens continuously covers
    source lines 1..articles.last_source_line. Push readability is irrelevant.
    """
    screen_columns={r[1] for r in db.execute("PRAGMA table_info(article_screens)")}
    if not SCREEN_COLUMNS <= screen_columns:
        raise ContractError("source coverage schema missing")
    article_columns={r[1] for r in db.execute("PRAGMA table_info(articles)")}
    if not ARTICLE_COVERAGE_COLUMNS <= article_columns:
        raise ContractError("article coverage watermark schema missing")
    article=db.execute(
        """SELECT id,last_page,total_pages,last_source_line
           FROM articles WHERE board='C_Chat' AND aid=?""",(aid,)
    ).fetchone()
    if not article:
        raise ContractError("unverified article/AID")
    article_id,last_page,total_pages,last_source_line=article
    if (last_source_line is None or type(last_source_line) is not int or
            last_source_line < 1):
        return {"article_verified":True,"screen_rows":0,"covered_start":None,
                "covered_end":None,"last_source_line":last_source_line,
                "gaps":[],"malformed_screen_evidence":False,
                "complete":False,"has_gap":"UNKNOWN",
                "reason":"article last_source_line watermark unavailable"}
    rows=db.execute("""
        SELECT source_page,total_pages,start_line,end_line
        FROM article_screens WHERE article_id=?
        ORDER BY start_line,end_line,source_page
    """,(article_id,)).fetchall()
    malformed=False
    intervals=[]
    for page,row_total,start,end in rows:
        if (type(page) is not int or type(row_total) is not int or
            type(start) is not int or type(end) is not int or
            page < 1 or row_total < page or start < 1 or end < start):
            malformed=True
            continue
        intervals.append((start,end))
    if malformed:
        return {"article_verified":True,"screen_rows":len(rows),
                "covered_start":None,"covered_end":None,
                "last_source_line":last_source_line,"gaps":[],
                "malformed_screen_evidence":True,"complete":False,
                "has_gap":True,"reason":"malformed article_screens evidence"}
    if not intervals:
        return {"article_verified":True,"screen_rows":0,"covered_start":None,
                "covered_end":None,"last_source_line":last_source_line,
                "gaps":[[1,last_source_line]],"malformed_screen_evidence":False,
                "complete":False,"has_gap":True,
                "reason":"no article_screens coverage evidence"}

    covered_start=intervals[0][0]
    merged_end=intervals[0][1]
    gaps=[]
    if covered_start > 1:
        gaps.append([1,min(last_source_line,covered_start-1)])
    for start,end in intervals[1:]:
        if start > merged_end + 1 and merged_end < last_source_line:
            gaps.append([merged_end+1,min(last_source_line,start-1)])
        merged_end=max(merged_end,end)
    if merged_end < last_source_line:
        gaps.append([merged_end+1,last_source_line])
    gaps=[g for g in gaps if g[0] <= g[1]]
    terminal_valid=(type(last_page) is int and type(total_pages) is int
                    and total_pages >= 1 and last_page == total_pages
                    and any(page == total_pages and page_total == total_pages
                            and end >= last_source_line
                            for page,page_total,start,end in rows))
    complete=(covered_start == 1 and merged_end >= last_source_line
              and not gaps and terminal_valid)
    return {"article_verified":True,"screen_rows":len(rows),
            "covered_start":covered_start,"covered_end":merged_end,
            "last_source_line":last_source_line,"last_page":last_page,
            "article_total_pages":total_pages,"gaps":gaps,
            "malformed_screen_evidence":False,"complete":complete,
            "terminal_verified":terminal_valid,
            "has_gap":not complete,
            "reason":("continuous article_screens coverage through canonical "
                      "last_source_line and terminal page" if complete else
                      "incomplete source range or unverified terminal page")}

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
