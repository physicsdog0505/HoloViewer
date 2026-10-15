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

def apply_runtime_import_optimizations(output: Path) -> dict[str, str]:
    target = output / "client_home.py"
    text = target.read_text(encoding="utf-8")
    eager = """from channel_push_discovery import (
    ChannelPushStore,
    cards_for_day,
    merge_cards,
    statuses_for_day,
)
from client_runtime import client_runtime_root
from client_collab_candidates import CollabCandidate, detect_collab_candidates
from client_support_colors import EXPORT_NAME, accent_style as exported_accent_style, load_support_colors
from client_stream_catalog import load_client_catalog_metadata, load_client_catalog_streams
from client_ui_shell import client_document
from frontend_stream_discovery import build_discovery_cards, hidden_reason
from frontend_time import TAIPEI
from live_stream_discovery import LiveDiscoveryCache
from today_stream_status import load_status_snapshot, stream_state
from youtube_metadata import YoutubeVideo
"""
    slim = """from client_collab_candidates import CollabCandidate, detect_collab_candidates
from client_ui_shell import client_document
from frontend_time import TAIPEI
"""
    if text.count(eager) != 1:
        raise RuntimeError("client_home eager-import anchor mismatch")
    text = text.replace(eager, slim)

    style_old = """def _channel_style(item: HomeStream) -> str:
    \"\"\"Prefer audited channel-ID colors; retain old appearance before export arrives.\"\"\"
    root = client_runtime_root()
    colors = load_support_colors(root)
    if (root / EXPORT_NAME).is_file():
        return exported_accent_style(item.channel_id, colors)
"""
    style_new = """def _channel_style(item: HomeStream) -> str:
    \"\"\"Prefer audited channel-ID colors; retain old appearance before export arrives.\"\"\"
    from client_runtime import client_runtime_root
    from client_support_colors import EXPORT_NAME, accent_style as exported_accent_style, load_support_colors
    root = client_runtime_root()
    colors = load_support_colors(root)
    if (root / EXPORT_NAME).is_file():
        return exported_accent_style(item.channel_id, colors)
"""
    if text.count(style_old) != 1:
        raise RuntimeError("client_home support-color lazy-import anchor mismatch")
    text = text.replace(style_old, style_new)

    display_old = """    durable_state = stream_state(video, now=now)
"""
    display_new = """    from today_stream_status import stream_state
    durable_state = stream_state(video, now=now)
"""
    if text.count(display_old) != 1:
        raise RuntimeError("client_home stream-state lazy-import anchor mismatch")
    text = text.replace(display_old, display_new)

    loader_anchor = '''    current = now or datetime.now(TAIPEI)
'''
    loader_imports = '''    from channel_push_discovery import ChannelPushStore, cards_for_day, merge_cards, statuses_for_day
    from client_runtime import client_runtime_root
    from client_stream_catalog import load_client_catalog_metadata, load_client_catalog_streams
    from frontend_stream_discovery import build_discovery_cards, hidden_reason
    from live_stream_discovery import LiveDiscoveryCache
    from today_stream_status import load_status_snapshot

    current = now or datetime.now(TAIPEI)
'''
    marker = "def load_home_streams("
    start = text.index(marker)
    tail = text[start:]
    if tail.count(loader_anchor) < 1:
        raise RuntimeError("client_home loader lazy-import anchor mismatch")
    tail = tail.replace(loader_anchor, loader_imports, 1)
    text = text[:start] + tail
    target.write_text(text, encoding="utf-8")
    return {"client_home_lazy_runtime_imports": "applied"}


def package(output: Path) -> dict:
    base = build(output)
    if base["pinned_source"] != PINNED:
        raise RuntimeError("accepted source pin changed")
    ui_overrides = apply_authorized_ui_overrides(output)
    runtime_optimizations = apply_runtime_import_optimizations(output)
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
        "runtime_optimizations": runtime_optimizations,
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
