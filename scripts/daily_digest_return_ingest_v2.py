#!/usr/bin/env python3
"""Validate Gemini Daily Digest return siblings and stage a deterministic public candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from scripts.daily_digest_normalizer_v2 import GEMINI_V2_SCHEMA, ContractError, canonical_json_bytes, normalize_digest

MANIFEST_DAY_RE = re.compile(r"^TARGET_DAY:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
MANIFEST_TZ_RE = re.compile(r"^TIMEZONE:\s*([^\s]+)\s*$", re.MULTILINE)
MANIFEST_OUTPUT_RE = re.compile(r"^-\s+([^\s]+holodocchi-gemini-digest[^\s.]*\.(?:json|md))\s*$", re.MULTILINE)
MANIFEST_VIDEO_RE = re.compile(r"^-\s+video_id:\s*[\"']?([^\s\"']+)", re.MULTILINE)


class ReturnIngestError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def parse_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    day_match = MANIFEST_DAY_RE.search(text)
    tz_match = MANIFEST_TZ_RE.search(text)
    if not day_match or not tz_match:
        raise ReturnIngestError("manifest missing TARGET_DAY or TIMEZONE")
    outputs = MANIFEST_OUTPUT_RE.findall(text)
    if len(outputs) != 2 or not any(name.endswith(".json") for name in outputs) or not any(name.endswith(".md") for name in outputs):
        raise ReturnIngestError("manifest must define exactly one JSON and one Markdown output")
    videos = MANIFEST_VIDEO_RE.findall(text)
    if not videos or len(videos) != len(set(videos)):
        raise ReturnIngestError("manifest Stream List video_ids must be non-empty and unique")
    return {
        "target_day": day_match.group(1),
        "timezone": tz_match.group(1),
        "outputs": tuple(outputs),
        "video_ids": tuple(videos),
    }


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def validate_return(payload: dict[str, Any], manifest: dict[str, Any]) -> None:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    schema = _clean(meta.get("schema_version") or payload.get("gemini_schema_version") or payload.get("SCHEMA_VERSION"))
    day = _clean(payload.get("target_day") or meta.get("target_day"))
    timezone = _clean(payload.get("timezone") or meta.get("timezone"))
    if schema != GEMINI_V2_SCHEMA:
        raise ReturnIngestError(f"unexpected Gemini schema: {schema!r}")
    if day != manifest["target_day"]:
        raise ReturnIngestError(f"target_day mismatch: source={day!r} manifest={manifest['target_day']!r}")
    if timezone != manifest["timezone"]:
        raise ReturnIngestError(f"timezone mismatch: source={timezone!r} manifest={manifest['timezone']!r}")

    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ReturnIngestError("streams must be an array")
    source_ids = [_clean(row.get("video_id")) for row in streams if isinstance(row, dict)]
    if len(source_ids) != len(streams) or any(not value for value in source_ids):
        raise ReturnIngestError("every streams[] entry must carry video_id")
    if tuple(source_ids) != manifest["video_ids"]:
        raise ReturnIngestError("Gemini streams video_id order/coverage does not match manifest Stream List")

    audit = payload.get("audit_stats") if isinstance(payload.get("audit_stats"), dict) else {}
    if audit:
        total = audit.get("total_streams")
        if total is not None and int(total) != len(manifest["video_ids"]):
            raise ReturnIngestError("audit_stats.total_streams does not match manifest Stream List")


def stage_return(
    *,
    manifest_path: Path,
    gemini_json_path: Path,
    gemini_markdown_path: Path,
    staging_root: Path,
) -> dict[str, Any]:
    manifest = parse_manifest(manifest_path)
    expected = set(manifest["outputs"])
    actual = {gemini_json_path.name, gemini_markdown_path.name}
    if expected != actual:
        raise ReturnIngestError(f"return sibling names mismatch: expected={sorted(expected)} actual={sorted(actual)}")

    json_bytes = gemini_json_path.read_bytes()
    markdown_bytes = gemini_markdown_path.read_bytes()
    if not json_bytes or not markdown_bytes:
        raise ReturnIngestError("Gemini return siblings must both be non-empty")

    try:
        payload = json.loads(json_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReturnIngestError(f"invalid Gemini JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReturnIngestError("Gemini JSON root must be an object")

    validate_return(payload, manifest)
    try:
        normalized = normalize_digest(payload)
    except ContractError as exc:
        raise ReturnIngestError(f"normalizer rejected Gemini JSON: {exc}") from exc

    raw_sha = sha256_bytes(json_bytes)
    md_sha = sha256_bytes(markdown_bytes)
    manifest_sha = sha256_bytes(manifest_path.read_bytes())
    revision_dir = staging_root / manifest["target_day"] / raw_sha
    raw_json_out = revision_dir / gemini_json_path.name
    raw_md_out = revision_dir / gemini_markdown_path.name
    public_out = revision_dir / f"{manifest['target_day']}.public-candidate.json"
    receipt_out = revision_dir / "return.receipt.json"

    public_bytes = canonical_json_bytes(normalized.artifact)
    receipt = {
        "schema_version": "holodocchi.daily_digest.return_receipt.v1",
        "status": "READY_FOR_PUBLICATION",
        "target_day": manifest["target_day"],
        "timezone": manifest["timezone"],
        "stream_count": len(manifest["video_ids"]),
        "manifest_file": manifest_path.name,
        "manifest_sha256": manifest_sha,
        "gemini_json_file": gemini_json_path.name,
        "gemini_json_sha256": raw_sha,
        "gemini_markdown_file": gemini_markdown_path.name,
        "gemini_markdown_sha256": md_sha,
        "public_candidate_file": public_out.name,
        "public_candidate_sha256": sha256_bytes(public_bytes),
        "normalizer_source_sha256": normalized.source_sha256,
        "normalizer_warnings": list(normalized.warnings),
        "revision_dir": str(revision_dir.resolve()),
        "transport_boundary": "raw-byte transport only; ingest owns validation/normalization/publication decision",
    }
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    planned = {
        raw_json_out: json_bytes,
        raw_md_out: markdown_bytes,
        public_out: public_bytes,
        receipt_out: receipt_bytes,
    }
    status = "CREATED"
    if all(path.exists() and path.read_bytes() == content for path, content in planned.items()):
        status = "NO_CHANGE"
    else:
        for path, content in planned.items():
            if path.exists() and path.read_bytes() != content:
                raise ReturnIngestError(f"immutable revision collision: {path}")
        for path, content in planned.items():
            if not path.exists():
                atomic_write(path, content)

    receipt["stage_status"] = status
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--gemini-json", required=True, type=Path)
    parser.add_argument("--gemini-markdown", required=True, type=Path)
    parser.add_argument("--staging-root", type=Path, default=Path("validation/daily-digest-v2/returns"))
    args = parser.parse_args(argv)
    try:
        receipt = stage_return(
            manifest_path=args.manifest.resolve(),
            gemini_json_path=args.gemini_json.resolve(),
            gemini_markdown_path=args.gemini_markdown.resolve(),
            staging_root=args.staging_root.resolve(),
        )
    except (ReturnIngestError, OSError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 1
    for key in (
        "stage_status", "status", "target_day", "stream_count", "gemini_json_sha256",
        "gemini_markdown_sha256", "public_candidate_sha256", "revision_dir",
    ):
        print(f"{key.upper()}={receipt[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
