"""Pure offline validators for #147 sanitized readback/health evidence.

No network, SQLite, D1, R2, subprocess or writer imports.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re

_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_KEYS = {"author", "content", "cookie", "authorization", "password", "secret",
                  "api_key", "raw_error", "request_headers", "response_body"}


def _iso(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key).lower()
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def canonical_sha256(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_d1_snapshot(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("snapshot object required")
    if raw.get("schema_version") != "holoviewer-d1-sanitized-snapshot-v1":
        raise ValueError("unsupported D1 snapshot schema")
    if raw.get("sanitized") is not True:
        raise ValueError("sanitized=true required")
    if FORBIDDEN_KEYS.intersection(_walk_keys(raw)):
        raise ValueError("forbidden sensitive/content field")
    if not _iso(raw.get("observed_at")):
        raise ValueError("valid observed_at required")

    snapshot_id = raw.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not _SHA.fullmatch(snapshot_id):
        raise ValueError("sha256 snapshot_id required")
    material = deepcopy(raw)
    material.pop("snapshot_id", None)
    if canonical_sha256(material) != snapshot_id:
        raise ValueError("snapshot_id digest mismatch")

    binding = raw.get("job_binding")
    if not isinstance(binding, dict) or not isinstance(binding.get("job_id"), str) or not binding["job_id"]:
        raise ValueError("job_id required")
    if not _SHA.fullmatch(str(binding.get("manifest_digest", ""))):
        raise ValueError("manifest_digest required")
    if not isinstance(binding.get("source_revision"), str) or not binding["source_revision"]:
        raise ValueError("source_revision required")
    if not isinstance(binding.get("scope"), dict):
        raise ValueError("job scope required")

    budget = raw.get("query_budget")
    if not isinstance(budget, dict):
        raise ValueError("query_budget required")
    limits = {
        "max_queries": (1, 3),
        "max_pages": (1, 5),
        "max_rows_returned": (1, 500),
        "cache_ttl_seconds": (60, 3600),
    }
    for key, (low, high) in limits.items():
        value = budget.get(key)
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{key} outside bounded dashboard contract")
    if not isinstance(budget.get("queries_used"), int) or budget["queries_used"] > budget["max_queries"]:
        raise ValueError("queries_used exceeds budget")
    if not isinstance(budget.get("rows_returned"), int) or budget["rows_returned"] > budget["max_rows_returned"]:
        raise ValueError("rows_returned exceeds budget")

    pagination = raw.get("pagination")
    if not isinstance(pagination, dict) or pagination.get("mode") != "keyset":
        raise ValueError("keyset pagination required")
    if not isinstance(pagination.get("page_size"), int) or pagination["page_size"] > 100:
        raise ValueError("page_size exceeds contract")
    if not isinstance(pagination.get("page_count"), int) or pagination["page_count"] > budget["max_pages"]:
        raise ValueError("page_count exceeds contract")

    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) != budget["rows_returned"]:
        raise ValueError("row count/budget mismatch")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("identity"), dict):
            raise ValueError("sanitized row identity required")
        if row.get("revision") is None:
            raise ValueError("target-visible revision required")
        if not _SHA.fullmatch(str(row.get("content_hash", ""))):
            raise ValueError("row content_hash required")
        if not isinstance(row.get("verified"), bool):
            raise ValueError("verified boolean required")

    verification = raw.get("verification")
    if not isinstance(verification, dict) or verification.get("mode") not in {"bounded_sample", "full_partition"}:
        raise ValueError("verification mode required")
    if verification["mode"] == "bounded_sample" and verification.get("job_verified") is not False:
        raise ValueError("bounded sample cannot verify a job")
    if verification.get("job_verified") is True:
        coverage = raw.get("coverage") if isinstance(raw.get("coverage"), dict) else {}
        if verification["mode"] != "full_partition" or coverage.get("complete_partition_proven") is not True:
            raise ValueError("full partition proof required for job_verified")

    return raw


def validate_api_semantic_health(raw: object) -> dict:
    if not isinstance(raw, dict) or raw.get("schema_version") != "holoviewer-api-semantic-health-v1":
        raise ValueError("unsupported API semantic health schema")
    if raw.get("sanitized") is not True or not _iso(raw.get("observed_at")):
        raise ValueError("sanitized fresh evidence envelope required")
    if FORBIDDEN_KEYS.intersection(_walk_keys(raw)):
        raise ValueError("forbidden sensitive/content field")
    if raw.get("overall_status") not in {"healthy", "degraded", "unhealthy", "unknown"}:
        raise ValueError("invalid overall_status")
    probes = raw.get("probes")
    if not isinstance(probes, list) or not probes:
        raise ValueError("semantic probes required")
    for probe in probes:
        if not isinstance(probe, dict) or not isinstance(probe.get("http_status"), int):
            raise ValueError("probe http status required")
        if probe.get("semantic_status") not in {"healthy", "degraded", "unhealthy", "unknown"}:
            raise ValueError("invalid semantic_status")
        if probe.get("name") == "health" and probe.get("http_status") == 200 and probe.get("semantic_status") == "healthy":
            raise ValueError("/health 200 cannot self-certify semantic health")
    budget = raw.get("query_budget")
    if not isinstance(budget, dict) or not isinstance(budget.get("http_requests_max"), int):
        raise ValueError("HTTP query budget required")
    if budget["http_requests_max"] > 4 or budget.get("http_requests_used", 0) > budget["http_requests_max"]:
        raise ValueError("HTTP query budget exceeded")
    if budget.get("cache_ttl_seconds", 0) < 60:
        raise ValueError("semantic probe cache TTL too small")
    return raw
