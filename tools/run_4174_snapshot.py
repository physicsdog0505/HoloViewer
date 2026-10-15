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


def load_manifest_paths() -> set[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("source_commit") != SOURCE_COMMIT:
        raise RuntimeError("manifest source commit mismatch")
    return {
        entry["path"]
        for entry in data.get("product_files", [])
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


def print_provenance(module_rows: list[dict[str, str]], assets: list[dict[str, str]]) -> None:
    report = {
        "migration_head": git_head(),
        "pinned_4174_source": SOURCE_COMMIT,
        "cwd": str(Path.cwd()),
        "python_executable": sys.executable,
        "sys_path": list(sys.path),
        "runtime_root": str(VENDOR),
        "loaded_product_modules": module_rows,
        "static_assets": assets,
    }
    print("=== 8788 RUNTIME PROVENANCE ===")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    print("=== END RUNTIME PROVENANCE ===")


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated 4174 snapshot runner")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()

    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONNOUSERSITE"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    isolate_sys_path()
    os.chdir(VENDOR)

    product_roots = load_product_roots()
    manifest_paths = load_manifest_paths()

    client_app = importlib.import_module("client_app")
    module_rows = audit_loaded_modules(product_roots, manifest_paths)
    assets = asset_rows(manifest_paths)
    print_provenance(module_rows, assets)

    # Checkpoint 2 deliberately uses the vendored snapshot itself as runtime root.
    # External owner data is not required to prove code/static isolation.
    sys.argv = [
        str(VENDOR / "client_app.py"),
        "--host", "127.0.0.1",
        "--port", str(args.port),
        "--runtime-root", str(VENDOR),
    ]
    return int(client_app.main())


if __name__ == "__main__":
    raise SystemExit(main())
