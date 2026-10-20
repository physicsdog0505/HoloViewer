"""Offline #47 semantic-health producer for PR #147 handoff.

Consumes sanitized observations only. No network, D1, YouTube provider, subprocess,
route, scheduler or writer surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import parse_qsl, urlsplit

SCHEMA = "holoviewer-api-semantic-health-v1"
ALLOWED = {"healthy", "degraded", "unhealthy", "unknown"}

CONTENT_KEYS = {"title", "body", "content", "author", "headers", "request_headers", "response_headers"}
SENSITIVE_KEY_PARTS = {
    "secret", "token", "password", "authorization", "auth", "cookie", "credential",
    "api_key", "apikey", "private_key", "privatekey",
}
SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "refresh_token", "api_key", "apikey", "key",
    "secret", "client_secret", "hmac_secret", "authorization", "auth", "credential",
}
SAFE_BASE_HOSTS = {"holoviewer-public-api.singlebagel.workers.dev"}


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _sensitive_key(value: object) -> bool:
    key = _normalize_key(value)
    if key in CONTENT_KEYS:
        return True
    parts = set(key.split("_"))
    if key in SENSITIVE_KEY_PARTS or parts.intersection(SENSITIVE_KEY_PARTS):
        return True
    collapsed = key.replace("_", "")
    return any(marker.replace("_", "") in collapsed for marker in {
        "client_secret", "hmac_secret", "access_token", "refresh_token",
        "wrangler_credential", "x_api_key", "api_token", "private_key",
    })


def _forbidden(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _sensitive_key(key) or _forbidden(item):
                return True
    elif isinstance(value, list):
        return any(_forbidden(item) for item in value)
    return False


def _safe_base_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("unsafe base_url")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("unsafe base_url")
    if parsed.query or parsed.fragment or (parsed.path not in {"", "/"}):
        raise ValueError("unsafe base_url")
    if parsed.hostname.lower() not in SAFE_BASE_HOSTS:
        raise ValueError("unapproved base_url host")
    return f"https://{parsed.hostname.lower()}"


def _safe_probe_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise ValueError("relative probe path required")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("unsafe probe path")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        norm = _normalize_key(key)
        if norm in SENSITIVE_QUERY_KEYS or _sensitive_key(norm):
            raise ValueError("sensitive probe query parameter")
    return parsed.path + (("?" + parsed.query) if parsed.query else "")


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
        "path": _safe_probe_path(raw.get("path") or ""),
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
            "base_url": _safe_base_url(observation.get("base_url") or ""),
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
