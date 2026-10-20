"""Explicitly versioned, sanitized, offline-only multi-day coverage projection."""
from __future__ import annotations

from datetime import date, timedelta

STATES = ("COMPLETE", "LOCAL_MISSING", "PENDING_SYNC", "PARTIAL", "CONFLICT", "UNKNOWN")


def _target_readback_state(evidence: object, *, day: str, expected_aids: object) -> str:
    """Interpret only the strong job-bound D1 readback contract.

    Returns COMPLETE only for independently verified full-partition readback.
    Bounded samples can never promote local COMPLETE.
    """
    if not isinstance(evidence, dict):
        return "UNKNOWN"
    if evidence.get("schema_version") != "holoviewer-d1-sanitized-snapshot-v1":
        return "UNKNOWN"
    if evidence.get("sanitized") is not True:
        return "UNKNOWN"
    verification = evidence.get("verification")
    coverage = evidence.get("coverage")
    binding = evidence.get("job_binding")
    if not isinstance(verification, dict) or not isinstance(coverage, dict) or not isinstance(binding, dict):
        return "UNKNOWN"
    if not binding.get("job_id") or not binding.get("manifest_digest") or not binding.get("source_revision"):
        return "UNKNOWN"
    scope = binding.get("scope")
    if not isinstance(scope, dict) or scope.get("day") != day:
        return "UNKNOWN"
    scoped_aids = scope.get("aids")
    if isinstance(expected_aids, list):
        if not isinstance(scoped_aids, list) or set(scoped_aids) != set(expected_aids):
            return "UNKNOWN"

    mode = verification.get("mode")
    if mode == "bounded_sample":
        return "UNKNOWN"
    if mode != "full_partition" or coverage.get("complete_partition_proven") is not True:
        return "UNKNOWN"

    missing = coverage.get("missing_identities")
    if isinstance(missing, int) and missing > 0:
        return "PENDING_SYNC"

    if (verification.get("job_verified") is True
            and verification.get("manifest_digest_match") is True
            and verification.get("identity_match") is True
            and verification.get("count_match") is True
            and missing == 0):
        return "COMPLETE"
    return "UNKNOWN"


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
        else:
            status = _target_readback_state(evidence, day=key, expected_aids=expected)
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
