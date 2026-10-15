#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = (ROOT / "vendor" / "4174-a144bb3").resolve()
MODULE_INDEX = ROOT / "provenance" / "4174-source-module-index.json"
SOURCE_COMMIT = "a144bb378a8bdd772faa867d608c1e7491253883"

def under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def source_roots() -> set[str]:
    data = json.loads(MODULE_INDEX.read_text(encoding="utf-8"))
    if data.get("source_commit") != SOURCE_COMMIT:
        raise RuntimeError("source module index is not pinned to a144bb3")
    roots: set[str] = set()
    for rel in data.get("python_paths", []):
        p = Path(rel)
        roots.add(p.parts[0] if len(p.parts) > 1 else p.stem)
    return roots

def isolate_sys_path() -> None:
    prefixes = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
    safe = [str(VENDOR)]
    for raw in sys.path:
        if not raw:
            continue
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        if any(under(resolved, prefix) for prefix in prefixes):
            text = str(resolved)
            if text not in safe:
                safe.append(text)
    sys.path[:] = safe

def audit_loaded_modules(roots: set[str]) -> None:
    escaped: list[str] = []
    for name, module in sorted(sys.modules.items()):
        if name.split(".", 1)[0] not in roots:
            continue
        file_name = getattr(module, "__file__", None)
        if not file_name:
            continue
        try:
            resolved = Path(file_name).resolve()
        except OSError:
            escaped.append(f"{name} -> {file_name}")
            continue
        if not under(resolved, VENDOR):
            escaped.append(f"{name} -> {resolved}")
    if escaped:
        raise RuntimeError(
            "4174 module resolved outside vendored snapshot:\n" + "\n".join(escaped)
        )

def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated runner for pinned 4174 Client")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--runtime-root", required=True)
    args = parser.parse_args()

    runtime_root = Path(args.runtime_root).expanduser().resolve()
    if not runtime_root.is_dir():
        raise SystemExit(f"runtime data root does not exist: {runtime_root}")

    roots = source_roots()
    isolate_sys_path()
    os.chdir(VENDOR)
    os.environ["PTT_CLIENT_RUNTIME_ROOT"] = str(runtime_root)

    client_app = importlib.import_module("client_app")
    audit_loaded_modules(roots)

    print(f"Runtime provenance: {SOURCE_COMMIT}")
    print(f"Code root: {VENDOR}")
    print(f"Runtime data root: {runtime_root}")

    sys.argv = [
        str(VENDOR / "client_app.py"),
        "--host", "127.0.0.1",
        "--port", str(args.port),
        "--runtime-root", str(runtime_root),
    ]
    return int(client_app.main())

if __name__ == "__main__":
    raise SystemExit(main())
