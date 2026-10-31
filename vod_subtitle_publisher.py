from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Iterable

ASSET_SCHEMA_VERSION = "holodocchi-vod-subtitle-v1"
RECEIPT_SCHEMA_VERSION = "holodocchi-vod-subtitle-publish-receipt-v1"
INDEX_SCHEMA_VERSION = 1
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
VIDEO_PATH = "/data/subtitles/videos/{video_id}.json"
GLOBAL_INDEX_PATH = "data/subtitles/index.json"
MONTH_INDEX_DIR = "data/subtitles/manifests/by-vod-month"
DEFAULT_CATALOG_MANIFEST = "youtube/v1/manifest.json"


class VodSubtitlePublishError(ValueError):
    pass


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> tuple[bytes, object]:
    try:
        raw = path.read_bytes()
        return raw, json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VodSubtitlePublishError(f"invalid JSON: {path}") from exc


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _validate_video_asset(asset: object, *, expected_video_id: str | None = None) -> dict[str, object]:
    if not isinstance(asset, dict):
        raise VodSubtitlePublishError("subtitle asset must be an object")
    required = {
        "schema_version", "video_id", "source_transcript_id", "source_content_hash",
        "translation_artifact_id", "translation_identity", "segment_count", "cues",
    }
    if set(asset) != required:
        raise VodSubtitlePublishError("subtitle asset fields mismatch")
    if asset["schema_version"] != ASSET_SCHEMA_VERSION:
        raise VodSubtitlePublishError("subtitle asset schema mismatch")
    video_id = str(asset["video_id"])
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise VodSubtitlePublishError("invalid video_id")
    if expected_video_id is not None and video_id != expected_video_id:
        raise VodSubtitlePublishError("subtitle asset video_id mismatch")
    if not str(asset["source_transcript_id"]):
        raise VodSubtitlePublishError("missing source_transcript_id")
    if not HEX64_RE.fullmatch(str(asset["source_content_hash"])):
        raise VodSubtitlePublishError("invalid source_content_hash")
    if not HEX64_RE.fullmatch(str(asset["translation_artifact_id"])):
        raise VodSubtitlePublishError("invalid translation_artifact_id")
    if not isinstance(asset["translation_identity"], dict):
        raise VodSubtitlePublishError("invalid translation_identity")
    count = asset["segment_count"]
    cues = asset["cues"]
    if type(count) is not int or count < 1 or not isinstance(cues, list) or len(cues) != count:
        raise VodSubtitlePublishError("subtitle segment_count mismatch")
    previous_start = -1
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict) or set(cue) != {"id", "start_ms", "end_ms", "zh_tw"}:
            raise VodSubtitlePublishError("invalid subtitle cue")
        if cue["id"] != index or type(cue["start_ms"]) is not int or type(cue["end_ms"]) is not int:
            raise VodSubtitlePublishError("invalid subtitle cue identity")
        if cue["start_ms"] < 0 or cue["end_ms"] <= cue["start_ms"] or cue["start_ms"] < previous_start:
            raise VodSubtitlePublishError("subtitle cues are not ordered")
        if not isinstance(cue["zh_tw"], str) or not cue["zh_tw"].strip():
            raise VodSubtitlePublishError("empty zh-TW subtitle cue")
        previous_start = cue["start_ms"]
    return asset


def _receipt_payload(asset: dict[str, object], asset_sha256: str, staged_at: str) -> dict[str, object]:
    if not staged_at or "T" not in staged_at:
        raise VodSubtitlePublishError("staged_at must be an explicit timestamp")
    video_id = str(asset["video_id"])
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "video_id": video_id,
        "asset_path": VIDEO_PATH.format(video_id=video_id),
        "asset_sha256": asset_sha256,
        "translation_artifact_id": asset["translation_artifact_id"],
        "source_transcript_id": asset["source_transcript_id"],
        "source_content_hash": asset["source_content_hash"],
        "staged_at": staged_at,
    }


def stage_receipt(asset_root: str | Path, receipts_root: str | Path, video_id: str, staged_at: str) -> dict[str, object]:
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise VodSubtitlePublishError("invalid video_id")
    relative = VIDEO_PATH.format(video_id=video_id).lstrip("/")
    asset_path = Path(asset_root) / relative
    raw, value = _read_json(asset_path)
    asset = _validate_video_asset(value, expected_video_id=video_id)
    receipt_path = Path(receipts_root) / f"{video_id}.json"
    planned = _receipt_payload(asset, _sha(raw), staged_at)
    if receipt_path.exists():
        _existing_raw, existing_value = _read_json(receipt_path)
        existing = _validate_receipt(existing_value)
        immutable_keys = set(planned) - {"staged_at"}
        if any(existing[key] != planned[key] for key in immutable_keys):
            raise VodSubtitlePublishError(f"immutable receipt conflict: {video_id}")
        return {"video_id": video_id, "receipt_path": str(receipt_path), "created": False}
    _write_atomic(receipt_path, _canonical_json(planned))
    return {"video_id": video_id, "receipt_path": str(receipt_path), "created": True}


def _validate_receipt(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise VodSubtitlePublishError("receipt must be an object")
    fields = {
        "schema_version", "video_id", "asset_path", "asset_sha256",
        "translation_artifact_id", "source_transcript_id", "source_content_hash", "staged_at",
    }
    if set(value) != fields or value["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise VodSubtitlePublishError("receipt contract mismatch")
    video_id = str(value["video_id"])
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise VodSubtitlePublishError("invalid receipt video_id")
    if value["asset_path"] != VIDEO_PATH.format(video_id=video_id):
        raise VodSubtitlePublishError("receipt asset_path mismatch")
    for key in ("asset_sha256", "translation_artifact_id", "source_content_hash"):
        if not HEX64_RE.fullmatch(str(value[key])):
            raise VodSubtitlePublishError(f"invalid receipt {key}")
    if not str(value["source_transcript_id"]) or not str(value["staged_at"]):
        raise VodSubtitlePublishError("receipt identity incomplete")
    return value


def load_receipts(receipts_root: str | Path) -> dict[str, dict[str, object]]:
    root = Path(receipts_root)
    paths = sorted(root.glob("*.json"))
    if not paths:
        raise VodSubtitlePublishError("no immutable publish receipts found")
    receipts: dict[str, dict[str, object]] = {}
    for path in paths:
        raw, value = _read_json(path)
        receipt = _validate_receipt(value)
        if raw != _canonical_json(receipt):
            raise VodSubtitlePublishError(f"receipt is not canonical: {path.name}")
        video_id = str(receipt["video_id"])
        if path.name != f"{video_id}.json" or video_id in receipts:
            raise VodSubtitlePublishError("receipt filename/identity conflict")
        receipts[video_id] = receipt
    return receipts


def _safe_catalog_path(root: Path, raw_path: str) -> Path:
    relative = raw_path.lstrip("/")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not relative.startswith("youtube/v1/"):
        raise VodSubtitlePublishError("catalog manifest path escapes youtube/v1")
    return root / relative


def catalog_video_months(catalog_root: str | Path, manifest_path: str = DEFAULT_CATALOG_MANIFEST) -> dict[str, str]:
    root = Path(catalog_root)
    manifest_file = _safe_catalog_path(root, "/" + manifest_path.lstrip("/"))
    _raw, value = _read_json(manifest_file)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("months"), list):
        raise VodSubtitlePublishError("existing VOD catalog manifest contract mismatch")
    result: dict[str, str] = {}
    for entry in value["months"]:
        if not isinstance(entry, dict):
            raise VodSubtitlePublishError("invalid VOD catalog month entry")
        month = str(entry.get("month", ""))
        path = str(entry.get("path", ""))
        if not MONTH_RE.fullmatch(month) or not path:
            raise VodSubtitlePublishError("invalid VOD catalog month identity")
        _month_raw, month_value = _read_json(_safe_catalog_path(root, path))
        if not isinstance(month_value, dict) or month_value.get("schema_version") != 1:
            raise VodSubtitlePublishError("VOD catalog month contract mismatch")
        if month_value.get("month") not in (None, month):
            raise VodSubtitlePublishError("VOD catalog month mismatch")
        videos = month_value.get("videos")
        if not isinstance(videos, list):
            raise VodSubtitlePublishError("VOD catalog month videos missing")
        for row in videos:
            if not isinstance(row, dict):
                continue
            video_id = str(row.get("video_id", ""))
            if not VIDEO_ID_RE.fullmatch(video_id):
                continue
            previous = result.get(video_id)
            if previous is not None and previous != month:
                raise VodSubtitlePublishError(f"video appears in multiple VOD catalog months: {video_id}")
            result[video_id] = month
    return result


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _index_entry(receipt: dict[str, object]) -> dict[str, object]:
    return {"video_id": receipt["video_id"], "staged_at": receipt["staged_at"]}


def _validate_indexes(candidate_root: Path, receipts: dict[str, dict[str, object]], months: dict[str, str]) -> None:
    _raw, global_value = _read_json(candidate_root / GLOBAL_INDEX_PATH)
    if not isinstance(global_value, dict) or set(global_value) != {"schema_version", "video_count", "videos"}:
        raise VodSubtitlePublishError("global index contract mismatch")
    if global_value["schema_version"] != INDEX_SCHEMA_VERSION or global_value["video_count"] != len(receipts):
        raise VodSubtitlePublishError("global index count mismatch")
    expected_global = [_index_entry(receipts[key]) for key in sorted(receipts)]
    if global_value["videos"] != expected_global:
        raise VodSubtitlePublishError("global index is not derived from receipts")

    grouped: dict[str, list[dict[str, object]]] = {}
    for video_id in sorted(receipts):
        month = months.get(video_id)
        if month is None:
            raise VodSubtitlePublishError(f"VOD catalog month lookup failed: {video_id}")
        grouped.setdefault(month, []).append(_index_entry(receipts[video_id]))
    month_dir = candidate_root / MONTH_INDEX_DIR
    actual = sorted(p.name for p in month_dir.glob("*.json")) if month_dir.exists() else []
    expected = [f"{month}.json" for month in sorted(grouped)]
    if actual != expected:
        raise VodSubtitlePublishError("by-VOD-month index set mismatch")
    for month, rows in grouped.items():
        _raw, value = _read_json(month_dir / f"{month}.json")
        if not isinstance(value, dict) or set(value) != {"schema_version", "month", "video_count", "videos"}:
            raise VodSubtitlePublishError("by-VOD-month index contract mismatch")
        if value != {"schema_version": 1, "month": month, "video_count": len(rows), "videos": rows}:
            raise VodSubtitlePublishError("by-VOD-month index content mismatch")


def validate_candidate(candidate_root: str | Path, receipts_root: str | Path, catalog_root: str | Path, *, catalog_manifest: str = DEFAULT_CATALOG_MANIFEST) -> dict[str, object]:
    root = Path(candidate_root)
    receipts = load_receipts(receipts_root)
    months = catalog_video_months(catalog_root, catalog_manifest)
    if any((root / "data/subtitles/manifests").glob("[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        raise VodSubtitlePublishError("old manifests/<YYYY-MM>.json contract is forbidden")
    if (root / "data/subtitles/receipts").exists() or (root / "data/watchalong").exists():
        raise VodSubtitlePublishError("private receipts/Watchalong content exposed in public candidate")
    for video_id, receipt in receipts.items():
        asset_path = root / str(receipt["asset_path"]).lstrip("/")
        raw, value = _read_json(asset_path)
        asset = _validate_video_asset(value, expected_video_id=video_id)
        if _sha(raw) != receipt["asset_sha256"]:
            raise VodSubtitlePublishError(f"candidate asset hash mismatch: {video_id}")
        for key in ("translation_artifact_id", "source_transcript_id", "source_content_hash"):
            if asset[key] != receipt[key]:
                raise VodSubtitlePublishError(f"candidate asset receipt mismatch: {video_id}")
    actual_assets = sorted(p.name for p in (root / "data/subtitles/videos").glob("*.json"))
    expected_assets = [f"{video_id}.json" for video_id in sorted(receipts)]
    if actual_assets != expected_assets:
        raise VodSubtitlePublishError("candidate video asset set does not match receipts")
    _validate_indexes(root, receipts, months)
    return {"video_count": len(receipts), "tree_sha256": _tree_digest(root)}


def build_candidate(asset_root: str | Path, receipts_root: str | Path, catalog_root: str | Path, candidate_root: str | Path, *, catalog_manifest: str = DEFAULT_CATALOG_MANIFEST) -> dict[str, object]:
    receipts = load_receipts(receipts_root)
    months = catalog_video_months(catalog_root, catalog_manifest)
    for video_id in receipts:
        if video_id not in months:
            raise VodSubtitlePublishError(f"VOD catalog month lookup failed: {video_id}")

    destination = Path(candidate_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = Path(tempfile.mkdtemp(prefix=destination.name + ".", dir=destination.parent))
    try:
        shell_headers = Path(__file__).resolve().parent / "vod-subtitles-static/_headers"
        if shell_headers.is_file():
            shutil.copy2(shell_headers, temp / "_headers")
        videos_dir = temp / "data/subtitles/videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        for video_id, receipt in receipts.items():
            source = Path(asset_root) / str(receipt["asset_path"]).lstrip("/")
            raw, value = _read_json(source)
            asset = _validate_video_asset(value, expected_video_id=video_id)
            if _sha(raw) != receipt["asset_sha256"]:
                raise VodSubtitlePublishError(f"staged asset hash mismatch: {video_id}")
            for key in ("translation_artifact_id", "source_transcript_id", "source_content_hash"):
                if asset[key] != receipt[key]:
                    raise VodSubtitlePublishError(f"staged asset receipt mismatch: {video_id}")
            (videos_dir / f"{video_id}.json").write_bytes(raw)

        global_index = {
            "schema_version": 1,
            "video_count": len(receipts),
            "videos": [_index_entry(receipts[key]) for key in sorted(receipts)],
        }
        (temp / GLOBAL_INDEX_PATH).parent.mkdir(parents=True, exist_ok=True)
        (temp / GLOBAL_INDEX_PATH).write_bytes(_canonical_json(global_index))

        grouped: dict[str, list[dict[str, object]]] = {}
        for video_id in sorted(receipts):
            grouped.setdefault(months[video_id], []).append(_index_entry(receipts[video_id]))
        month_dir = temp / MONTH_INDEX_DIR
        month_dir.mkdir(parents=True, exist_ok=True)
        for month, rows in sorted(grouped.items()):
            payload = {"schema_version": 1, "month": month, "video_count": len(rows), "videos": rows}
            (month_dir / f"{month}.json").write_bytes(_canonical_json(payload))

        checked = validate_candidate(temp, receipts_root, catalog_root, catalog_manifest=catalog_manifest)
        if destination.exists() and _tree_digest(destination) == checked["tree_sha256"]:
            return {**checked, "candidate_root": str(destination), "changed": False}
        if destination.exists():
            shutil.rmtree(destination)
        temp.replace(destination)
        temp = None
        return {**checked, "candidate_root": str(destination), "changed": True}
    finally:
        if temp is not None and temp.exists():
            shutil.rmtree(temp)


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    receipt = sub.add_parser("receipt")
    receipt.add_argument("--asset-root", required=True)
    receipt.add_argument("--receipts-root", required=True)
    receipt.add_argument("--video-id", required=True)
    receipt.add_argument("--staged-at", required=True)

    for name in ("build", "validate"):
        command = sub.add_parser(name)
        command.add_argument("--receipts-root", required=True)
        command.add_argument("--catalog-root", required=True)
        command.add_argument("--catalog-manifest", default=DEFAULT_CATALOG_MANIFEST)
        command.add_argument("--candidate-root", required=True)
        if name == "build":
            command.add_argument("--asset-root", required=True)

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "receipt":
            result = stage_receipt(args.asset_root, args.receipts_root, args.video_id, args.staged_at)
        elif args.command == "build":
            result = build_candidate(args.asset_root, args.receipts_root, args.catalog_root, args.candidate_root, catalog_manifest=args.catalog_manifest)
        else:
            result = validate_candidate(args.candidate_root, args.receipts_root, args.catalog_root, catalog_manifest=args.catalog_manifest)
    except (OSError, VodSubtitlePublishError) as exc:
        parser.exit(1, f"VOD subtitle publisher failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
