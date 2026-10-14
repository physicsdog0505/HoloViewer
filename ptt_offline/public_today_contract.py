"""Offline-only PTT Public Today contract adapter. No network, SQLite or process access.

All payloads in this module are synthetic/test inputs until an accepted data-service
producer supplies verified source and coverage evidence. Fields are PROPOSED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from json import dumps
from typing import Any
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
MAX_PAGE = 200
MAX_BYTES = 512 * 1024


class ContractError(ValueError):
    """Fail-closed contract violation."""


def taipei_day(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ContractError("timestamp requires timezone")
    return dt.astimezone(TAIPEI).date().isoformat()


def canonical_id(push: dict[str, Any]) -> str:
    """Reuse the reviewed AID/source-line/author/UTC-time/content key concept.

    Canonical digest encoding MUST be cross-checked against private #311 before
    production use. This proposed adapter never claims byte parity by itself.
    """
    aid = push.get("aid")
    line = push.get("source_line")
    author = push.get("author")
    content = push.get("content")
    when = push.get("occurred_at")
    if not aid or type(line) is not int or line < 1 or not isinstance(author, str) or not isinstance(content, str) or not when:
        raise ContractError("missing canonical push identity")
    dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ContractError("naive timestamp")
    utc = dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    wire = dumps([aid, line, author, utc, content], ensure_ascii=False, separators=(",", ":"))
    return sha256(wire.encode("utf-8")).hexdigest()


def history_completeness(manifest: dict[str, Any] | None, claimed_complete: bool = False) -> str:
    """Never trust caller claims/checksum alone; only external accepted evidence.

    Synthetic accepted manifests must explicitly bind day and all relevant AIDs.
    Real issuer/signature verification is a future authorized integration gate.
    """
    if not isinstance(manifest, dict):
        return "partial"
    if (manifest.get("authority") != "synthetic-accepted-fixture"
            or manifest.get("status") != "final-complete"
            or not isinstance(manifest.get("day"), str)
            or not isinstance(manifest.get("aids"), list)
            or not manifest["aids"]
            or len(manifest["aids"]) != len(set(manifest["aids"]))):
        return "partial"
    return "complete" if claimed_complete else "partial"


@dataclass
class TodayAdapter:
    day: str
    aids: set[str]
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    cursors: dict[str, int] = field(default_factory=dict)
    purged: dict[str, int] = field(default_factory=dict)
    last_checked: str | None = None
    freshness: str = "unknown"
    completeness: str = "partial"
    history_gap: bool = False
    source: str = "synthetic-only"

    def __post_init__(self) -> None:
        datetime.fromisoformat(self.day)
        if not self.aids or not all(isinstance(a, str) and a for a in self.aids):
            raise ContractError("explicit verified AIDs required")

    def merge_snapshot(self, pushes: list[dict[str, Any]], *, collector_first: bool = True) -> None:
        for raw in pushes:
            row = dict(raw)
            aid = row.get("aid")
            if aid not in self.aids:
                raise ContractError("cross-thread AID")
            if taipei_day(row["occurred_at"]) != self.day:
                raise ContractError("cross-day push")
            if row.get("floor") is not None and (type(row["floor"]) is not int or row["floor"] < 1):
                raise ContractError("invalid display floor")
            identity = canonical_id(row)
            if row.get("push_id") not in (None, identity):
                raise ContractError("canonical push_id mismatch")
            row["push_id"] = identity
            row.setdefault("origin", "web")
            prior = self.rows.get(identity)
            if prior is None or (collector_first and row["origin"] == "collector" and prior.get("origin") != "collector"):
                self.rows[identity] = row

    def read_initial(self, limit: int = 300) -> list[dict[str, Any]]:
        if limit != 300:
            raise ContractError("accepted initial window is 300")
        return self._ordered()[-300:]

    def _ordered(self) -> list[dict[str, Any]]:
        return sorted(self.rows.values(), key=lambda r: (r["occurred_at"], r["aid"], r["source_line"], r["push_id"]))

    def read_after_key(self, key: str, limit: int = MAX_PAGE) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_PAGE:
            raise ContractError("page bound")
        ordered = self._ordered()
        positions = [i for i, row in enumerate(ordered) if row["push_id"] == key]
        if not positions:
            self.history_gap = True
            self.completeness = "partial"
            return []
        return ordered[positions[0] + 1:positions[0] + 1 + limit]

    def ingest_relay_page(self, *, aid: str, after_cursor: int, pushes: list[dict[str, Any]],
                          next_cursor: int, has_more: bool, checked_at: str,
                          purged_through_cursor: int = 0, max_bytes: int = MAX_BYTES) -> None:
        if aid not in self.aids or type(after_cursor) is not int or after_cursor < 0:
            raise ContractError("invalid AID/cursor")
        if type(next_cursor) is not int or next_cursor < after_cursor:
            raise ContractError("regressive cursor")
        if not 1 <= max_bytes <= MAX_BYTES or len(dumps(pushes, ensure_ascii=False).encode("utf-8")) > max_bytes:
            raise ContractError("oversize response")
        if len(pushes) > MAX_PAGE:
            raise ContractError("too many pushes")
        if after_cursor < self.purged.get(aid, 0) or after_cursor < purged_through_cursor:
            self.history_gap = True
            self.completeness = "partial"
            raise ContractError("retention gap / purged floor")
        if after_cursor != self.cursors.get(aid, 0):
            raise ContractError("expired or wrong replay cursor")
        last = after_cursor
        for row in pushes:
            if row.get("aid") != aid or type(row.get("cursor")) is not int or row["cursor"] <= last:
                raise ContractError("out-of-order/cross-AID relay")
            last = row["cursor"]
        if pushes and next_cursor != last:
            raise ContractError("next cursor does not match page")
        if not pushes and next_cursor != after_cursor:
            raise ContractError("empty page cursor mismatch")
        # Parse checked_at before committing; failures must retain last good rows.
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        if checked.tzinfo is None:
            raise ContractError("naive checked_at")
        self.merge_snapshot(pushes)
        self.cursors[aid] = next_cursor
        self.purged[aid] = max(self.purged.get(aid, 0), purged_through_cursor)
        self.last_checked = checked_at
        self.freshness = "fresh"
        # has_more=True requires caller continuation; a latest cursor is not completeness.
        if has_more:
            self.completeness = "partial"

    def mark_fetch_failure(self) -> None:
        self.freshness = "stale"  # preserve self.rows, cursor, last success

    def freshness_at(self, now_iso: str, stale_after_seconds: int = 30) -> str:
        if not self.last_checked:
            return "unknown"
        a = datetime.fromisoformat(self.last_checked.replace("Z", "+00:00"))
        b = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        if a.tzinfo is None or b.tzinfo is None:
            raise ContractError("naive freshness timestamp")
        if (b - a).total_seconds() > stale_after_seconds:
            self.freshness = "stale"
        return self.freshness

    def roll_to(self, now_iso: str, aids: set[str]) -> "TodayAdapter":
        next_day = taipei_day(now_iso)
        return self if next_day == self.day else TodayAdapter(day=next_day, aids=aids)
