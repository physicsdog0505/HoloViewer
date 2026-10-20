"""Offline #47 semantic-health producer for PR #147 handoff.

Consumes sanitized observations only. No network, D1, YouTube provider, subprocess,
route, scheduler or writer surface.
"""
from __future__ import annotations

from datetime import datetime, timezone

SCHEMA = "holoviewer-api-semantic-health-v1"
ALLOWED = {"healthy", "degraded", "unhealthy", "unknown"}
FORBIDDEN = {
    "title", "body", "content", "author", "cookie", "authorization", "headers",
    "request_headers", "response_headers", "secret", "password", "api_key", "token",
}


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _forbidden(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN or _forbidden(item):
                return True
    elif isinstance(value, list):
        return any(_forbidden(item) for item in value)
    return False


def _semantic_probe(name: str, raw: dict, *, observed_at: datetime,
                    stale_after_seconds: int) -> dict:
    http_status = raw.get("http_status")
    reachable = isinstance(http_status, int) and 200 <= http_status < 500
    schema_expected = raw.get("expected_schema")
    schema_actual = raw.get("schema_version")
    watermark = _parse(raw.get("semantic_watermark"))
    source_freshness = raw.get("source_freshness")
    gap = raw.get("gap")
    partial = raw.get("coverage_status") == "partial"
    unknown_authority = raw.get("authority") in {None, "unknown"}
    age = None if watermark is None else max(0.0, (observed_at - watermark).total_seconds())

    if name == "health":
        status, reason = "unknown", "reachability-only"
    elif not reachable:
        status, reason = "unhealthy", "http-unreachable"
    elif not isinstance(schema_expected, str) or schema_actual != schema_expected:
        status, reason = "unhealthy", "schema-mismatch"
    elif watermark is None:
        status, reason = "unknown", "semantic-watermark-missing"
    elif source_freshness not in {"fresh", "stale"}:
        status, reason = "unknown", "source-freshness-unknown"
    elif source_freshness == "stale" or age is None or age > stale_after_seconds:
        status, reason = "degraded", "semantic-watermark-stale"
    elif gap is True or partial:
        status, reason = "degraded", "gap-or-partial-coverage"
    elif unknown_authority:
        status, reason = "unknown", "semantic-authority-unknown"
    else:
        status, reason = "healthy", "schema-watermark-authority-valid"

    probe = {
        "name": name,
        "path": str(raw.get("path") or ""),
        "http_status": http_status if isinstance(http_status, int) else 0,
        "reachable": reachable,
        "semantic_status": status,
        "reason": reason,
        "schema_version": schema_actual if isinstance(schema_actual, str) else None,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
    }
    if name != "health":
        probe["content_health"] = {
            "semantic_watermark": raw.get("semantic_watermark"),
            "source_freshness": source_freshness if source_freshness in {"fresh", "stale"} else "unknown",
            "gap": bool(gap) if isinstance(gap, bool) else None,
            "coverage_status": raw.get("coverage_status"),
            "authority": raw.get("authority"),
        }
    return probe


def build_semantic_health(observation: dict, *, stale_after_seconds: int = 120) -> dict:
    """Project sanitized #47 observations into the #147 semantic-health envelope."""
    if not isinstance(observation, dict) or observation.get("sanitized") is not True:
        raise ValueError("sanitized observation required")
    if _forbidden(observation):
        raise ValueError("forbidden sensitive/content field")
    observed_at = _parse(observation.get("observed_at"))
    if observed_at is None:
        raise ValueError("timezone-aware observed_at required")
    if not isinstance(stale_after_seconds, int) or stale_after_seconds <= 0:
        raise ValueError("positive stale_after_seconds required")
    raw_probes = observation.get("probes")
    if not isinstance(raw_probes, dict):
        raise ValueError("probe observations required")

    probes = []
    for name in ("health", "today", "history"):
        raw = raw_probes.get(name)
        if isinstance(raw, dict):
            probes.append(_semantic_probe(name, raw, observed_at=observed_at,
                                          stale_after_seconds=stale_after_seconds))
    if not probes:
        raise ValueError("at least one semantic probe required")

    semantic = [p["semantic_status"] for p in probes if p["name"] != "health"]
    if "unhealthy" in semantic:
        overall = "unhealthy"
    elif "degraded" in semantic:
        overall = "degraded"
    elif semantic and all(x == "healthy" for x in semantic):
        overall = "healthy"
    elif semantic:
        overall = "unknown"
    else:
        overall = "unknown"

    return {
        "schema_version": SCHEMA,
        "sanitized": True,
        "observed_at": observation["observed_at"],
        "target": {
            "service": str(observation.get("service") or "holoviewer-public-api"),
            "base_url": str(observation.get("base_url") or ""),
        },
        "overall_status": overall,
        "evidence_freshness": "fresh",
        "probes": probes,
        "query_budget": {
            "http_requests_used": 0,
            "http_requests_max": 0,
            "cache_ttl_seconds": 60,
        },
        "contract_gaps": list(observation.get("contract_gaps") or []),
        "producer_mode": "offline-sanitized-projection",
    }


def expected_set_authority_envelope(document: dict) -> dict:
    """Map a validated #47 expected-set document into the #147 authority envelope."""
    from .youtube_expected_set import validate_expected_set

    item = validate_expected_set(document)
    return {
        "verified": item["completeness_authority"] == "VERIFIED",
        "day": item["day"],
        "version": f'{item["scope_version"]}+{item["source_revision"]}',
        "issuer": item["issuer"],
        "evidence_hash": item["source_hash"],
        "scope": {
            "kind": item["scope_kind"],
            "version": item["scope_version"],
            "hash": item["scope_hash"],
        },
        "late_metadata_watermark": {
            "observed_through": item["late_metadata_observed_through"],
            "required_after": item["late_metadata_required_after"],
            "status": item["late_metadata_status"],
        },
        "completeness_authority": item["completeness_authority"],
        "unknown_cases": item["unknown_cases"],
    }
