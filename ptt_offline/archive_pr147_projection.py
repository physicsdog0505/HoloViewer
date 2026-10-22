"""Pure PR #147 Sync Monitor projection for Archive delivery evidence."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .archive_job_evidence import JOB_SCHEMA, validate_archive_job_evidence


def project_archive_job_for_pr147(evidence: dict[str,Any]) -> dict[str,Any]:
    value=validate_archive_job_evidence(evidence)
    manifest=value.get("manifest") if isinstance(value.get("manifest"),dict) else {}
    target=value.get("target") if isinstance(value.get("target"),dict) else {}
    coverage=value.get("coverage_summary") if isinstance(value.get("coverage_summary"),dict) else {}
    expected=value.get("expected_aid_completeness")
    if not isinstance(expected,dict):
        expected={"status":"UNKNOWN","authority":None,
                  "contract_gaps":["expected-aid-authority-unavailable"]}

    # Archive delivery, archive data coverage, and expected-AID completeness are
    # intentionally separate outputs. Consumers must not promote one from another.
    return {
        "schema_version":"holoviewer-pr147-archive-monitor-projection-v1",
        "sanitized":True,
        "component":"Archive",
        "job_id":value.get("job_id"),
        "target":{"kind":target.get("kind"),"identity":target.get("identity")},
        "source_revision":value.get("source_revision"),
        "source_hash":value.get("source_hash"),
        "manifest_digest":manifest.get("digest"),
        "manifest_key":manifest.get("key"),
        "manifest_schema_version":manifest.get("schema_version"),
        "attempted_at":value.get("attempted_at"),
        "succeeded_at":value.get("succeeded_at"),
        "attempt_count":value.get("attempt_count"),
        "retry_after":value.get("retry_after"),
        "backoff_seconds":value.get("backoff_seconds"),
        "error_code":value.get("error_code"),
        "uploaded_count":value.get("uploaded_count"),
        "independently_verified_count":value.get("independently_verified_count"),
        "snapshot_id":value.get("snapshot_id"),
        "readback_observed_at":value.get("readback_observed_at"),
        "verification_mode":value.get("verification_mode"),
        "job_verified":value.get("job_verified"),
        "coverage_summary":deepcopy(coverage),
        "job_status":value.get("job_status"),
        "expected_aid_completeness":deepcopy(expected),
        "contract_gaps":list(value.get("contract_gaps") or []),
    }


def project_archive_as_sync_job(evidence: dict[str,Any]) -> dict[str,Any]:
    """Projection shaped for PR #147's normalized Sync Monitor fields.

    Target-specific evidence remains nested in evidence_source_fields, while the
    existing generic monitor keys preserve nulls and do not infer job success.
    """
    item=project_archive_job_for_pr147(evidence)
    status_map={
        "pending":"waiting",
        "attempted":"running",
        "succeeded":"completed",
        "failed":"failed",
        "unknown":"unknown",
    }
    return {
        "job_id":item["job_id"],
        "component":"Archive",
        "source":"PTT Archive",
        "target":item["target"]["kind"],
        "last_attempted_at":item["attempted_at"],
        "last_successful_at":item["succeeded_at"],
        "status":status_map.get(item["job_status"],"unknown"),
        "attempt_count":item["attempt_count"],
        "retry_after":item["retry_after"],
        "backoff_seconds":item["backoff_seconds"],
        "input_count":item["coverage_summary"].get("object_count"),
        "published_count":item["uploaded_count"],
        "verified_count":item["independently_verified_count"],
        "error_code":item["error_code"],
        "error_message":None,
        "last_progress_at":item["readback_observed_at"] or item["attempted_at"],
        "evidence_source":"#48 archive delivery evidence",
        "evidence_observed_at":item["readback_observed_at"] or item["attempted_at"],
        "contract_gaps":item["contract_gaps"],
        "evidence_source_fields":item,
    }
