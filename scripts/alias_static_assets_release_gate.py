#!/usr/bin/env python3
"""Pure helpers for the #228 Alias forward-only Static Assets release gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


class AliasReleaseGateError(RuntimeError):
    pass


ALIAS_PREFIX = "site/data/search/aliases/v1/"
PUBLIC_ALIAS_PREFIX = "/data/search/aliases/v1/"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_lower_hex(value: str, length: int, label: str) -> None:
    if len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
        raise AliasReleaseGateError(f"{label} must be {length} lowercase hex characters")


def validate_alias_site_delta(rows: Iterable[str]) -> dict:
    """Allow exactly latest.json plus one newly-added immutable SHA object."""
    actual = [row.strip() for row in rows if row.strip()]
    if len(actual) != 2:
        raise AliasReleaseGateError(f"Alias site delta must contain exactly 2 paths, got {actual!r}")
    latest = [row for row in actual if row.endswith("\tsite/data/search/aliases/v1/latest.json")]
    versions = [
        row for row in actual
        if "\tsite/data/search/aliases/v1/versions/" in row and row.endswith(".json")
    ]
    if len(latest) != 1 or len(versions) != 1:
        raise AliasReleaseGateError(f"Alias delta must be latest.json + one version object: {actual!r}")
    latest_status = latest[0].split("\t", 1)[0]
    version_status, version_path = versions[0].split("\t", 1)
    if latest_status not in {"A", "M"}:
        raise AliasReleaseGateError(f"unexpected latest.json status: {latest_status}")
    if version_status != "A":
        raise AliasReleaseGateError(f"immutable version must be newly added, got {version_status}")
    stem = Path(version_path).stem
    require_lower_hex(stem, 64, "immutable Alias filename")
    return {"latest_status": latest_status, "immutable_path": version_path, "immutable_sha256": stem}


def validate_alias_contract(site_root: str | Path) -> dict:
    root = Path(site_root)
    latest_path = root / "data/search/aliases/v1/latest.json"
    if not latest_path.is_file():
        raise AliasReleaseGateError("Alias latest.json missing")
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AliasReleaseGateError("Alias latest.json invalid") from exc
    if latest.get("schema_version") != 1 or latest.get("dataset") != "holodocchi-member-aliases-public-v1":
        raise AliasReleaseGateError("Alias latest.json schema/dataset mismatch")
    digest = str(latest.get("sha256") or "")
    require_lower_hex(digest, 64, "Alias pointer sha256")
    expected_asset = f"{PUBLIC_ALIAS_PREFIX}versions/{digest}.json"
    if latest.get("asset_path") != expected_asset:
        raise AliasReleaseGateError("Alias latest.json asset_path does not match sha256")
    immutable = root / expected_asset.lstrip("/")
    if not immutable.is_file():
        raise AliasReleaseGateError("Alias immutable object missing")
    raw = immutable.read_bytes()
    if sha256_bytes(raw) != digest:
        raise AliasReleaseGateError("Alias immutable bytes do not match filename/pointer SHA")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise AliasReleaseGateError("Alias immutable payload invalid JSON") from exc
    if payload.get("schema_version") != 1 or payload.get("dataset") != "holodocchi-member-aliases-public-v1":
        raise AliasReleaseGateError("Alias immutable schema/dataset mismatch")
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        raise AliasReleaseGateError("Alias members must be a non-empty list")
    ids = []
    alias_count = 0
    for member in members:
        if not isinstance(member, dict):
            raise AliasReleaseGateError("Alias member entry must be object")
        channel_id = str(member.get("channel_id") or "")
        if not channel_id:
            raise AliasReleaseGateError("Alias member missing channel_id")
        ids.append(channel_id)
        aliases = member.get("aliases")
        if not isinstance(aliases, list):
            raise AliasReleaseGateError(f"Alias list missing for {channel_id}")
        alias_count += len(aliases)
        for alias in aliases:
            if not isinstance(alias, dict):
                raise AliasReleaseGateError("Alias entry must be object")
            if set(alias) != {"value", "normalized_value", "strength", "enabled"}:
                raise AliasReleaseGateError("Public Alias entry exposes unexpected fields")
            if alias.get("strength") not in {"strong", "weak"}:
                raise AliasReleaseGateError("invalid Alias strength")
    if len(ids) != len(set(ids)):
        raise AliasReleaseGateError("duplicate channel_id in public Alias payload")
    return {
        "sha256": digest,
        "member_count": len(members),
        "alias_count": alias_count,
        "latest_path": "site/data/search/aliases/v1/latest.json",
        "immutable_path": f"site/data/search/aliases/v1/versions/{digest}.json",
    }


def youtube_manifest_paths(manifest: dict) -> list[dict]:
    if manifest.get("schema_version") != 1:
        raise AliasReleaseGateError("Production YouTube manifest schema mismatch")
    months = manifest.get("months")
    indexes = manifest.get("channel_indexes")
    if not isinstance(months, list) or not isinstance(indexes, list):
        raise AliasReleaseGateError("Production YouTube manifest inventory missing")
    entries: list[dict] = []
    for item in [*months, *indexes]:
        if not isinstance(item, dict):
            raise AliasReleaseGateError("malformed Production YouTube manifest entry")
        logical = str(item.get("path") or "")
        if not logical.startswith("youtube/v1/"):
            raise AliasReleaseGateError(f"unsafe Production YouTube path: {logical!r}")
        rel = Path(logical)
        if rel.is_absolute() or ".." in rel.parts:
            raise AliasReleaseGateError(f"unsafe Production YouTube path: {logical!r}")
        size = item.get("bytes")
        digest = str(item.get("sha256") or "")
        if not isinstance(size, int) or size < 0:
            raise AliasReleaseGateError(f"invalid Production YouTube byte count: {logical}")
        require_lower_hex(digest, 64, f"YouTube SHA for {logical}")
        entries.append({"path": logical, "bytes": size, "sha256": digest})
    paths = [e["path"] for e in entries]
    if len(paths) != len(set(paths)):
        raise AliasReleaseGateError("duplicate Production YouTube manifest path")
    return entries


def verify_declared_bytes(data: bytes, entry: dict) -> None:
    if len(data) != entry["bytes"]:
        raise AliasReleaseGateError(f"byte length mismatch: {entry['path']}")
    if sha256_bytes(data) != entry["sha256"]:
        raise AliasReleaseGateError(f"sha256 mismatch: {entry['path']}")
