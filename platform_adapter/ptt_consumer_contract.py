"""#68 Public PTT *consumer* validation only — no provider/router implementation.

The shape comes from #48's PttTodayReadModel/PttHistoryReadModel.
This module must not dispatch routes, calculate PTT floors or push identity,
query SQLite/D1, or substitute itself for the accepted PTT renderer.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from platform_adapter.public_api import PublicAPIUnavailable

PUBLIC_PUSH_FIELDS = frozenset({
    "push_id", "aid", "source_line", "kind", "author",
    "content", "occurred_at", "floor", "source_url",
})
_STATUSES = frozenset({"fresh", "stale", "unknown"})
_COMPLETENESS = frozenset({"complete", "partial", "unverified"})


def validate_ptt_consumer_envelope(
    payload: Any, *, day: str, history: bool = False,
) -> dict[str, Any]:
    """Validate #48 public read envelope without inventing missing content.

    The returned document is the original provider-owned envelope. This only
    recognizes public-safe fields; the actual 4174 PTT consumer stays closed
    until the reviewed #48 API mount and renderer binding are available.
    """
    try:
        if not isinstance(payload, dict):
            raise ValueError("expected object")
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError("noncanonical day")
        if payload.get("schema_version") != "public-consumer-v1":
            raise ValueError("unknown schema")
        if payload.get("day") != day:
            raise ValueError("cross-day provider response")
        if not isinstance(payload.get("as_of"), str) or not payload["as_of"]:
            raise ValueError("missing as_of")
        freshness, completeness = payload.get("freshness"), payload.get("completeness")
        if not isinstance(freshness, dict) or freshness.get("status") not in _STATUSES:
            raise ValueError("invalid freshness")
        if not isinstance(completeness, dict) or completeness.get("status") not in _COMPLETENESS:
            raise ValueError("invalid completeness")
        if type(completeness.get("gap")) is not bool:
            raise ValueError("unknown gap")
        if not isinstance(payload.get("checkpoint"), (str, type(None))):
            raise ValueError("checkpoint must remain opaque")
        pushes, page = payload.get("pushes"), payload.get("page")
        if not isinstance(pushes, list) or not isinstance(page, dict):
            raise ValueError("missing public page")
        limit = page.get("limit")
        if type(limit) is not int or not 1 <= limit <= (200 if history else 300):
            raise ValueError("unbounded page")
        if type(page.get("has_more")) is not bool:
            raise ValueError("missing pagination state")
        if not isinstance(page.get("next_checkpoint"), (str, type(None))):
            raise ValueError("invalid opaque continuation")
        for row in pushes:
            if not isinstance(row, dict) or set(row) != PUBLIC_PUSH_FIELDS:
                raise ValueError("internal/nonpublic PTT push fields")
            if row["kind"] not in (None, "推", "噓", "→"):
                raise ValueError("invalid public push kind")
            if not isinstance(row["push_id"], str) or not row["push_id"].startswith("ptt:v1:"):
                raise ValueError("invalid canonical public identity")
            if not isinstance(row["aid"], str) or not row["aid"]:
                raise ValueError("missing public AID")
    except (ValueError, TypeError, KeyError) as exc:
        raise PublicAPIUnavailable("Invalid #48 public PTT consumer envelope") from exc
    return payload
