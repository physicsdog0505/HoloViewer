"""Offline YouTube daily expected-set contract for Data Lifecycle #147.

No network, SQLite, D1, R2, scheduling or production writes.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")

SCHEMA_VERSION = "holoviewer-youtube-expected-set-v1"
SCOPES = {
    "history-review-66": 66,
    "today-approved-85": 85,
}
UNKNOWN_REASONS = {
    "actual_start_missing",
    "actual_start_unverified",
    "source_gap",
    "late_metadata_pending",
    "roster_membership_unknown",
    "metadata_revision_conflict",
}


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _day(value: object) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("day must be ISO YYYY-MM-DD")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def validate_expected_set(document: object) -> dict:
    """Validate one sanitized daily expected-set document.

    A VERIFIED set is complete only for its declared scope. It never implies
    completeness for the other roster scope.
    """
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported expected-set schema")
    day = _day(document.get("day"))
    scope = document.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("scope required")
    kind = scope.get("kind")
    if kind not in SCOPES:
        raise ValueError("unsupported roster scope")
    if scope.get("channel_count") != SCOPES[kind]:
        raise ValueError("scope channel_count mismatch")
    if not isinstance(scope.get("version"), str) or not scope["version"]:
        raise ValueError("scope version required")
    _sha(scope.get("hash"), "scope.hash")
    if not isinstance(document.get("issuer"), str) or not document["issuer"]:
        raise ValueError("issuer required")
    _parse_time(document.get("issued_at"))

    source = document.get("source")
    if not isinstance(source, dict):
        raise ValueError("source required")
    if not isinstance(source.get("revision"), str) or not source["revision"]:
        raise ValueError("source revision required")
    _sha(source.get("hash"), "source.hash")

    watermark = document.get("late_metadata_watermark")
    if not isinstance(watermark, dict):
        raise ValueError("late_metadata_watermark required")
    observed_through = _parse_time(watermark.get("observed_through"))
    required_after = _parse_time(watermark.get("required_after"))
    if watermark.get("status") not in {"SATISFIED", "PENDING"}:
        raise ValueError("invalid late metadata watermark status")
    if watermark["status"] == "SATISFIED" and observed_through < required_after:
        raise ValueError("satisfied watermark precedes required_after")

    rows = document.get("videos")
    expected = document.get("expected_video_ids")
    if not isinstance(rows, list) or not isinstance(expected, list):
        raise ValueError("videos and expected_video_ids required")
    if len(expected) != len(set(expected)) or any(
        not isinstance(v, str) or not VIDEO_ID.fullmatch(v) for v in expected
    ):
        raise ValueError("expected_video_ids must be unique YouTube IDs")

    seen = set()
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("video row must be object")
        video_id = row.get("video_id")
        channel_id = row.get("channel_id")
        if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id) or video_id in seen:
            raise ValueError("invalid or duplicate video_id")
        if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id):
            raise ValueError("invalid channel_id")
        if row.get("actual_start_verified") is not True:
            raise ValueError("expected video requires verified actual_start")
        if row.get("actual_start_source") != "YouTube liveStreamingDetails.actualStartTime":
            raise ValueError("actual_start authority mismatch")
        actual_start = _parse_time(row.get("actual_start"))
        if actual_start.astimezone(TAIPEI).date().isoformat() != day:
            raise ValueError("actual_start falls outside Asia/Taipei day")
        if not isinstance(row.get("revision"), str) or not row["revision"]:
            raise ValueError("video revision required")
        _sha(row.get("content_hash"), "video.content_hash")
        seen.add(video_id)
        normalized.append(video_id)

    if sorted(expected) != sorted(normalized):
        raise ValueError("expected_video_ids must exactly match verified video rows")

    unknown = document.get("unknown_cases")
    if not isinstance(unknown, list):
        raise ValueError("unknown_cases required")
    for item in unknown:
        if not isinstance(item, dict) or item.get("reason") not in UNKNOWN_REASONS:
            raise ValueError("invalid UNKNOWN case")
        value = item.get("video_id")
        if value is not None and (not isinstance(value, str) or not VIDEO_ID.fullmatch(value)):
            raise ValueError("UNKNOWN video_id invalid")

    authority = document.get("completeness_authority")
    if authority not in {"VERIFIED", "UNKNOWN"}:
        raise ValueError("invalid completeness authority")
    if authority == "VERIFIED":
        if unknown:
            raise ValueError("VERIFIED set cannot contain UNKNOWN cases")
        if watermark["status"] != "SATISFIED":
            raise ValueError("VERIFIED set requires satisfied late-metadata watermark")

    return {
        "schema_version": SCHEMA_VERSION,
        "day": day,
        "scope_kind": kind,
        "scope_version": scope["version"],
        "scope_hash": scope["hash"],
        "issuer": document["issuer"],
        "source_revision": source["revision"],
        "source_hash": source["hash"],
        "late_metadata_observed_through": watermark["observed_through"],
        "late_metadata_required_after": watermark["required_after"],
        "late_metadata_status": watermark["status"],
        "completeness_authority": authority,
        "expected_video_ids": sorted(expected),
        "unknown_cases": unknown,
    }


def audit_recent(documents: list[dict], *, as_of_day: str, window_days: int = 30) -> dict:
    """Bounded offline audit over sanitized documents only.

    The function intentionally has no provider client. It rejects documents
    outside the requested rolling window and never combines 66/85 scopes.
    """
    end = date.fromisoformat(_day(as_of_day))
    if not 1 <= window_days <= 31:
        raise ValueError("window_days must be between 1 and 31")
    start = end - timedelta(days=window_days - 1)
    rows = []
    keys = set()
    for raw in documents:
        item = validate_expected_set(raw)
        d = date.fromisoformat(item["day"])
        if d < start or d > end:
            raise ValueError("document outside bounded audit window")
        key = (item["scope_kind"], item["scope_version"], item["day"])
        if key in keys:
            raise ValueError("duplicate day/scope/version evidence")
        keys.add(key)
        rows.append({
            "day": item["day"],
            "scope_kind": item["scope_kind"],
            "scope_version": item["scope_version"],
            "completeness_authority": item["completeness_authority"],
            "expected_count": len(item["expected_video_ids"]),
            "unknown_count": len(item["unknown_cases"]),
            "late_metadata_status": item["late_metadata_status"],
            "source_revision": item["source_revision"],
            "source_hash": item["source_hash"],
        })
    rows.sort(key=lambda x: (x["day"], x["scope_kind"], x["scope_version"]))
    return {
        "schema_version": "holoviewer-youtube-expected-set-audit-v1",
        "window": {"start_day": start.isoformat(), "end_day": end.isoformat(), "days": window_days},
        "rows": rows,
        "provider_calls": 0,
        "external_writes": 0,
        "scope_merge_forbidden": True,
    }
