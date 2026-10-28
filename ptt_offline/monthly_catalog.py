"""Verified daily PTT packages -> stable monthly Static Assets catalog.

This module is intentionally free of Collector/Publisher restart behavior and
Cloudflare deployment side effects. It consumes already-authorized closeout
evidence, validates immutable daily package bytes, and produces one canonical
monthly catalog that can be published by the owner-local Static Assets runtime.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

CATALOG_SCHEMA = "holoviewer-ptt-monthly-catalog-v1"
DAILY_SCHEMA = "holoviewer-ptt-daily-static-package-v1"
LEGACY_SCHEMA = "ptt-r2-archive-v1"
DAY_V1 = "holoviewer-ptt-history-day-v1"
DAY_V2 = "holoviewer-ptt-history-day-v2"
TPE = ZoneInfo("Asia/Taipei")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class MonthlyCatalogError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _require_sha(value: object, label: str) -> str:
    value = str(value or "")
    if not SHA_RE.fullmatch(value):
        raise MonthlyCatalogError(f"{label} must be lowercase SHA-256")
    return value


def _safe_key(value: object) -> str:
    value = str(value or "")
    if not value or value.startswith("/") or not value.endswith(".json"):
        raise MonthlyCatalogError("safe relative JSON object key required")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise MonthlyCatalogError("unsafe relative object key")
    return value


def _parse_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonthlyCatalogError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MonthlyCatalogError(f"{label} object required")
    return value


def _day_bounds(day: str) -> tuple[datetime, datetime, datetime]:
    if not DAY_RE.fullmatch(day):
        raise MonthlyCatalogError("canonical Taipei day required")
    start = datetime.fromisoformat(day).replace(tzinfo=TPE).astimezone(timezone.utc)
    end = start + timedelta(days=1)
    closeout = end + timedelta(hours=7, minutes=30)
    return start, end, closeout


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_aware(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise MonthlyCatalogError(f"{label} required")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonthlyCatalogError(f"{label} invalid") from exc
    if out.tzinfo is None:
        raise MonthlyCatalogError(f"{label} must be timezone-aware")
    return out.astimezone(timezone.utc)


def validate_downstream_authorization(*, downstream_authorized: bool) -> None:
    if downstream_authorized is not True:
        raise MonthlyCatalogError("downstream_authorized=false; archive publication forbidden")


def validate_closeout_evidence(
    *,
    day: str,
    finalization: dict[str, Any],
    archive_job: dict[str, Any],
) -> None:
    if not isinstance(finalization, dict) or finalization.get("day") != day:
        raise MonthlyCatalogError("finalization day mismatch")
    if finalization.get("state") != "VERIFIED_COMPLETE":
        raise MonthlyCatalogError("finalization is not VERIFIED_COMPLETE")
    if finalization.get("archive_ready") is not True:
        raise MonthlyCatalogError("finalization archive_ready=true required")

    if not isinstance(archive_job, dict):
        raise MonthlyCatalogError("archive job receipt required")
    if archive_job.get("day") not in (None, day):
        raise MonthlyCatalogError("archive job day mismatch")
    if archive_job.get("job_verified") is not True:
        raise MonthlyCatalogError("archive job is not verified")
    manifest_verified = archive_job.get("manifest_verified")
    if manifest_verified is None and isinstance(archive_job.get("readback_receipt"), dict):
        manifest_verified = archive_job["readback_receipt"].get("manifest_verified")
    if manifest_verified is not True:
        raise MonthlyCatalogError("archive manifest readback is not verified")
    readback = archive_job.get("remote_readback") or archive_job.get("readback_receipt") or {}
    if readback:
        for key in ("object_sha_verified", "push_count_verified", "partition_range_verified"):
            if key in readback and readback[key] is not True:
                raise MonthlyCatalogError(f"remote readback {key}=false")


def _validate_daily_object(
    *,
    day: str,
    item: dict[str, Any],
    raw: bytes,
    seen_identities: set[str],
) -> tuple[int, str, str]:
    expected_sha = _require_sha(item.get("sha256"), "daily object sha256")
    if digest_bytes(raw) != expected_sha:
        raise MonthlyCatalogError("daily object SHA mismatch")
    payload = _parse_json(raw, "daily object")
    pushes = payload.get("pushes")
    if not isinstance(pushes, list):
        raise MonthlyCatalogError("daily object pushes list required")
    expected_count = item.get("pushes", item.get("push_count"))
    if not isinstance(expected_count, int) or expected_count < 0 or len(pushes) != expected_count:
        raise MonthlyCatalogError("daily object push count mismatch")

    start, end, closeout = _day_bounds(day)
    schema = payload.get("schema_version")
    pstart = _parse_aware(payload.get("partition_start"), "partition_start")
    pend = _parse_aware(payload.get("partition_end"), "partition_end")
    membership = payload.get("membership")
    if not isinstance(membership, dict) or membership.get("silent_drop") is not False:
        raise MonthlyCatalogError("daily object membership audit invalid")

    if schema == DAY_V1:
        if pstart != start or pend != end:
            raise MonthlyCatalogError("daily v1 partition range mismatch")
    elif schema == DAY_V2:
        if payload.get("partition_kind") != "expected-thread-lifecycle":
            raise MonthlyCatalogError("daily v2 partition kind mismatch")
        if pstart != start or not (end <= pend <= closeout):
            raise MonthlyCatalogError("daily v2 partition range mismatch")
        if membership.get("handoff_boundary") != payload.get("partition_end"):
            raise MonthlyCatalogError("daily v2 handoff boundary mismatch")
        if membership.get("closeout_limit") != _iso_z(closeout):
            raise MonthlyCatalogError("daily v2 closeout limit mismatch")
    else:
        raise MonthlyCatalogError("unsupported daily object schema")

    for row in pushes:
        if not isinstance(row, dict):
            raise MonthlyCatalogError("daily push row invalid")
        key = str(row.get("source_record_key") or "")
        if not key:
            raise MonthlyCatalogError("source_record_key required")
        if key in seen_identities:
            raise MonthlyCatalogError("duplicate source_record_key")
        seen_identities.add(key)
        if row.get("coverage_day") != day:
            raise MonthlyCatalogError("push coverage_day mismatch")
        occurred = _parse_aware(row.get("occurred_at"), "push occurred_at")
        if not (pstart <= occurred < pend):
            raise MonthlyCatalogError("push outside partition range")
        if row.get("floor") is None or row.get("floor_quality") != "per-thread-ordinal":
            raise MonthlyCatalogError("authoritative per-thread floor required")
    return len(pushes), _iso_z(pstart), _iso_z(pend)


def validate_daily_package(
    *,
    manifest_key: str,
    manifest_raw: bytes,
    object_loader: Callable[[str], bytes],
    expected_day: str | None = None,
) -> dict[str, Any]:
    manifest_key = _safe_key(manifest_key)
    manifest = _parse_json(manifest_raw, "daily manifest")
    if manifest.get("schema_version") != DAILY_SCHEMA:
        raise MonthlyCatalogError("unsupported daily package schema")
    day = str(manifest.get("taipei_day") or "")
    if expected_day is not None and day != expected_day:
        raise MonthlyCatalogError("daily package day mismatch")
    _day_bounds(day)
    objects = manifest.get("objects")
    if not isinstance(objects, list) or not objects:
        raise MonthlyCatalogError("daily package requires objects")
    if manifest.get("total_objects") not in (None, len(objects)):
        raise MonthlyCatalogError("daily manifest object count mismatch")

    seen_keys: set[str] = set()
    seen_identities: set[str] = set()
    total = 0
    ranges: list[tuple[str, str]] = []
    normalized_objects = []
    for item in objects:
        if not isinstance(item, dict):
            raise MonthlyCatalogError("daily manifest object entry invalid")
        key = _safe_key(item.get("key"))
        if key in seen_keys:
            raise MonthlyCatalogError("duplicate daily object key")
        seen_keys.add(key)
        raw = object_loader(key)
        if not isinstance(raw, (bytes, bytearray)):
            raise MonthlyCatalogError("daily object loader must return bytes")
        count, pstart, pend = _validate_daily_object(
            day=day, item=item, raw=bytes(raw), seen_identities=seen_identities
        )
        total += count
        ranges.append((pstart, pend))
        normalized_objects.append(
            {
                "key": key,
                "sha256": _require_sha(item.get("sha256"), "daily object sha256"),
                "pushes": count,
                "partition_start": pstart,
                "partition_end": pend,
            }
        )

    expected_total = manifest.get("total_pushes")
    if not isinstance(expected_total, int) or expected_total < 0 or total != expected_total:
        raise MonthlyCatalogError("daily manifest total push count mismatch")
    if len(seen_identities) != total:
        raise MonthlyCatalogError("duplicate source_record_key")
    source_hash = _require_sha(manifest.get("source_hash"), "daily source_hash")
    manifest_sha = digest_bytes(manifest_raw)
    return {
        "day": day,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha,
        "source_hash": source_hash,
        "push_count": total,
        "partition_start": min(r[0] for r in ranges),
        "partition_end": max(r[1] for r in ranges),
        "objects": normalized_objects,
    }


def validate_legacy_manifest(*, manifest_key: str, manifest_raw: bytes) -> dict[str, Any]:
    manifest_key = _safe_key(manifest_key)
    manifest = _parse_json(manifest_raw, "legacy manifest")
    if manifest.get("schema_version") != LEGACY_SCHEMA:
        raise MonthlyCatalogError("unsupported legacy archive schema")
    if manifest.get("precision") != "minute" or manifest.get("timezone") != "UTC":
        raise MonthlyCatalogError("legacy manifest precision/timezone mismatch")
    month = str(manifest.get("month") or "")
    if not MONTH_RE.fullmatch(month):
        raise MonthlyCatalogError("legacy manifest month invalid")
    objects = manifest.get("objects")
    days = manifest.get("days")
    if not isinstance(objects, list) or not isinstance(days, list):
        raise MonthlyCatalogError("legacy manifest objects/days required")
    seen = set()
    for item in objects:
        if not isinstance(item, dict):
            raise MonthlyCatalogError("legacy object entry invalid")
        key = _safe_key(item.get("key"))
        if key in seen:
            raise MonthlyCatalogError("duplicate legacy object key")
        seen.add(key)
        _require_sha(item.get("sha256"), "legacy object sha256")
        count = item.get("pushes", item.get("push_count"))
        if not isinstance(count, int) or count < 0:
            raise MonthlyCatalogError("legacy object push count invalid")
        start = item.get("bucket_start", item.get("partition_start"))
        end = item.get("bucket_end", item.get("partition_end"))
        if _parse_aware(start, "legacy object start") >= _parse_aware(end, "legacy object end"):
            raise MonthlyCatalogError("legacy object partition range invalid")
    complete_days = []
    for row in days:
        if not isinstance(row, dict):
            continue
        day = str(row.get("day") or "")
        if not DAY_RE.fullmatch(day) or not day.startswith(month + "-"):
            continue
        if row.get("coverage_status") == "COMPLETE" and row.get("finalized") is True:
            complete_days.append(day)
    return {
        "month": month,
        "manifest_key": manifest_key,
        "manifest_sha256": digest_bytes(manifest_raw),
        "complete_days": sorted(set(complete_days)),
    }


def _empty_catalog(month: str) -> dict[str, Any]:
    if not MONTH_RE.fullmatch(month):
        raise MonthlyCatalogError("month must be YYYY-MM")
    return {
        "schema_version": CATALOG_SCHEMA,
        "month": month,
        "timezone": "Asia/Taipei",
        "source_policy": "verified-complete-only-v1",
        "days": [],
    }


def load_catalog(raw: bytes | None, *, month: str) -> dict[str, Any]:
    if raw is None:
        return _empty_catalog(month)
    catalog = _parse_json(raw, "monthly catalog")
    if catalog.get("schema_version") != CATALOG_SCHEMA or catalog.get("month") != month:
        raise MonthlyCatalogError("monthly catalog identity mismatch")
    if catalog.get("timezone") != "Asia/Taipei" or not isinstance(catalog.get("days"), list):
        raise MonthlyCatalogError("monthly catalog contract invalid")
    seen = set()
    for row in catalog["days"]:
        if not isinstance(row, dict):
            raise MonthlyCatalogError("monthly catalog day entry invalid")
        day = str(row.get("day") or "")
        if day in seen or not DAY_RE.fullmatch(day) or not day.startswith(month + "-"):
            raise MonthlyCatalogError("monthly catalog day identity invalid")
        seen.add(day)
        if row.get("coverage_status") != "COMPLETE":
            raise MonthlyCatalogError("monthly catalog may reference only COMPLETE days")
        source = row.get("source")
        if not isinstance(source, dict) or source.get("kind") not in {"legacy-archive-v1", "daily-package-v1"}:
            raise MonthlyCatalogError("monthly catalog source invalid")
        if not str(source.get("base") or "").startswith("https://"):
            raise MonthlyCatalogError("monthly catalog source base invalid")
        m = source.get("manifest")
        if not isinstance(m, dict):
            raise MonthlyCatalogError("monthly catalog manifest reference required")
        _safe_key(m.get("key"))
        _require_sha(m.get("sha256"), "monthly catalog manifest sha256")
    return catalog


def _catalog_result(catalog: dict[str, Any], previous_raw: bytes | None) -> dict[str, Any]:
    catalog["days"] = sorted(catalog["days"], key=lambda row: row["day"])
    if catalog["days"]:
        catalog["updated_through"] = catalog["days"][-1]["day"]
    else:
        catalog.pop("updated_through", None)
    raw = canonical_bytes(catalog)
    return {
        "catalog": catalog,
        "raw": raw,
        "sha256": digest_bytes(raw),
        "changed": previous_raw != raw,
        "key": f"ptt/v1/manifests/monthly/{catalog['month']}.json",
    }


def seed_verified_legacy(
    *,
    month: str,
    existing_catalog_raw: bytes | None,
    base_url: str,
    manifest_key: str,
    manifest_raw: bytes,
    legacy_readback_verified: bool,
) -> dict[str, Any]:
    if legacy_readback_verified is not True:
        raise MonthlyCatalogError("legacy coverage lacks verified readback authorization")
    base_url = str(base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise MonthlyCatalogError("legacy base URL must be https")
    legacy = validate_legacy_manifest(manifest_key=manifest_key, manifest_raw=manifest_raw)
    if legacy["month"] != month:
        raise MonthlyCatalogError("legacy month mismatch")
    catalog = load_catalog(existing_catalog_raw, month=month)
    by_day = {row["day"]: row for row in catalog["days"]}
    for day in legacy["complete_days"]:
        candidate = {
            "day": day,
            "coverage_status": "COMPLETE",
            "source": {
                "kind": "legacy-archive-v1",
                "base": base_url,
                "manifest": {
                    "key": manifest_key,
                    "sha256": legacy["manifest_sha256"],
                    "schema_version": LEGACY_SCHEMA,
                },
            },
        }
        if day in by_day and by_day[day] != candidate:
            raise MonthlyCatalogError(f"conflicting verified source for {day}")
        by_day[day] = candidate
    catalog["days"] = list(by_day.values())
    return _catalog_result(catalog, existing_catalog_raw)


def advance_verified_daily(
    *,
    month: str,
    existing_catalog_raw: bytes | None,
    downstream_authorized: bool,
    finalization: dict[str, Any],
    archive_job: dict[str, Any],
    base_url: str,
    manifest_key: str,
    manifest_raw: bytes,
    object_loader: Callable[[str], bytes],
) -> dict[str, Any]:
    validate_downstream_authorization(downstream_authorized=downstream_authorized)
    base_url = str(base_url or "").rstrip("/")
    if not base_url.startswith("https://"):
        raise MonthlyCatalogError("daily base URL must be https")
    verified = validate_daily_package(
        manifest_key=manifest_key,
        manifest_raw=manifest_raw,
        object_loader=object_loader,
    )
    day = verified["day"]
    if not day.startswith(month + "-"):
        raise MonthlyCatalogError("daily package outside target month")
    validate_closeout_evidence(day=day, finalization=finalization, archive_job=archive_job)

    archive_manifest_digest = archive_job.get("manifest_digest")
    if archive_manifest_digest is None and isinstance(archive_job.get("manifest"), dict):
        archive_manifest_digest = archive_job["manifest"].get("digest")
    if archive_manifest_digest is not None and archive_manifest_digest != verified["manifest_sha256"]:
        raise MonthlyCatalogError("archive job manifest digest mismatch")

    catalog = load_catalog(existing_catalog_raw, month=month)
    candidate = {
        "day": day,
        "coverage_status": "COMPLETE",
        "push_count": verified["push_count"],
        "partition_start": verified["partition_start"],
        "partition_end": verified["partition_end"],
        "source": {
            "kind": "daily-package-v1",
            "base": base_url,
            "manifest": {
                "key": manifest_key,
                "sha256": verified["manifest_sha256"],
                "schema_version": DAILY_SCHEMA,
            },
            "source_hash": verified["source_hash"],
        },
    }
    by_day = {row["day"]: row for row in catalog["days"]}
    if day in by_day:
        if by_day[day] != candidate:
            raise MonthlyCatalogError(f"conflicting verified digest for {day}")
        return _catalog_result(catalog, existing_catalog_raw)
    by_day[day] = candidate
    catalog["days"] = list(by_day.values())
    return _catalog_result(catalog, existing_catalog_raw)
