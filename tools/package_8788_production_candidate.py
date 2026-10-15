#!/usr/bin/env python3
"""Package pinned 4174 source for the EXISTING Cloudflare Public Worker.

This is an offline build only; no Cloudflare access or deployment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
if __package__:
    from .build_python_worker_bundle import build
else:
    from build_python_worker_bundle import build

TARGET = "holoviewer-public"
PINNED = "a144bb378a8bdd772faa867d608c1e7491253883"
ASSETS = ("ptt_timeline.js", "ptt_player_adapter.js", "ptt_worker_adapter.js",
          "hololive_channels.prototype.json")

def package(output: Path) -> dict:
    base = build(output)
    if base["pinned_source"] != PINNED:
        raise RuntimeError("accepted source pin changed")
    if (output / "entry_fixture.py").exists():
        raise RuntimeError("fixture entrypoint must never be deployed")
    public = output / "public"
    if not public.is_dir():
        raise RuntimeError("original public asset directory missing")
    source_channels = output / "hololive_channels.prototype.json"
    if not source_channels.is_file():
        raise RuntimeError("accepted channel metadata missing")
    shutil.copyfile(source_channels, public / source_channels.name)
    digests = {}
    for item in ASSETS:
        source = source_channels if item == source_channels.name else public / item
        destination = public / item
        if not source.is_file() or not destination.is_file():
            raise RuntimeError("missing required asset: " + item)
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        if expected != hashlib.sha256(destination.read_bytes()).hexdigest():
            raise RuntimeError("asset changed: " + item)
        digests[item] = expected
    config = {
        "name": TARGET,
        "main": "entry.py",
        "compatibility_date": "2026-10-15",
        "compatibility_flags": ["python_workers"],
        "services": [{"binding": "PUBLIC_API", "service": "holoviewer-public-api"}],
        "assets": {"directory": "./public", "binding": "ASSETS", "run_worker_first": False},
    }
    (output / "wrangler.jsonc").write_text(json.dumps(config, indent=2) + "\n")
    receipt = {
        **base, "target_worker": TARGET, "runtime": "python_workers",
        "assets": digests, "d1_bindings": [], "worker_deployed": False,
        "production_capability": "limited-route probe; NOT full product acceptance",
        "requires_explicit_owner_deploy_approval": True,
    }
    (output / "bundle-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.output.resolve()), indent=2))

if __name__ == "__main__":
    main()
