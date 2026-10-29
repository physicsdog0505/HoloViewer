"""Strict source-only authority for bounded historical baseline repair.

Unlike the near-live Publisher, this path deliberately ignores Collector
arrival time.  It is usable only when the complete article line range is
present and the canonical article URL can anchor every PTT MM/DD HH:MM value
in strict source-line chronology.
"""
from hashlib import sha256
import json

from .collector_source_preview import verify_schema
from .d1_publisher import canonical_record
from .ptt_aid_identity import identity_receipt, verify_aid_url
from .public_today_contract import ContractError
from .url_epoch_authority import reconstruct_events


def inspect_historical_article(db, *, article_id, max_rows=50000):
    if type(max_rows) is not int or not 1 <= max_rows <= 50000:
        raise ContractError("bounded historical source scan required")
    verify_schema(db)
    article=db.execute(
        "SELECT id,board,aid,url FROM articles WHERE id=? AND board='C_Chat'",
        (article_id,),
    ).fetchone()
    if article is None:
        raise ContractError("historical article not found")
    article_id,board,raw_aid,url=article
    receipt=identity_receipt(board,raw_aid,url)

    keys=("source_line","source_page","kind","author","content",
          "ptt_date","ptt_time","collected_at")
    raw=db.execute("""
        SELECT source_line,source_page,kind,author,content,ptt_date,ptt_time,collected_at
        FROM pushes WHERE article_id=? ORDER BY source_line LIMIT ?
    """,(article_id,max_rows+1)).fetchall()
    if not raw:
        raise ContractError("historical article has no source rows")
    if len(raw)>max_rows:
        raise ContractError("historical source scan truncated")
    pushes=[dict(zip(keys,row)) for row in raw]
    lines=[row["source_line"] for row in pushes]
    if (any(type(line) is not int or line<=0 for line in lines) or
        lines!=sorted(lines) or len(lines)!=len(set(lines))):
        raise ContractError("historical source lines are not strict and unique")

    has_screens=db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_screens'"
    ).fetchone() is not None
    if not has_screens:
        raise ContractError("historical article coverage evidence required")
    ranges=db.execute("""
        SELECT start_line,end_line FROM article_screens
        WHERE article_id=? ORDER BY start_line,end_line
    """,(article_id,)).fetchall()
    if not ranges or any(type(start) is not int or type(end) is not int or
                         start<=0 or end<start for start,end in ranges):
        raise ContractError("valid historical article coverage required")
    if ranges[0][0]!=1:
        raise ContractError("historical coverage must start at article line 1")
    merged_end=ranges[0][1]
    for start,end in ranges[1:]:
        if start>merged_end+1:
            raise ContractError("historical article coverage has a gap")
        merged_end=max(merged_end,end)
    if merged_end<lines[-1]:
        raise ContractError("historical coverage does not reach latest source row")

    rebuilt=reconstruct_events(
        board=board,aid=receipt["aid"],url=url,pushes=pushes,
        identity_verifier=verify_aid_url,
    )
    rows=[]
    for row in rebuilt:
        rows.append(canonical_record({
            **row,"source_url":url,"origin":"collector","floor":None,
        }))
    source_identity=sha256(json.dumps(
        [receipt["aid"],url],sort_keys=True,separators=(",",":"),
        ensure_ascii=False,
    ).encode()).hexdigest()
    return {
        "status":"HISTORICAL_URL_EPOCH_READY",
        "authority":"verified_url_epoch_full_article_v1",
        "aid":receipt["aid"],
        "url":url,
        "source_identity":source_identity,
        "coverage_start":1,
        "coverage_end":merged_end,
        "checked_source_rows":len(rows),
        "candidate_rows":rows,
    }
