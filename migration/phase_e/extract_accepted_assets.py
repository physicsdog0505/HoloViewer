#!/usr/bin/env python3
"""Extract accepted 4174 literal UI assets for an isolated static-shell build.

No Python product code is imported or executed, and no private runtime data,
SQLite, credentials or generated HTML records are copied.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "vendor" / "4174-a144bb3"
ASSETS = {
    "client_ui_shell.py": {
        "CLIENT_CSS": "client-shell.css",
        "LIVE_RAIL_CSS": "client-rail.css",
        "CLIENT_JS": "client-shell.js",
    },
    "client_custom_view.py": {
        "CUSTOM_CSS": "custom-view.css",
        "CUSTOM_JS": "custom-view.js",
    },
}


def literal_constants(source: Path) -> dict[str, str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            found[target.id] = node.value.value
    return found


def build(output: Path) -> dict:
    if not SOURCE.is_dir():
        raise RuntimeError("pinned 4174 vendor source missing")
    if output.resolve() == SOURCE.resolve() or SOURCE.resolve() in output.resolve().parents:
        raise ValueError("output may not be inside pinned source")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for module, mapping in ASSETS.items():
        constants = literal_constants(SOURCE / module)
        for name, target in mapping.items():
            if name not in constants:
                raise RuntimeError(f"accepted literal {module}:{name} missing")
            contents = constants[name]
            path = output / target
            path.write_text(contents + "\n", encoding="utf-8")
            records.append({
                "source": module, "constant": name, "output": target,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
    manifest = {"source_commit": "a144bb378a8bdd772faa867d608c1e7491253883",
                "asset_count": len(records), "assets": records}
    (output / "accepted-asset-provenance.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="build/8788-phase-e-assets")
    args = p.parse_args()
    result = build(Path(args.output))
    print(f"Extracted {result['asset_count']} accepted UI assets to {args.output}")


if __name__ == "__main__":
    main()
