"""Explicit bounded, read-only Collector -> selected day/AID staging.

Source rows are scanned only for one verified article. They are never selected
by schema-preview first-N query. No publication or D1 mutation is performed.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from .collector_source_preview import verify_schema
from .public_today_contract import ContractError, normalize_public_aid
from .publisher_cli import coverage_receipt
from .url_epoch_authority import reconstruct_events

MAX_SOURCE_ROWS = 50000
MAX_STAGE_ROWS = 5


def stage_selected_day(db, *, day: str, aid: str, limit: int=5,
                       after_source_line: int=0,
                       identity_verifier=None) -> dict:
    if type(limit) is not int or not 1 <= limit <= MAX_STAGE_ROWS:
        raise ContractError("first-window staging cap exceeded")
    if type(after_source_line) is not int or after_source_line < 0:
        raise ContractError("invalid ACKed source checkpoint")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError
    except (TypeError,ValueError) as exc:
        raise ContractError("invalid exact selected Taipei day") from exc
    canonical=normalize_public_aid(aid)
    verify_schema(db)
    article=db.execute(
        "SELECT id,board,aid,url FROM articles WHERE board=? AND aid IN (?,?)",
        ("C_Chat",canonical,"#"+canonical),
    ).fetchall()
    if len(article) != 1:
        raise ContractError("exactly one verified C_Chat article required")
    article_id,board,raw_aid,url=article[0]
    if normalize_public_aid(raw_aid) != canonical:
        raise ContractError("selected AID mismatch")
    coverage=coverage_receipt(db,raw_aid)
    # Bound the full chronology before determining the selected Taipei day.
    raw=db.execute(
        """SELECT source_line,source_page,kind,author,content,ptt_date,ptt_time
           FROM pushes WHERE article_id=? ORDER BY source_line LIMIT ?""",
        (article_id,MAX_SOURCE_ROWS+1),
    ).fetchall()
    if len(raw)>MAX_SOURCE_ROWS:
        raise ContractError("source chronology exceeds bounded audit cap")
    keys=("source_line","source_page","kind","author","content","ptt_date","ptt_time")
    chronological=reconstruct_events(
        board=board,aid=raw_aid,url=url,
        identity_verifier=identity_verifier,
        pushes=[dict(zip(keys,r)) for r in raw],
    )
    selected=[{**r,"source_url":url,"origin":"collector"}
              for r in chronological if r["day"] == day
              and r["source_line"] > after_source_line]
    source_identity=sha256(json.dumps([board,canonical,url,article_id],
        separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    # Source-prefix digest only through ACKed line; later appends do not change it.
    # Existing-row edits/reparses do, and must fail before advancing checkpoint.
    def prefix_digest(through):
        return sha256(json.dumps(
            [r for r in raw if r[0] <= through],
            separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "day":day,"aid":canonical,"source_identity":source_identity,
        "acked_prefix_digest":prefix_digest(after_source_line),
        "next_prefix_digest":prefix_digest(
            selected[min(len(selected),limit)-1]["source_line"] if selected else after_source_line),
        "source_rows_examined":len(raw),
        "selected_rows_total":len(selected),
        "rows":selected[:limit],
        "has_more":len(selected)>limit,
        "next_after_source_line":(selected[min(len(selected),limit)-1]["source_line"]
                                   if selected else after_source_line),
        "coverage":coverage,
    }
