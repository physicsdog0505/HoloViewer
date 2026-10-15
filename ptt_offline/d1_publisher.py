"""#48 canonical SQLite -> replay-safe D1 Publisher boundary.

SQL is compatible with D1. Offline sqlite3 is used ONLY for contract tests:
never opens owner SQLite, invokes Worker, or creates production resources.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from .public_today_contract import canonical_id, normalize_public_aid, taipei_day, public_push, ContractError
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
import re

PTT_URL = re.compile(r"^https://www\.ptt\.cc/bbs/C_Chat/M\.[0-9]+\.A\.[A-Za-z0-9]+\.html$")


def accepted_url(value: Any) -> str | None:
    return value if isinstance(value, str) and PTT_URL.fullmatch(value) else None


def canonical_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Preserve source identity; no guess of missing floor/kind."""
    row = dict(raw)
    row["aid"] = normalize_public_aid(row["aid"])
    row["day"] = taipei_day(row["occurred_at"])
    row["push_id"] = canonical_id(row)
    if row.get("kind") not in (None, "推", "噓", "→"):
        raise ContractError("invalid kind")
    if row.get("floor") is not None and (type(row["floor"]) is not int or row["floor"] <= 0):
        raise ContractError("invalid floor")
    row["source_url"] = accepted_url(row.get("source_url"))
    row["source_priority"] = 10 if row.get("origin") == "collector" else 0
    return row


UPSERT_PUSH = """
INSERT INTO ptt_pushes
(push_id,aid,day,source_line,kind,author,content,occurred_at,floor,
 source_url,source_priority,source_record_key)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(push_id) DO UPDATE SET
  floor=CASE WHEN excluded.source_priority >= ptt_pushes.source_priority
             THEN excluded.floor ELSE ptt_pushes.floor END,
  kind=CASE WHEN excluded.source_priority >= ptt_pushes.source_priority
            THEN COALESCE(excluded.kind,ptt_pushes.kind) ELSE ptt_pushes.kind END,
  source_url=COALESCE(ptt_pushes.source_url,excluded.source_url),
  source_priority=MAX(ptt_pushes.source_priority,excluded.source_priority),
  source_record_key=COALESCE(ptt_pushes.source_record_key,excluded.source_record_key)
"""


def record_params(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in (
        "push_id", "aid", "day", "source_line", "kind", "author",
        "content", "occurred_at", "floor", "source_url",
        "source_priority", "source_record_key",
    ))


def publish_batch(db: Any, day: str, aids: Iterable[str],
                  rows: Iterable[dict[str, Any]]) -> int:
    """Use a single D1 batch transaction or SQLite transaction supplied by caller.

    This function targets Python DB-API compatible offline executors. A real
    Worker uses the same SQL through D1.prepare/batch, separately gated.
    """
    canonical_aids = {normalize_public_aid(a) for a in aids}
    if not canonical_aids:
        raise ContractError("verified AID scope required")
    staged = [canonical_record(x) for x in rows]
    if any(x["day"] != day or x["aid"] not in canonical_aids for x in staged):
        raise ContractError("batch cross-day/AID")
    # Validate every row before issuing first statement.
    with db:
        for aid in sorted(canonical_aids):
            db.execute("INSERT OR IGNORE INTO ptt_threads(day,aid) VALUES (?,?)", (day, aid))
        for row in staged:
            db.execute(UPSERT_PUSH, record_params(row))
            if row.get("source_record_key"):
                db.execute("""INSERT INTO ptt_source_evidence
                   (day,aid,source_record_key,push_id,source_line)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(day,aid,source_record_key) DO UPDATE SET
                   push_id=excluded.push_id,source_line=excluded.source_line""",
                   (day,row["aid"],row["source_record_key"],row["push_id"],row["source_line"]))
    return len(staged)


def read_day(db: Any, day: str) -> tuple[set[str], list[dict[str, Any]]]:
    aids = {r[0] for r in db.execute(
        "SELECT aid FROM ptt_threads WHERE day=? ORDER BY aid", (day,))}
    records = db.execute("""SELECT push_id,aid,source_line,kind,author,
       content,occurred_at,floor,source_url
       FROM ptt_pushes WHERE day=? ORDER BY occurred_at,aid,source_line,push_id""",
       (day,)).fetchall()
    fields=("push_id","aid","source_line","kind","author","content","occurred_at","floor","source_url")
    return aids,[dict(zip(fields,row)) for row in records]
