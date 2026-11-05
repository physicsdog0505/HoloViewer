"""Read-only source-wide PTT year classification with row-level pending isolation.

Unlike strict event reconstruction this path keeps the raw source rows and
classifies each independently. It intentionally produces *no publishable rows*
without accepted positive authority; inferred candidates are for review only.
"""
from .collector_source_preview import verify_schema
from .public_today_contract import ContractError,normalize_public_aid,taipei_day
from .source_time_partition import partition_candidate_rows
from .publisher_cli import coverage_receipt

MAX_AUDIT_ROWS=50000

def audit_source_day(db,*,day,aid,timezone_evidence=False):
    from datetime import date
    try:
        if date.fromisoformat(day).isoformat()!=day:
            raise ValueError
    except (TypeError,ValueError) as exc:
        raise ContractError("invalid canonical selected day") from exc
    aid=normalize_public_aid(aid)
    verify_schema(db)
    article=db.execute("SELECT id,board,aid,url FROM articles WHERE board='C_Chat' AND aid IN (?,?)",
                       (aid,"#"+aid)).fetchall()
    if len(article)!=1:
        raise ContractError("exact C_Chat article identity required")
    id_,board,stored_aid,url=article[0]
    rows=db.execute("""SELECT source_line,ptt_date,ptt_time,collected_at
        FROM pushes WHERE article_id=? ORDER BY source_line LIMIT ?""",
        (id_,MAX_AUDIT_ROWS+1)).fetchall()
    if len(rows)>MAX_AUDIT_ROWS:
        raise ContractError("bounded source audit limit")
    source=[dict(zip(("source_line","ptt_date","ptt_time","collected_at"),r)) for r in rows]
    classified=partition_candidate_rows(board=board,aid=stored_aid,url=url,
                             rows=source,timezone_evidence=timezone_evidence)
    inferred_day=[r for r in classified["inferred"]
                  if taipei_day(r["occurred_at"])==day]
    # Positive event authority is not present: absolutely no live write.
    return {"day":day,"aid":aid,"source_rows_examined":len(source),
       "identity":classified["identity"],"inferred_day":inferred_day,
       "pending":classified["pending"],"checkpoint_blocked_at":
        classified["checkpoint_blocked_at"],
       "publishable_rows":[],"coverage":coverage_receipt(db,stored_aid)}
