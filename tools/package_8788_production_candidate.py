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
import re
if __package__:
    from .build_python_worker_bundle import build
else:
    from build_python_worker_bundle import build

TARGET = "holoviewer-public"
PINNED = "a144bb378a8bdd772faa867d608c1e7491253883"
ASSETS = ("ptt_timeline.js", "ptt_player_adapter.js", "ptt_worker_adapter.js",
          "hololive_channels.prototype.json")
SUPPORT_COLOR_EXPORT = "holoviewer-channel-support-colors.json"
CHANNEL_ID = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")

def validate_support_color_export(source: Path) -> dict:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise RuntimeError("verified support-color export unreadable") from exc
    if payload.get("schema_version") != 1 or payload.get("fallback") != "neutral":
        raise RuntimeError("verified support-color export schema mismatch")
    rows = payload.get("channels")
    if not isinstance(rows, list) or len(rows) != 66:
        raise RuntimeError("verified support-color export must contain exactly 66 rows")
    seen = set()
    colored = neutral = dual = 0
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("invalid support-color row")
        channel_id = row.get("channel_id")
        if not isinstance(channel_id, str) or not CHANNEL_ID.fullmatch(channel_id) or channel_id in seen:
            raise RuntimeError("invalid/duplicate support-color channel_id")
        seen.add(channel_id)
        mode = row.get("display_mode")
        if mode == "neutral":
            neutral += 1
            continue
        if mode == "dual_color":
            values = row.get("color_hexes")
            if not (isinstance(values, list) and len(values) == 2 and
                    all(isinstance(v, str) and HEX.fullmatch(v) for v in values)):
                raise RuntimeError("invalid dual support color")
            dual += 1
            colored += 1
            continue
        if mode == "solid":
            value = row.get("color_hex")
            if not isinstance(value, str) or not HEX.fullmatch(value):
                raise RuntimeError("invalid solid support color")
            colored += 1
            continue
        raise RuntimeError("unsupported support-color display mode")
    if (colored, neutral, dual) != (57, 9, 1):
        raise RuntimeError("verified support-color receipt mismatch")
    return {
        "rows": len(rows), "colored": colored, "neutral": neutral, "dual": dual,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }

AUTHORIZED_UI_OVERRIDES = {
    "live_channel_rail_clear_navigation": {
        "path": "client_ui_shell.py",
        "old": "position:fixed;left:2px;top:270px;z-index:65;width:64px;max-height:calc(100vh - 282px);",
        "new": "position:fixed;left:2px;top:466px;z-index:65;width:64px;max-height:calc(100vh - 478px);",
    },
}

def apply_authorized_ui_overrides(output: Path) -> dict[str, str]:
    applied = {}
    for name, spec in AUTHORIZED_UI_OVERRIDES.items():
        target = output / spec["path"]
        text = target.read_text(encoding="utf-8")
        old = spec["old"]
        if text.count(old) != 1:
            raise RuntimeError("authorized UI override anchor mismatch: " + name)
        target.write_text(text.replace(old, spec["new"]), encoding="utf-8")
        applied[name] = spec["new"]
    return applied

def package(output: Path, *, support_colors: Path) -> dict:
    support_receipt = validate_support_color_export(support_colors)
    base = build(output)
    if base["pinned_source"] != PINNED:
        raise RuntimeError("accepted source pin changed")
    ui_overrides = apply_authorized_ui_overrides(output)
    shutil.copyfile(support_colors, output / SUPPORT_COLOR_EXPORT)
    if hashlib.sha256((output / SUPPORT_COLOR_EXPORT).read_bytes()).hexdigest() != support_receipt["sha256"]:
        raise RuntimeError("support-color export changed during packaging")
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
        "authorized_ui_overrides": ui_overrides,
        "support_colors": support_receipt,
        "assets": digests, "d1_bindings": [], "worker_deployed": False,
        "production_capability": "limited-route probe; NOT full product acceptance",
        "requires_explicit_owner_deploy_approval": True,
    }
    (output / "bundle-provenance.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--support-colors", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.output.resolve(), support_colors=args.support_colors.resolve()), indent=2))

if __name__ == "__main__":
    main()
