#!/usr/bin/env python3
"""Build a disposable Python Worker feasibility bundle from pinned 4174 blobs.

This is source packaging only. It never deploys, writes to D1, starts servers,
or copies product logic from rejected branches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "4174-a144bb3"
MANIFEST = ROOT / "provenance" / "4174-source-manifest.json"
PINNED = "a144bb378a8bdd772faa867d608c1e7491253883"


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def build(output: Path) -> dict:
    if output.exists():
        raise ValueError("Worker feasibility output must be a new directory")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("source_commit") != PINNED:
        raise RuntimeError("source manifest pin mismatch")
    entries = manifest.get("product_files")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("product manifest is empty")

    output.mkdir(parents=True, exist_ok=False)
    copied = []
    for entry in entries:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("unsafe product path")
        source = (VENDOR / relative).resolve()
        if not source.is_file() or not source.is_relative_to(VENDOR.resolve()):
            raise RuntimeError("missing or escaped vendored source")
        data = source.read_bytes()
        if blob_sha(data) != entry["source_blob_sha"]:
            raise RuntimeError("vendored source blob mismatch: " + str(relative))
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        copied.append(str(relative))

    adapter = output / "platform_adapter"
    shutil.copytree(ROOT / "platform_adapter", adapter, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (output / "entry.py").write_text(
        "from platform_adapter.cloudflare_entry import Default\n", encoding="utf-8"
    )
    # Source-only local Worker setup, using the same Python Worker/runtime
    # interface as Cloudflare; does not create or deploy a second backend.
    (output / "wrangler.jsonc").write_text(json.dumps({
        "name": "holoviewer-8788-local-feasibility",
        "main": "entry.py",
        "compatibility_date": "2026-10-15",
        "compatibility_flags": ["python_workers"],
    }, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "pinned_source": PINNED,
        "verified_product_files": len(copied),
        "entrypoint": "entry.py",
        "deployed": False,
        "tested_on_pyodide": False,
    }
    (output / "bundle-provenance.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="new disposable output directory")
    args = parser.parse_args()
    target = Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix="hv-python-worker-")).resolve() / "bundle"
    receipt = build(target)
    print(json.dumps({"bundle_path": str(target), **receipt}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
