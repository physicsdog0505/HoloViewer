"""Read-only Daily PTT finalization projection for Admin.

Three facts are intentionally independent:
1. source/data completeness
2. repair job outcome
3. archive package/delivery/readback outcome
"""
from __future__ import annotations

from copy import deepcopy
import re

SOURCE_STATES = {"VERIFIED_COMPLETE", "REPAIR_NEEDED", "UNKNOWN", "CONFLICT"}
JOB_STATES = {"completed", "succeeded", "failed", "running", "waiting", "unknown", "unavailable"}
PACKAGE_STATES = {"COMPLETE", "PARTIAL", "UNKNOWN"}
READBACK_STATES = {"VERIFIED", "UNKNOWN"}
_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _bounded_error_code(value: object) -> str | None:
    return value if isinstance(value, str) and _ERROR_CODE.fullmatch(value) else None


def _count_gap_ranges(gaps: object) -> int:
    if not isinstance(gaps, dict):
        return 0
    total = 0
    for value in gaps.values():
        if not isinstance(value, list) or not value:
            continue
        if all(isinstance(x, int) for x in value):
            ordered = sorted(set(value))
            total += 1 + sum(1 for a, b in zip(ordered, ordered[1:]) if b != a + 1)
        else:
            total += len(value)
    return total


def _source_state(day: dict) -> str:
    local = day.get("local_status")
    conflicts = day.get("conflicts") or []
    missing = day.get("missing_aids") or []
    gaps = day.get("source_line_gaps") or {}
    expected = day.get("expected_aids")
    actual = day.get("actual_aids")
    if conflicts or local == "CONFLICT":
        return "CONFLICT"
    if local == "REPAIR_NEEDED" or missing or _count_gap_ranges(gaps):
        return "REPAIR_NEEDED"
    if (local == "COMPLETE" and isinstance(expected, list) and isinstance(actual, list)
            and set(expected) == set(actual) and isinstance(day.get("final_verification_at"), str)
            and day.get("final_verification_at")):
        return "VERIFIED_COMPLETE"
    return "UNKNOWN"


def _repair_projection(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {
            "status": "unknown",
            "attempted": None,
            "succeeded": None,
            "failed": None,
            "attempted_at": None,
            "succeeded_at": None,
            "error_code": None,
            "contract_gaps": ["repair-job-evidence-unavailable"],
        }
    status = raw.get("status") if raw.get("status") in JOB_STATES else "unknown"
    error_code = _bounded_error_code(raw.get("error_code"))
    gaps = list(raw.get("contract_gaps") or [])
    if raw.get("error_code") is not None and error_code is None:
        gaps.append("invalid-repair-error-code")
    return {
        "status": status,
        "attempted": raw.get("attempted") if isinstance(raw.get("attempted"), bool) else None,
        "succeeded": raw.get("succeeded") if isinstance(raw.get("succeeded"), bool) else None,
        "failed": raw.get("failed") if isinstance(raw.get("failed"), bool) else None,
        "attempted_at": raw.get("attempted_at"),
        "succeeded_at": raw.get("succeeded_at"),
        "error_code": error_code,
        "contract_gaps": gaps,
    }


def _archive_projection(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("component") != "Archive":
        return {
            "package_status": "UNKNOWN",
            "delivery_job_status": "unknown",
            "readback_verified_status": "UNKNOWN",
            "job_id": None,
            "target": None,
            "readback_at": None,
            "contract_gaps": ["archive-delivery-job-evidence-unavailable"],
        }
    fields = raw.get("evidence_source_fields") if isinstance(raw.get("evidence_source_fields"), dict) else {}
    coverage = fields.get("coverage_summary") if isinstance(fields.get("coverage_summary"), dict) else {}
    package_status = coverage.get("status") if coverage.get("status") in PACKAGE_STATES else "UNKNOWN"
    delivery = raw.get("status") if raw.get("status") in JOB_STATES else "unknown"
    error_code = _bounded_error_code(raw.get("error_code"))
    archive_gaps = list(raw.get("contract_gaps") or []) + list(fields.get("contract_gaps") or [])
    if raw.get("error_code") is not None and error_code is None:
        archive_gaps.append("invalid-archive-error-code")
    # False does not mean failure for bounded samples; only explicit whole-job proof is VERIFIED.
    readback = "VERIFIED" if fields.get("job_verified") is True else "UNKNOWN"
    return {
        "package_status": package_status,
        "delivery_job_status": delivery,
        "readback_verified_status": readback,
        "job_id": raw.get("job_id"),
        "target": raw.get("target"),
        "readback_at": fields.get("readback_observed_at"),
        "verification_mode": fields.get("verification_mode"),
        "error_code": error_code,
        "contract_gaps": archive_gaps,
    }


def build_daily_finalization(evidence: dict) -> dict:
    """Project latest daily finalization without inventing producer truth."""
    coverage = evidence.get("coverage") if isinstance(evidence.get("coverage"), dict) else {}
    days = coverage.get("days") if isinstance(coverage.get("days"), list) else []
    normalized_days = [item for item in days if isinstance(item, dict) and isinstance(item.get("date"), str)]
    target_day = evidence.get("target_day") if isinstance(evidence.get("target_day"), str) else None
    if target_day is not None:
        day = next((item for item in normalized_days if item.get("date") == target_day), {})
    else:
        day = max(normalized_days, key=lambda item: item["date"]) if normalized_days else {}

    expected = day.get("expected_aids") if isinstance(day.get("expected_aids"), list) else None
    missing = day.get("missing_aids") if isinstance(day.get("missing_aids"), list) else []
    gaps = day.get("source_line_gaps") if isinstance(day.get("source_line_gaps"), dict) else {}

    source_status = _source_state(day)
    repair = _repair_projection(evidence.get("repair_job"))
    archive = _archive_projection(evidence.get("archive_sync_job"))

    contract_gaps = []
    contract_gaps.extend(day.get("contract_gaps") or [])
    contract_gaps.extend(repair["contract_gaps"])
    contract_gaps.extend(archive["contract_gaps"])
    if not day:
        contract_gaps.append("source-completeness-evidence-unavailable")
    if day and not day.get("final_verification_at"):
        contract_gaps.append("final-verification-timestamp-unavailable")

    top_error = _bounded_error_code(evidence.get("error_code"))
    if evidence.get("error_code") is not None and top_error is None:
        contract_gaps.append("invalid-error-code")

    final_verification_at = day.get("final_verification_at")
    return {
        "schema_version": "holoviewer-admin-daily-finalization-v1",
        "read_only": True,
        "closeout_schedule": {"local_time": "07:30", "timezone": "Asia/Taipei"},
        "runs": [{
            "target_day": target_day or day.get("date"),
            "source_completeness": {
                "status": source_status,
                "expected_aid_count": len(expected) if expected is not None else None,
                "missing_aid_count": len(missing),
                "missing_range_count": _count_gap_ranges(gaps),
                "final_verification_at": final_verification_at,
            },
            "repair_job": {k: v for k, v in repair.items() if k != "contract_gaps"},
            "archive": {k: v for k, v in archive.items() if k != "contract_gaps"},
            "error_code": top_error,
            "contract_gaps": sorted(set(str(x) for x in contract_gaps if x)),
            "evidence": {
                "coverage_day": deepcopy(day),
                "repair_job": deepcopy(evidence.get("repair_job")),
                "archive_sync_job": deepcopy(evidence.get("archive_sync_job")),
            },
        }],
    }
