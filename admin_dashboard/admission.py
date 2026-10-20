"""Multi-process-safe admission and sanitized audit state for read-only Admin readers.

This local SQLite database stores only quota/admission/audit metadata. It is not a
Production data client and exposes no business-data write capability.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

DEFAULT_REQUEST_CLASSES = {
    "d1": {"d1_snapshot"},
    "archive": {"archive_delivery"},
    "api_semantic": {"api_semantic_health"},
    "publisher": {"publisher_evidence"},
    "collector": {"collector_evidence"},
}

DEFAULT_SOURCE_LIMITS = {
    "d1": (6, 600),
    "archive": (6, 600),
    "api_semantic": (12, 600),
    "publisher": (12, 600),
    "collector": (12, 600),
}


@dataclass(frozen=True)
class AdmissionRequest:
    source: str
    scope: dict
    verification_mode: str
    request_class: str
    cost_class: str
    coalesce_key: str


@dataclass(frozen=True)
class AdmissionReceipt:
    request_id: str
    source: str
    scope_hash: str
    mode: str
    admitted: bool
    reason: str
    window_started_at: str | None
    requests_used: int
    requests_limit: int
    cache_hit: bool
    coalesced: bool
    observed_at: str


class SQLiteReadAdmissionController:
    """Atomic process-shared rolling-window admission with fail-closed corruption handling."""

    def __init__(self, state_path: Path, *, source_limits: dict[str, tuple[int, int]] | None = None,
                 lease_seconds: int = 15):
        self._path = Path(state_path)
        self._limits = dict(source_limits or DEFAULT_SOURCE_LIMITS)
        self._lease = max(1, int(lease_seconds))
        if not self._limits:
            raise ValueError("source limits required")
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(str(self._path), timeout=2.0, isolation_level=None)
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        con = self._connect()
        try:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS admission_windows(
              source TEXT PRIMARY KEY,
              window_started REAL NOT NULL,
              requests_used INTEGER NOT NULL CHECK(requests_used >= 0)
            );
            CREATE TABLE IF NOT EXISTS admission_inflight(
              coalesce_key TEXT PRIMARY KEY,
              lease_until REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_read_audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              observed_at TEXT NOT NULL,
              principal TEXT,
              source TEXT NOT NULL,
              operation_class TEXT NOT NULL,
              scope_hash TEXT NOT NULL,
              admitted INTEGER NOT NULL,
              cache_hit INTEGER NOT NULL,
              duration_bucket TEXT,
              result_class TEXT,
              error_code TEXT
            );
            """)
        finally:
            con.close()

    @staticmethod
    def scope_hash(scope: dict) -> str:
        raw = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def admit(self, request: AdmissionRequest, *, now: float | None = None,
              cache_hit: bool = False) -> AdmissionReceipt:
        observed = time.time() if now is None else float(now)
        req_id = str(uuid.uuid4())
        try:
            scope_hash = self.scope_hash(request.scope)
        except (TypeError, ValueError):
            scope_hash = "sha256:unavailable"
            return self._receipt(req_id, request, scope_hash, False, "admission_denied",
                                 None, 0, 0, cache_hit, False, observed)
        limit_spec = self._limits.get(request.source)
        request_allowed = (
            request.request_class in DEFAULT_REQUEST_CLASSES.get(request.source, set())
            and request.verification_mode in {"bounded_sample", "full_partition"}
            and request.cost_class in {"bounded_read", "manual_full_partition"}
            and not (request.verification_mode == "full_partition"
                     and request.cost_class != "manual_full_partition")
        )
        if not request_allowed:
            return self._receipt(req_id, request, scope_hash, False, "admission_denied",
                                 None, 0, limit_spec[0] if limit_spec else 0,
                                 cache_hit, False, observed)
        if limit_spec is None:
            return self._receipt(req_id, request, scope_hash, False, "source_disabled",
                                 None, 0, 0, cache_hit, False, observed)
        limit, window_seconds = limit_spec
        try:
            con = self._connect()
            con.execute("BEGIN IMMEDIATE")
            inflight = con.execute(
                "SELECT lease_until FROM admission_inflight WHERE coalesce_key=?",
                (request.coalesce_key,)).fetchone()
            if inflight and float(inflight[0]) > observed:
                con.execute("COMMIT")
                return self._receipt(req_id, request, scope_hash, False, "coalesced_inflight",
                                     None, 0, limit, cache_hit, True, observed)
            con.execute("DELETE FROM admission_inflight WHERE lease_until <= ?", (observed,))
            row = con.execute(
                "SELECT window_started, requests_used FROM admission_windows WHERE source=?",
                (request.source,)).fetchone()
            if row is None or observed - float(row[0]) >= window_seconds:
                window_started, used = observed, 0
                con.execute(
                    "INSERT INTO admission_windows(source,window_started,requests_used) VALUES(?,?,0) "
                    "ON CONFLICT(source) DO UPDATE SET window_started=excluded.window_started, requests_used=0",
                    (request.source, window_started))
            else:
                window_started, used = float(row[0]), int(row[1])
            if used >= limit:
                con.execute("COMMIT")
                return self._receipt(req_id, request, scope_hash, False, "budget_exceeded",
                                     window_started, used, limit, cache_hit, False, observed)
            used += 1
            con.execute("UPDATE admission_windows SET requests_used=? WHERE source=?",
                        (used, request.source))
            con.execute("INSERT OR REPLACE INTO admission_inflight(coalesce_key,lease_until) VALUES(?,?)",
                        (request.coalesce_key, observed + self._lease))
            con.execute("COMMIT")
            return self._receipt(req_id, request, scope_hash, True, "admitted",
                                 window_started, used, limit, cache_hit, False, observed)
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            return self._receipt(req_id, request, scope_hash, False, "admission_state_error",
                                 None, 0, limit, cache_hit, False, observed)
        finally:
            try:
                con.close()
            except Exception:
                pass

    def release(self, coalesce_key: str) -> None:
        try:
            con = self._connect()
            con.execute("DELETE FROM admission_inflight WHERE coalesce_key=?", (coalesce_key,))
            con.close()
        except (sqlite3.DatabaseError, OSError):
            pass

    def audit(self, *, principal: str | None, source: str, operation_class: str,
              scope_hash: str, admitted: bool, cache_hit: bool, duration_bucket: str,
              result_class: str, error_code: str | None, observed_at: str | None = None) -> None:
        stamp = observed_at or _iso(time.time())
        principal = _safe_label(principal, 128)
        source = _safe_label(source, 64) or "unknown"
        operation_class = _safe_label(operation_class, 64) or "unknown"
        result_class = _safe_label(result_class, 32) or "unknown"
        error_code = _safe_label(error_code, 64)
        try:
            con = self._connect()
            con.execute(
                "INSERT INTO admin_read_audit(observed_at,principal,source,operation_class,scope_hash,"
                "admitted,cache_hit,duration_bucket,result_class,error_code) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (stamp, principal, source, operation_class, scope_hash, int(admitted), int(cache_hit),
                 duration_bucket, result_class, error_code))
            con.close()
        except (sqlite3.DatabaseError, OSError):
            # Audit failure must not accidentally grant a read.
            raise RuntimeError("audit_unavailable")

    @staticmethod
    def _receipt(req_id, request, scope_hash, admitted, reason, window_started, used,
                 limit, cache_hit, coalesced, observed):
        return AdmissionReceipt(
            request_id=req_id, source=request.source, scope_hash=scope_hash,
            mode=request.verification_mode, admitted=admitted, reason=reason,
            window_started_at=_iso(window_started) if window_started is not None else None,
            requests_used=used, requests_limit=limit, cache_hit=cache_hit,
            coalesced=coalesced, observed_at=_iso(observed))


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_label(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = "".join(ch for ch in str(value) if ch.isalnum() or ch in "._:@-/")[:limit]
    return cleaned or None
