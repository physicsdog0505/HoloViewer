"""Explicitly versioned, sanitized, offline-only multi-day coverage projection."""
from __future__ import annotations

from datetime import date, timedelta

STATES = ("COMPLETE", "LOCAL_MISSING", "PENDING_SYNC", "PARTIAL", "CONFLICT", "UNKNOWN")


def project_coverage(days: list[dict], *, start_day: str, end_day: str) -> dict:
    """Create every expected date, even when no inventory was supplied.

    Input day rows may contain PR147 daily inventories or a normalized PTT row
    with the same evidence fields. Missing dates are always UNKNOWN, never complete.
    """
    start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
    if end < start or (end - start).days > 366:
        raise ValueError("invalid or excessive day range")
    indexed = {}
    for item in days:
        day = item.get("date")
        if day in indexed:
            raise ValueError("duplicate day")
        indexed[day] = item
    rows = []
    current = start
    while current <= end:
        key = current.isoformat()
        item = indexed.get(key, {})
        source = next((x for x in item.get("sources", []) if x.get("source") == "ptt"), {}) if isinstance(item.get("sources"), list) else item
        expected = source.get("expected_set")
        actual = source.get("actual_set", [])
        gaps = source.get("source_line_gaps") or {}
        missing = source.get("missing_ids") or []
        conflicts = source.get("conflicts") or []
        evidence = source.get("target_evidence") or {}
        base = source.get("completeness_status", "UNKNOWN")
        if conflicts or base == "CONFLICT":
            status = "CONFLICT"
        elif base != "COMPLETE":
            status = "LOCAL_MISSING" if missing else "PARTIAL" if gaps or base == "REPAIR_NEEDED" else "UNKNOWN"
        elif evidence.get("verified") is True and evidence.get("all_expected_present") is True:
            status = "COMPLETE"
        elif evidence.get("verified") is True and evidence.get("all_expected_present") is False:
            status = "PENDING_SYNC"
        else:
            status = "UNKNOWN"  # local completeness alone does not prove target completeness
        rows.append({
            "date": key, "status": status, "local_status": base,
            "expected_aids": expected, "actual_aids": actual,
            "missing_aids": missing, "source_line_gaps": gaps,
            "conflicts": conflicts, "target_evidence": evidence,
            "contract_gaps": source.get("contract_gaps", []),
            "source_version": source.get("source_version"),
            "last_updated_at": source.get("last_updated_at"),
        })
        current += timedelta(days=1)
    return {"schema_version": "holoviewer-admin-coverage-v1", "from_day": start_day,
            "through_day": end_day, "days": rows, "read_only": True}
