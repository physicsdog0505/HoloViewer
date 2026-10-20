"""Normalize read-only #48/#135/#147 evidence without inventing health."""
from __future__ import annotations

from datetime import datetime, timezone

from data_lifecycle.common import parse_time

MONITOR_STATES = {"running", "waiting", "failed", "completed", "unknown"}
HEALTH_STATES = {"healthy", "degraded", "unhealthy", "unknown", "unavailable"}


def _age_seconds(observed_at: object, now: datetime) -> float | None:
    if not isinstance(observed_at, str):
        return None
    try:
        return max(0.0, (now.astimezone(timezone.utc) - parse_time(observed_at)).total_seconds())
    except (TypeError, ValueError):
        return None


def _freshness(observed_at: object, *, now: datetime, stale_after_seconds: int) -> str:
    age = _age_seconds(observed_at, now)
    if age is None:
        return "unknown"
    return "stale" if age > stale_after_seconds else "fresh"


def _publisher_state(checkpoint: dict) -> str:
    state = checkpoint.get("state")
    return {
        "collecting": "running", "verifying": "running", "provisional": "waiting",
        "retry_pending": "waiting", "complete": "completed", "failed": "failed",
    }.get(state, "unknown")


def _job(**values) -> dict:
    result = {
        "job_id": None, "component": None, "source": None, "target": None,
        "last_attempted_at": None, "last_successful_at": None, "status": "unknown",
        "attempt_count": None, "retry_after": None, "backoff_seconds": None,
        "input_count": None, "published_count": None, "verified_count": None,
        "manifest_digest": None, "source_revision": None, "snapshot_id": None,
        "scope": None, "readback_at": None, "verification_mode": None,
        "queries_used": None, "max_queries": None,
        "rows_returned": None, "max_rows_returned": None, "rows_read_reported": None,
        "page_count": None, "max_pages": None, "cache_status": None,
        "error_code": None, "error_message": None, "last_progress_at": None,
        "evidence_source": None, "evidence_observed_at": None,
        "evidence_freshness": "unknown", "contract_gaps": [],
    }
    result.update(values)
    if result["status"] not in MONITOR_STATES:
        result["status"] = "unknown"
        result["contract_gaps"].append("unsupported-job-status")
    return result


def _telemetry(evidence: dict, component: str) -> dict:
    raw = evidence.get("job_telemetry")
    if not isinstance(raw, dict) or raw.get("schema_version") != "holoviewer-sync-job-evidence-v1":
        return {}
    item = raw.get("components", {}).get(component) if isinstance(raw.get("components"), dict) else None
    if not isinstance(item, dict):
        return {}
    allowed = {
        "job_id", "last_attempted_at", "last_successful_at", "status", "attempt_count",
        "retry_after", "backoff_seconds", "input_count", "published_count", "verified_count",
        "error_code", "last_progress_at", "manifest_digest", "source_revision", "readback_at",
    }
    result = {key: item.get(key) for key in allowed if key in item}
    # Error text is displayed only when its producer explicitly marks it sanitized.
    if item.get("error_sanitized") is True and isinstance(item.get("error_message"), str):
        result["error_message"] = item["error_message"][:240].replace("\n", " ").replace("\r", " ")
    return result


def build_sync_monitor(evidence: dict, *, now: datetime | None = None,
                       stale_after_seconds: int = 120) -> dict:
    """Build monitor rows from sanitized contracts; never infer success from presence."""
    now = now or datetime.now(timezone.utc)
    checkpoint = evidence.get("publisher_checkpoint")
    manifest = evidence.get("r2_manifest")
    target = evidence.get("d1_snapshot")
    jobs = []

    if isinstance(checkpoint, dict):
        observed = evidence.get("publisher_observed_at")
        telemetry = _telemetry(evidence, "Publisher")
        values = {
            "job_id": checkpoint.get("job_id") or checkpoint.get("last_batch_id"),
            "component": "Publisher", "source": checkpoint.get("source_identity") or "PTT SQLite",
            "target": "D1", "status": _publisher_state(checkpoint),
            "last_progress_at": evidence.get("publisher_last_progress_at"),
            "evidence_source": "#48 publisher checkpoint", "evidence_observed_at": observed,
            "evidence_freshness": _freshness(observed, now=now, stale_after_seconds=stale_after_seconds),
            "contract_gaps": [] if telemetry else ["publisher-job-telemetry-unavailable"],
        }
        values.update(telemetry)
        jobs.append(_job(**values))
    else:
        jobs.append(_job(component="Publisher", source="PTT SQLite", target="D1",
                         evidence_source="#48 publisher checkpoint",
                         contract_gaps=["publisher-checkpoint-unavailable"]))

    if isinstance(manifest, dict) and manifest.get("schema_version") == "ptt-r2-archive-v1":
        observed = manifest.get("generated_at")
        days = manifest.get("days") if isinstance(manifest.get("days"), list) else []
        complete = bool(days) and all(
            isinstance(item, dict) and item.get("coverage_status") == "COMPLETE"
            and item.get("finalized") is True for item in days
        )
        published = manifest.get("total_pushes", manifest.get("pushes"))
        telemetry = _telemetry(evidence, "R2 Archive")
        values = {
            "job_id": manifest.get("manifest_key"), "component": "R2 Archive",
            "source": "PTT SQLite", "target": "R2", "status": "unknown",
            "input_count": published, "published_count": published,
            "verified_count": published if complete and isinstance(published, int) else None,
            "last_progress_at": observed, "evidence_source": "PR #135 ptt-r2-archive-v1 manifest",
            "evidence_observed_at": observed,
            "evidence_freshness": _freshness(observed, now=now, stale_after_seconds=stale_after_seconds),
            "contract_gaps": ["manifest-is-data-evidence-not-job-success"] +
                             ([] if telemetry else ["archive-attempt-retry-error-telemetry-unavailable"]),
        }
        values.update(telemetry)
        jobs.append(_job(**values))
    else:
        jobs.append(_job(component="R2 Archive", source="PTT SQLite", target="R2",
                         evidence_source="PR #135 ptt-r2-archive-v1 manifest",
                         contract_gaps=["r2-manifest-unavailable"]))

    if isinstance(target, dict) and target.get("sanitized") is True and isinstance(target.get("rows"), list):
        observed = target.get("observed_at")
        telemetry = _telemetry(evidence, "D1 Snapshot")
        binding = target.get("job_binding") if isinstance(target.get("job_binding"), dict) else {}
        budget = target.get("query_budget") if isinstance(target.get("query_budget"), dict) else {}
        pagination = target.get("pagination") if isinstance(target.get("pagination"), dict) else {}
        verification = target.get("verification") if isinstance(target.get("verification"), dict) else {}
        values = {
            "job_id": binding.get("job_id"), "component": "D1 Snapshot", "source": "Publisher",
            "target": "D1", "status": "unknown", "published_count": len(target["rows"]),
            "snapshot_id": target.get("snapshot_id"),
            "manifest_digest": binding.get("manifest_digest"),
            "source_revision": binding.get("source_revision"),
            "scope": binding.get("scope"),
            "readback_at": observed, "verification_mode": verification.get("mode"),
            "queries_used": budget.get("queries_used"), "max_queries": budget.get("max_queries"),
            "rows_returned": budget.get("rows_returned"), "max_rows_returned": budget.get("max_rows_returned"),
            "rows_read_reported": budget.get("rows_read_reported"),
            "page_count": pagination.get("page_count"), "max_pages": budget.get("max_pages"),
            "cache_status": evidence.get("d1_cache_status"),
            "last_progress_at": observed, "evidence_source": "sanitized D1 snapshot",
            "evidence_observed_at": observed,
            "evidence_freshness": _freshness(observed, now=now, stale_after_seconds=stale_after_seconds),
            "contract_gaps": ["snapshot-presence-does-not-prove-sync-success"] +
                             ([] if telemetry else ["d1-job-telemetry-unavailable"]),
        }
        values.update(telemetry)
        jobs.append(_job(**values))
    else:
        jobs.append(_job(component="D1 Snapshot", source="Publisher", target="D1",
                         evidence_source="sanitized D1 snapshot",
                         contract_gaps=["sanitized-d1-snapshot-unavailable"]))

    return {"schema_version": "holoviewer-sync-monitor-v1", "jobs": jobs,
            "read_only": True, "rerun_sync_available": False}


def coverage_sync_consistency(inventory: object, monitor: object) -> list[dict]:
    """Report disagreement without letting either signal overwrite the other."""
    if not isinstance(inventory, dict) or not isinstance(monitor, dict):
        return [{"code": "comparison-unavailable", "severity": "unknown"}]
    jobs = monitor.get("jobs") if isinstance(monitor.get("jobs"), list) else []
    statuses = {item.get("status") for item in jobs if isinstance(item, dict)
                and item.get("component") in {"Publisher", "R2 Archive", "D1 Snapshot"}}
    coverage_states = []
    if isinstance(inventory.get("days"), list):
        days = [item for item in inventory["days"] if isinstance(item, dict)]
        scoped_jobs = [item for item in jobs if isinstance(item.get("scope"), dict)
                       and isinstance(item["scope"].get("day"), str)]
        if not scoped_jobs:
            return [{"code": "comparison-scope-unbound", "severity": "unknown"}]
        findings = []
        incomplete = {"UNKNOWN", "REPAIR_NEEDED", "LOCAL_MISSING", "PARTIAL", "CONFLICT", "PENDING_SYNC"}
        for day in days:
            day_status = day.get("status")
            day_jobs = [job for job in scoped_jobs if job["scope"].get("day") == day.get("date")]
            day_statuses = {job.get("status") for job in day_jobs}
            if day_status == "COMPLETE" and "failed" in day_statuses:
                findings.append({"code": "coverage-complete-sync-failed", "severity": "warning",
                                 "day": day.get("date")})
            if day_status in incomplete and "completed" in day_statuses:
                findings.append({"code": "sync-completed-coverage-not-complete", "severity": "warning",
                                 "day": day.get("date")})
        return findings
    sources = inventory.get("sources") if isinstance(inventory.get("sources"), list) else []
    ptt = next((item for item in sources if isinstance(item, dict) and item.get("source") == "ptt"), None)
    if ptt:
        coverage_states = [ptt.get("completeness_status")]
    if not coverage_states:
        return [{"code": "ptt-coverage-unavailable", "severity": "unknown"}]
    findings = []
    if "COMPLETE" in coverage_states and "failed" in statuses:
        findings.append({"code": "coverage-complete-sync-failed", "severity": "warning"})
    incomplete = {"UNKNOWN", "REPAIR_NEEDED", "LOCAL_MISSING", "PARTIAL", "CONFLICT", "PENDING_SYNC"}
    if any(state in incomplete for state in coverage_states) and "completed" in statuses:
        findings.append({"code": "sync-completed-coverage-not-complete", "severity": "warning"})
    return findings


def build_system_health(evidence: dict, *, now: datetime | None = None,
                        stale_after_seconds: int = 120) -> dict:
    """Require an explicit semantic probe; PID/HTTP reachability alone stays UNKNOWN."""
    now = now or datetime.now(timezone.utc)
    rows = []
    raw_components = evidence.get("components") if isinstance(evidence.get("components"), dict) else {}
    for component in ("Collector", "Publisher", "Archive", "Production API"):
        raw = raw_components.get(component)
        if not isinstance(raw, dict):
            rows.append({"component": component, "status": "unavailable",
                         "process_alive": None, "http_status": None,
                         "semantic_check": None, "observed_at": None,
                         "freshness": "unknown", "evidence_source": None,
                         "error": "monitor source unavailable"})
            continue
        semantic = raw.get("semantic_check") if isinstance(raw.get("semantic_check"), dict) else None
        status = semantic.get("status") if semantic else "unknown"
        if status not in HEALTH_STATES - {"unavailable"}:
            status = "unknown"
        observed = raw.get("observed_at")
        freshness = _freshness(observed, now=now, stale_after_seconds=stale_after_seconds)
        if freshness == "stale" and status == "healthy":
            status = "unknown"
        rows.append({"component": component, "status": status,
                     "process_alive": raw.get("process_alive"),
                     "http_status": raw.get("http_status"),
                     "semantic_check": semantic, "observed_at": observed,
                     "freshness": freshness, "evidence_source": raw.get("evidence_source"),
                     "error": raw.get("error")})
    return {"schema_version": "holoviewer-system-health-v1", "components": rows,
            "read_only": True}
