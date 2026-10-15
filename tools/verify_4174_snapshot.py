#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "4174-a144bb3"
MANIFEST = ROOT / "provenance" / "4174-source-manifest.json"
MODULE_INDEX = ROOT / "provenance" / "4174-source-module-index.json"
EXPECTED_SOURCE = "a144bb378a8bdd772faa867d608c1e7491253883"
FAILED_BRANCHES = {"dev/8788-parity", "dev/8788-clean-transplant"}

def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()

def fail(messages: list[str]) -> int:
    for message in messages:
        print("FAIL:", message, file=sys.stderr)
    return 1

def main() -> int:
    errors: list[str] = []
    if not VENDOR.is_dir():
        return fail([f"missing vendored snapshot: {VENDOR}"])

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    module_index = json.loads(MODULE_INDEX.read_text(encoding="utf-8"))
    if manifest.get("source_commit") != EXPECTED_SOURCE:
        errors.append("manifest source commit is not pinned a144bb3")
    if module_index.get("source_commit") != EXPECTED_SOURCE:
        errors.append("module index source commit is not pinned a144bb3")

    expected = {entry["path"]: entry for entry in manifest.get("files", [])}
    actual = {
        str(path.relative_to(VENDOR))
        for path in VENDOR.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    if missing:
        errors.append("manifest files missing: " + ", ".join(missing))
    if extra:
        errors.append("unmanifested files inside snapshot: " + ", ".join(extra))

    for rel, entry in expected.items():
        path = VENDOR / rel
        if not path.is_file():
            continue
        observed = git_blob_sha(path.read_bytes())
        if observed != entry.get("blob_sha"):
            errors.append(f"blob mismatch {rel}: {observed} != {entry.get('blob_sha')}")

    source_roots: set[str] = set()
    for rel in module_index.get("python_paths", []):
        p = Path(rel)
        source_roots.add(p.parts[0] if len(p.parts) > 1 else p.stem)

    vendored_roots: set[str] = set()
    for rel in actual:
        p = Path(rel)
        if p.suffix != ".py":
            continue
        vendored_roots.add(p.parts[0] if len(p.parts) > 1 else p.stem)

    missing_imports: dict[str, set[str]] = {}
    for rel in sorted(actual):
        path = VENDOR / rel
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            errors.append(f"syntax error in {rel}: {exc}")
            continue
        needed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                needed.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                needed.add(node.module.split(".", 1)[0])
        absent = sorted(name for name in needed if name in source_roots and name not in vendored_roots)
        if absent:
            missing_imports[rel] = set(absent)
    for rel, names in sorted(missing_imports.items()):
        errors.append(f"local import escapes snapshot in {rel}: {', '.join(sorted(names))}")

    forbidden = [
        ROOT / "site",
        ROOT / "cloudflare",
        ROOT / "app.py",
        ROOT / "public_snapshot.py",
        ROOT / "scripts" / "start_public_local.sh",
    ]
    for path in forbidden:
        if path.exists():
            errors.append(f"legacy Public residue present: {path.relative_to(ROOT)}")

    try:
        branch = subprocess.check_output(
            ["git", "-C", str(ROOT), "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if branch in FAILED_BRANCHES:
            errors.append(f"refusing failed migration branch: {branch}")
    except (OSError, subprocess.CalledProcessError):
        pass

    if errors:
        return fail(errors)

    print(f"PASS: 4174 snapshot pinned to {EXPECTED_SOURCE}")
    print(f"PASS: {len(expected)} manifested files are byte-identical Git blobs")
    print("PASS: local import closure resolves inside vendor/4174-a144bb3")
    print("PASS: no legacy Public product tree detected")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
