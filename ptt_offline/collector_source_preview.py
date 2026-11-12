"""#48 read-only canonical Collector SQLite mapping and bounded offline preview.

This is an execution-safe preparation CLI, not the live D1 publisher.
Requires explicit --source and --day; it never infers an owner DB path.
For events without an authoritative year+timezone it fails closed instead
of manufacturing canonical timestamps.
"""
import argparse
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from .public_today_contract import taipei_day, ContractError

EXPECTED = {
    "articles": {"id", "board", "aid", "url", "title_hint", "created_at", "last_seen_at"},
    "pushes": {"id", "article_id", "source_line", "source_page", "kind", "author",
               "content", "ptt_date", "ptt_time", "collected_at"},
}
MAX_PREVIEW = 5


def open_source(path):
    candidate = Path(path).expanduser().resolve(strict=True)
    if not candidate.is_file():
        raise ContractError("explicit source must be a file")
    return sqlite3.connect(candidate.as_uri() + "?mode=ro", uri=True)


def verify_schema(db):
    checks = {}
    for table, required in EXPECTED.items():
        got = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        checks[table] = {"columns": sorted(got), "missing": sorted(required - got)}
    if any(v["missing"] for v in checks.values()):
        raise ContractError("canonical Collector schema mismatch")
    return checks


def preview(db, *, day, limit=MAX_PREVIEW):
    if type(limit) is not int or not 1 <= limit <= MAX_PREVIEW:
        raise ContractError("preview bound")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ContractError("invalid Taipei day")
    # Read at most 5 joined records. The original ptt_date/time fields
    # often omit a trustworthy year/timezone; publication needs source proof.
    records = db.execute("""
      SELECT a.board,a.aid,a.url,p.source_line,p.kind,p.author,
             p.content,p.ptt_date,p.ptt_time,p.collected_at
      FROM pushes p JOIN articles a ON a.id=p.article_id
      WHERE a.board='C_Chat'
      ORDER BY p.id LIMIT ?
    """, (limit,)).fetchall()
    return {
        "mode": "SCHEMA_ONLY_DRY_RUN",
        "requested_day": day,
        "source_rows_examined": len(records),
        "publishable_rows": 0,
        "time_identity": "UNVERIFIED",
        "publication_blocker": "ptt_date/ptt_time require proven year/timezone + selected-day matching",
        "source_fields": ["board","aid","url","source_line","kind","author",
                          "content","ptt_date","ptt_time","collected_at"],
        "content_redacted": True,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="Explicit Collector SQLite path; read-only")
    p.add_argument("--day", required=True, help="Taipei YYYY-MM-DD scope")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--dry-run", action="store_true", required=True)
    args=p.parse_args(argv)
    with open_source(args.source) as db:
        schema=verify_schema(db)
        info=preview(db,day=args.day,limit=args.limit)
    print(json.dumps({"schema":schema,"receipt":info},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
