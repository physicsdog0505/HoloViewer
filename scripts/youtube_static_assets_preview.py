from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


class PreviewError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_object(data: bytes, *, label: str) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreviewError(f"invalid JSON for {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreviewError(f"expected JSON object for {label}")
    return value


def _load_manifest(v1_root: str | Path) -> tuple[Path, bytes, dict]:
    root = Path(v1_root).expanduser().resolve()
    path = root / "manifest.json"
    if not path.is_file():
        raise PreviewError(f"manifest missing: {path}")
    raw = path.read_bytes()
    manifest = _json_object(raw, label="manifest")
    if manifest.get("schema_version") != 1:
        raise PreviewError("unsupported manifest schema_version")
    if not isinstance(manifest.get("current_month"), str):
        raise PreviewError("manifest current_month missing")
    if not isinstance(manifest.get("months"), list):
        raise PreviewError("manifest months must be list")
    if not isinstance(manifest.get("channel_indexes"), list):
        raise PreviewError("manifest channel_indexes must be list")
    return root, raw, manifest


def _relative_logical(path: str) -> Path:
    prefix = "youtube/v1/"
    if not isinstance(path, str) or not path.startswith(prefix):
        raise PreviewError(f"unexpected logical path: {path!r}")
    rel = Path(path[len(prefix):])
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise PreviewError(f"unsafe logical path: {path}")
    return rel


def _verify_declared(data: bytes, item: dict, *, label: str) -> None:
    expected_bytes = item.get("bytes")
    expected_sha = item.get("sha256")
    if not isinstance(expected_bytes, int) or expected_bytes < 0:
        raise PreviewError(f"{label}: invalid bytes")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise PreviewError(f"{label}: invalid sha256")
    if len(data) != expected_bytes:
        raise PreviewError(f"{label}: byte length mismatch")
    if _sha256(data) != expected_sha:
        raise PreviewError(f"{label}: sha256 mismatch")


def verify_local_tree(v1_root: str | Path) -> dict:
    root, manifest_raw, manifest = _load_manifest(v1_root)
    month_count = 0
    video_count = 0
    for item in manifest["months"]:
        if not isinstance(item, dict):
            raise PreviewError("malformed month manifest entry")
        rel = _relative_logical(item.get("path"))
        path = root / rel
        if not path.is_file():
            raise PreviewError(f"month missing: {item.get('path')}")
        raw = path.read_bytes()
        _verify_declared(raw, item, label=f"month {item.get('path')}")
        payload = _json_object(raw, label=f"month {item.get('path')}")
        if payload.get("schema_version") != 1:
            raise PreviewError(f"month schema mismatch: {item.get('path')}")
        videos = payload.get("videos")
        if not isinstance(videos, list):
            raise PreviewError(f"month videos invalid: {item.get('path')}")
        expected_count = item.get("count")
        if not isinstance(expected_count, int) or expected_count != len(videos):
            raise PreviewError(f"month count mismatch: {item.get('path')}")
        month_count += 1
        video_count += len(videos)

    declared_indexes: set[str] = set()
    for item in manifest["channel_indexes"]:
        if not isinstance(item, dict):
            raise PreviewError("malformed channel index manifest entry")
        rel = _relative_logical(item.get("path"))
        declared_indexes.add(rel.as_posix())
        path = root / rel
        if not path.is_file():
            raise PreviewError(f"channel index missing: {item.get('path')}")
        raw = path.read_bytes()
        _verify_declared(raw, item, label=f"index {item.get('path')}")
        payload = _json_object(raw, label=f"index {item.get('path')}")
        if payload.get("schema_version") != 1:
            raise PreviewError(f"index schema mismatch: {item.get('path')}")
        if payload.get("channel_id") != item.get("channel_id"):
            raise PreviewError(f"channel_id mismatch: {item.get('path')}")
        months = payload.get("months")
        if not isinstance(months, dict) or any(
            not isinstance(ids, list) for ids in months.values()
        ):
            raise PreviewError(f"index months invalid: {item.get('path')}")
        actual_count = sum(len(ids) for ids in months.values())
        if actual_count != item.get("video_count"):
            raise PreviewError(f"index video_count mismatch: {item.get('path')}")

    actual_indexes = {
        path.relative_to(root).as_posix()
        for path in (root / "index/channels").glob("*.json")
    } if (root / "index/channels").exists() else set()
    if actual_indexes != declared_indexes:
        raise PreviewError("channel index inventory mismatch")

    return {
        "manifest_sha256": _sha256(manifest_raw),
        "months": month_count,
        "channel_indexes": len(manifest["channel_indexes"]),
        "videos": video_count,
        "local_readback": "PASS",
    }


def build_pilot_tree(
    source_v1: str | Path,
    target_v1: str | Path,
    *,
    max_channel_indexes: int = 5,
) -> dict:
    source_root, _, manifest = _load_manifest(source_v1)
    target_root = Path(target_v1).expanduser().resolve()
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True)

    current_month = manifest["current_month"]
    current_item = next(
        (
            item
            for item in manifest["months"]
            if isinstance(item, dict)
            and item.get("path") == f"youtube/v1/current/{current_month}.json"
        ),
        None,
    )
    archive_items = sorted(
        [
            item
            for item in manifest["months"]
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and "/archive/" in item["path"]
        ],
        key=lambda item: item["path"],
    )
    selected_months = []
    if archive_items:
        selected_months.append(archive_items[-1])
    if current_item is not None:
        selected_months.append(current_item)
    if not selected_months:
        raise PreviewError("pilot selection found no month objects")

    selected_month_names = {
        Path(item["path"]).stem
        for item in selected_months
    }
    pilot_month_entries = []
    for item in selected_months:
        rel = _relative_logical(item["path"])
        raw = (source_root / rel).read_bytes()
        _verify_declared(raw, item, label=f"pilot month {item['path']}")
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        pilot_month_entries.append(dict(item))

    pilot_index_entries = []
    index_candidates = []
    for item in sorted(
        manifest["channel_indexes"],
        key=lambda entry: entry.get("channel_id", "") if isinstance(entry, dict) else "",
    ):
        if not isinstance(item, dict):
            continue
        rel = _relative_logical(item["path"])
        payload = _json_object(
            (source_root / rel).read_bytes(),
            label=f"pilot source index {item['path']}",
        )
        filtered = {
            month: ids
            for month, ids in (payload.get("months") or {}).items()
            if month in selected_month_names and isinstance(ids, list) and ids
        }
        if not filtered:
            continue
        index_candidates.append((item, filtered))
        if len(index_candidates) >= max_channel_indexes:
            break

    if not index_candidates:
        raise PreviewError("pilot selection found no channel indexes")

    for item, filtered in index_candidates:
        channel_id = item["channel_id"]
        pilot_payload = {
            "schema_version": 1,
            "channel_id": channel_id,
            "months": filtered,
        }
        raw = json.dumps(
            pilot_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        rel = Path("index/channels") / f"{channel_id}.json"
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        pilot_index_entries.append({
            "channel_id": channel_id,
            "path": f"youtube/v1/{rel.as_posix()}",
            "bytes": len(raw),
            "sha256": _sha256(raw),
            "video_count": sum(len(ids) for ids in filtered.values()),
        })

    pilot_manifest = {
        "schema_version": 1,
        "current_month": current_month,
        "months": pilot_month_entries,
        "channel_indexes": pilot_index_entries,
        "channel_index": "youtube/v1/index/channels/<channel_id>.json",
    }
    (target_root / "manifest.json").write_text(
        json.dumps(
            pilot_manifest,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    verified = verify_local_tree(target_root)
    return {
        **verified,
        "pilot": True,
        "selected_months": sorted(selected_month_names),
        "selected_channel_indexes": len(pilot_index_entries),
        "http_request_budget": 1 + len(pilot_month_entries) + len(pilot_index_entries),
    }


def stage_site(
    source_site: str | Path,
    source_v1: str | Path,
    target_site: str | Path,
) -> dict:
    source_site_path = Path(source_site).expanduser().resolve()
    source_v1_path = Path(source_v1).expanduser().resolve()
    target = Path(target_site).expanduser().resolve()

    verify = verify_local_tree(source_v1_path)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source_site_path, target)

    youtube = target / "youtube"
    if youtube.exists():
        shutil.rmtree(youtube)
    (target / "youtube").mkdir(parents=True)
    shutil.copytree(source_v1_path, target / "youtube/v1")

    staged = verify_local_tree(target / "youtube/v1")
    if staged != verify:
        raise PreviewError("staged tree differs from accepted local tree")
    return staged


def write_preview_config(
    source_config: str | Path,
    output_config: str | Path,
    staged_site: str | Path,
) -> dict:
    source = Path(source_config).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("name") != "holoviewer-public":
        raise PreviewError("unexpected Worker name")
    assets = payload.get("assets")
    if not isinstance(assets, dict):
        raise PreviewError("authoritative config has no assets block")

    staged = Path(staged_site).expanduser().resolve()
    out = dict(payload)
    out["assets"] = dict(assets)
    out["assets"]["directory"] = str(staged)
    # Do not mutate routes/workers_dev/preview settings. versions upload creates
    # an inert Worker version only; triggers remain untouched unless separately
    # deployed with a trigger/deployment command.
    target = Path(output_config).expanduser().resolve()
    target.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out


def _http_get(
    url: str,
    *,
    opener=urlopen,
    timeout: int = 10,
    attempts: int = 2,
) -> bytes:
    request = Request(
        url,
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "HoloViewer-Issue448-Preview/1",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.25 * attempt)
    raise PreviewError(
        f"HTTP GET failed after {attempts} attempt(s): {url}: {last_error}"
    )


def _remote_url(base_url: str, logical_path: str, nonce: str) -> str:
    rel = "/".join(quote(part, safe="") for part in logical_path.split("/"))
    return f"{base_url.rstrip('/')}/{rel}?issue448={quote(nonce, safe='')}"


def _load_baseline_manifest(path: str | Path | None) -> dict | None:
    if not path:
        return None
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_file():
        raise PreviewError(f"baseline manifest missing: {candidate}")
    payload = _json_object(candidate.read_bytes(), label="baseline manifest")
    if payload.get("schema_version") != 1:
        raise PreviewError("baseline manifest schema mismatch")
    return payload


def _changed_entries(current: list[dict], baseline: list[dict] | None) -> list[dict]:
    if baseline is None:
        return list(current)
    previous = {
        item.get("path"): item
        for item in baseline
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    changed = []
    for item in current:
        old = previous.get(item.get("path"))
        if old is None or any(
            old.get(key) != item.get(key)
            for key in ("sha256", "bytes", "count", "channel_id", "video_count")
        ):
            changed.append(item)
    return changed


def verify_http_tree(
    base_url: str,
    v1_root: str | Path,
    *,
    nonce: str = "readback",
    opener=urlopen,
    baseline_manifest: str | Path | None = None,
    workers: int = 12,
    progress: bool = True,
) -> dict:
    _, local_manifest_raw, manifest = _load_manifest(v1_root)
    baseline = _load_baseline_manifest(baseline_manifest)

    manifest_url = _remote_url(base_url, "youtube/v1/manifest.json", nonce)
    remote_manifest_raw = _http_get(manifest_url, opener=opener)
    if remote_manifest_raw != local_manifest_raw:
        raise PreviewError("remote manifest bytes differ from accepted local manifest")
    remote_manifest = _json_object(remote_manifest_raw, label="remote manifest")
    if remote_manifest != manifest:
        raise PreviewError("remote manifest semantic mismatch")

    months = _changed_entries(
        manifest["months"],
        baseline.get("months") if baseline is not None else None,
    )
    indexes = _changed_entries(
        manifest["channel_indexes"],
        baseline.get("channel_indexes") if baseline is not None else None,
    )
    mode = "DELTA" if baseline is not None else "FULL"

    def verify_one(kind: str, item: dict) -> tuple[str, str]:
        logical = item["path"]
        raw = _http_get(_remote_url(base_url, logical, nonce), opener=opener)
        _verify_declared(raw, item, label=f"remote {kind} {logical}")
        payload = _json_object(raw, label=f"remote {kind} {logical}")
        if payload.get("schema_version") != 1:
            raise PreviewError(f"remote {kind} schema mismatch: {logical}")
        if kind == "month":
            videos = payload.get("videos")
            if not isinstance(videos, list) or len(videos) != item.get("count"):
                raise PreviewError(f"remote month count mismatch: {logical}")
        else:
            if payload.get("channel_id") != item.get("channel_id"):
                raise PreviewError(f"remote index channel_id mismatch: {logical}")
            month_map = payload.get("months")
            if not isinstance(month_map, dict) or any(
                not isinstance(ids, list) for ids in month_map.values()
            ):
                raise PreviewError(f"remote index months invalid: {logical}")
            if sum(len(ids) for ids in month_map.values()) != item.get("video_count"):
                raise PreviewError(f"remote index video_count mismatch: {logical}")
        return kind, logical

    tasks = [("month", item) for item in months] + [
        ("index", item) for item in indexes
    ]
    total = len(tasks)
    worker_count = max(1, min(workers, total or 1))
    if progress:
        print(
            f"READBACK_MODE={mode} MANIFEST=1 "
            f"MONTHS={len(months)}/{len(manifest['months'])} "
            f"INDEXES={len(indexes)}/{len(manifest['channel_indexes'])} "
            f"WORKERS={worker_count}",
            flush=True,
        )

    completed = 0
    if tasks:
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(verify_one, kind, item): (kind, item["path"])
                for kind, item in tasks
            }
            for future in as_completed(futures):
                kind, logical = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    raise PreviewError(
                        f"{kind} readback failed: {logical}: {exc}"
                    ) from exc
                completed += 1
                if progress and (completed == total or completed % 10 == 0):
                    print(f"READBACK_PROGRESS={completed}/{total}", flush=True)

    return {
        "manifest_http_readback": "PASS",
        "month_objects_http_readback": "PASS",
        "channel_index_http_readback": "PASS",
        "manifest_sha256": _sha256(remote_manifest_raw),
        "readback_mode": mode,
        "declared_months": len(manifest["months"]),
        "declared_channel_indexes": len(manifest["channel_indexes"]),
        "checked_months": len(months),
        "checked_channel_indexes": len(indexes),
        "http_requests": 1 + total,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Issue #448 Static Assets Version URL pilot helper"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-local")
    check.add_argument("--v1", required=True)

    stage = sub.add_parser("stage")
    stage.add_argument("--source-site", required=True)
    stage.add_argument("--source-v1", required=True)
    stage.add_argument("--target-site", required=True)

    pilot = sub.add_parser("stage-pilot")
    pilot.add_argument("--source-site", required=True)
    pilot.add_argument("--source-v1", required=True)
    pilot.add_argument("--target-site", required=True)
    pilot.add_argument("--max-channel-indexes", type=int, default=5)

    config = sub.add_parser("write-config")
    config.add_argument("--source-config", required=True)
    config.add_argument("--output-config", required=True)
    config.add_argument("--staged-site", required=True)

    http = sub.add_parser("verify-http")
    http.add_argument("--base-url", required=True)
    http.add_argument("--v1", required=True)
    http.add_argument("--nonce", default="readback")
    http.add_argument("--baseline-manifest")
    http.add_argument("--workers", type=int, default=12)

    args = parser.parse_args(argv)
    if args.command == "check-local":
        result = verify_local_tree(args.v1)
    elif args.command == "stage":
        result = stage_site(args.source_site, args.source_v1, args.target_site)
    elif args.command == "stage-pilot":
        target_site = Path(args.target_site).expanduser().resolve()
        source_site = Path(args.source_site).expanduser().resolve()
        if target_site.exists():
            shutil.rmtree(target_site)
        shutil.copytree(source_site, target_site)
        youtube = target_site / "youtube"
        if youtube.exists():
            shutil.rmtree(youtube)
        (target_site / "youtube").mkdir(parents=True)
        result = build_pilot_tree(
            args.source_v1,
            target_site / "youtube/v1",
            max_channel_indexes=args.max_channel_indexes,
        )
    elif args.command == "write-config":
        result = write_preview_config(
            args.source_config, args.output_config, args.staged_site
        )
    else:
        result = verify_http_tree(
            args.base_url,
            args.v1,
            nonce=args.nonce,
            baseline_manifest=args.baseline_manifest,
            workers=args.workers,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
