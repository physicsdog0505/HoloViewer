"""Provider adapter for the single canonical D1 store (offline DB-API emulation).

The adapter consumes already-projected D1 rows; it never scrapes PTT or reads
the owner's private SQLite. A live Worker/D1 binding is a later runtime gate.
"""
from __future__ import annotations

from typing import Any
from .d1_publisher import read_day
from .public_today_contract import (
    InitialWindow, PttProvider, RelayPage, ContractError,
)


class D1PttProvider(PttProvider):
    def __init__(self, db: Any, *, day: str, checked_at: str = "2026-10-15T00:00:00Z"):
        self.db = db
        self.day = day
        self.checked_at = checked_at

    def aids_for_day(self, day: str) -> set[str]:
        if day != self.day:
            raise ContractError("provider day binding mismatch")
        return read_day(self.db, day)[0]

    def snapshot_for_day(self, day: str) -> list[dict[str, Any]]:
        if day != self.day:
            raise ContractError("provider day binding mismatch")
        return read_day(self.db, day)[1]

    def initial_window(self, aid: str, *, limit: int) -> InitialWindow:
        """D1 read-model snapshot is already a coverage-safe ordered projection.

        A provider that implements *real relay* must replace this with an
        independently reviewed proof of tail completeness and watermark state.
        """
        if type(limit) is not int or limit < 1:
            raise ContractError("initial window bound")
        rows = self.db.execute(
            """SELECT p.push_id,p.aid,p.source_line,p.kind,p.author,p.content,
                      p.occurred_at,p.floor,p.source_url
               FROM ptt_pushes p WHERE p.day=? AND p.aid=?
               ORDER BY p.occurred_at,p.source_line,p.push_id DESC LIMIT ?""",
            (self.day, aid, limit),
        ).fetchall()
        names = ("push_id", "aid", "source_line", "kind", "author",
                 "content", "occurred_at", "floor", "source_url")
        selected = [dict(zip(names, r)) for r in reversed(rows)]
        for index, row in enumerate(selected, start=1):
            row["cursor"] = index
        return InitialWindow(
            aid=aid, pushes=selected, checkpoint_cursor=len(selected),
            checked_at=self.checked_at, safe=True,
        )

    def relay_after(self, aid: str, *, after_cursor: int, limit: int) -> RelayPage:
        """No fabricated relay cursor: real provider must define resume semantics."""
        raise ContractError("D1 relay cursor requires verified provider state")
