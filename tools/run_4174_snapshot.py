#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = (ROOT / "vendor" / "4174-a144bb3").resolve()
MANIFEST = ROOT / "provenance" / "4174-source-manifest.json"
MODULE_INDEX = ROOT / "provenance" / "4174-source-module-index.json"
SOURCE_COMMIT = "a144bb378a8bdd772faa867d608c1e7491253883"


def git_head() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def load_manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("source_commit") != SOURCE_COMMIT:
        raise RuntimeError("manifest source commit mismatch")
    return data


def snapshot_signature(manifest: dict) -> dict[str, str]:
    sig: dict[str, str] = {}
    for entry in manifest.get("product_files", []):
        rel = entry.get("path")
        if not isinstance(rel, str):
            continue
        path = VENDOR / rel
        if not path.is_file():
            raise RuntimeError(f"manifested source file missing at runtime: {rel}")
        sig[rel] = git_blob_sha(path.read_bytes())
    return sig


def verify_snapshot_unchanged(before: dict[str, str]) -> None:
    after_manifest = load_manifest()
    after = snapshot_signature(after_manifest)
    if before != after:
        changed = sorted(set(before) | set(after))
        diffs = [rel for rel in changed if before.get(rel) != after.get(rel)]
        raise RuntimeError(
            "vendored source snapshot changed during runtime: " + ", ".join(diffs)
        )

    actual = {
        str(path.relative_to(VENDOR))
        for path in VENDOR.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    }
    expected = set(before)
    extra = sorted(actual - expected)
    if extra:
        raise RuntimeError(
            "generated/unmanifested file appeared inside vendored snapshot: "
            + ", ".join(extra)
        )


def isolate_sys_path() -> None:
    prefixes = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    safe = [str(VENDOR)]
    for raw in list(sys.path):
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if any(under(resolved, prefix) for prefix in prefixes):
            value = str(resolved)
            if value not in safe:
                safe.append(value)
    sys.path[:] = safe


def load_product_roots() -> set[str]:
    data = json.loads(MODULE_INDEX.read_text(encoding="utf-8"))
    if data.get("source_commit") != SOURCE_COMMIT:
        raise RuntimeError("module index source commit mismatch")
    roots: set[str] = set()
    for rel in data.get("python_paths", []):
        p = Path(rel)
        roots.add(p.parts[0] if len(p.parts) > 1 else p.stem)
    return roots


def load_manifest_paths(manifest: dict) -> set[str]:
    return {
        entry["path"]
        for entry in manifest.get("product_files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }


def audit_loaded_modules(product_roots: set[str], manifest_paths: set[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    escaped: list[str] = []

    for name, module in sorted(sys.modules.items()):
        if name.split(".", 1)[0] not in product_roots:
            continue
        file_name = getattr(module, "__file__", None)
        if not file_name:
            continue
        resolved = Path(file_name).resolve()
        if not under(resolved, VENDOR):
            escaped.append(f"{name} -> {resolved}")
            continue
        rel = str(resolved.relative_to(VENDOR))
        if rel.endswith(".pyc"):
            rel = rel.replace("__pycache__/", "")
            rel = rel.split(".cpython-", 1)[0] + ".py"
        if rel not in manifest_paths:
            escaped.append(f"{name} -> unmanifested {rel}")
            continue
        rows.append({"module": name, "file": str(resolved), "manifest_path": rel})

    if escaped:
        raise RuntimeError(
            "product module resolution escaped the vendored manifest:\n"
            + "\n".join(escaped)
        )
    return rows


def asset_rows(manifest_paths: set[str]) -> list[dict[str, str]]:
    required = [
        "public/ptt_timeline.js",
        "public/ptt_player_adapter.js",
        "public/ptt_worker_adapter.js",
        "hololive_channels.prototype.json",
    ]
    rows: list[dict[str, str]] = []
    for rel in required:
        if rel not in manifest_paths:
            raise RuntimeError(f"required asset is not manifested: {rel}")
        path = (VENDOR / rel).resolve()
        if not under(path, VENDOR) or not path.is_file():
            raise RuntimeError(f"required asset does not resolve inside snapshot: {rel}")
        rows.append({
            "manifest_path": rel,
            "file": str(path),
            "sha256": file_sha256(path),
        })
    return rows


def validate_runtime_data_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == VENDOR or under(resolved, VENDOR):
        raise RuntimeError(
            f"runtime-data root must be outside vendored code root: {resolved}"
        )
    if under(VENDOR, resolved):
        raise RuntimeError(
            f"runtime-data root must not contain vendored code root: {resolved}"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def print_provenance(
    runtime_data_root: Path,
    module_rows: list[dict[str, str]],
    assets: list[dict[str, str]],
) -> None:
    report = {
        "migration_head": git_head(),
        "pinned_4174_source": SOURCE_COMMIT,
        "cwd": str(Path.cwd()),
        "python_executable": sys.executable,
        "sys_path": list(sys.path),
        "code_root": str(VENDOR),
        "runtime_data_root": str(runtime_data_root),
        "today_refresh_disabled": os.environ.get("PTT_CLIENT_DISABLE_TODAY_REFRESH") == "1",
        "loaded_product_modules": module_rows,
        "static_assets": assets,
    }
    print("=== 8788 RUNTIME PROVENANCE ===")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print("=== END RUNTIME PROVENANCE ===")


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated 4174 snapshot runner")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--runtime-data-root", required=True)
    args = parser.parse_args()

    runtime_data_root = validate_runtime_data_root(Path(args.runtime_data_root))

    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PTT_CLIENT_DISABLE_TODAY_REFRESH"] = "1"

    isolate_sys_path()
    if str(runtime_data_root) in sys.path:
        raise RuntimeError("runtime-data root must never be present in sys.path")

    manifest = load_manifest()
    before_signature = snapshot_signature(manifest)

    os.chdir(VENDOR)
    product_roots = load_product_roots()
    manifest_paths = load_manifest_paths(manifest)

    client_app = importlib.import_module("client_app")
    module_rows = audit_loaded_modules(product_roots, manifest_paths)
    assets = asset_rows(manifest_paths)
    print_provenance(runtime_data_root, module_rows, assets)

    sys.argv = [
        str(VENDOR / "client_app.py"),
        "--host", "127.0.0.1",
        "--port", str(args.port),
        "--runtime-root", str(runtime_data_root),
    ]

    try:
        result = int(client_app.main())
    finally:
        verify_snapshot_unchanged(before_signature)
        print("PASS: vendored source snapshot unchanged after runtime")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
