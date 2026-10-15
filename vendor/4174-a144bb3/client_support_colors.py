"""Read-only 4174 consumer for the pinned #338 channel support-color JSON export.

No database reads, name matching, network requests or guessed colors. The producer
is pinned to 631fe4bc; its export is generated separately by the 8501 owner.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
CHANNEL = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
EXPORT_NAME = "holoviewer-channel-support-colors.json"


def load_support_colors(runtime_root: str | Path) -> dict[str, dict]:
    """Return trusted channel-ID indexed view; missing/invalid input stays neutral."""
    source = Path(runtime_root) / EXPORT_NAME
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("fallback") != "neutral":
        return {}
    rows = payload.get("channels")
    if not isinstance(rows, list):
        return {}
    indexed: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel_id = row.get("channel_id")
        if not isinstance(channel_id, str) or not CHANNEL.fullmatch(channel_id) or channel_id in indexed:
            continue
        mode = row.get("display_mode")
        status = row.get("verification_status")
        semantics = row.get("color_semantics")
        if mode == "dual_color" and status == "community" and semantics == "2025_6th_fes_penlight":
            hexes = row.get("color_hexes")
            if (isinstance(hexes, list) and len(hexes) == 2
                    and all(isinstance(v, str) and HEX.fullmatch(v) for v in hexes)):
                indexed[channel_id] = {"mode": "dual_color", "hexes": tuple(c.upper() for c in hexes), "source": "2025 6th Fes community penlight"}
        elif mode == "solid" and status in {"verified", "community"}:
            color = row.get("color_hex")
            if isinstance(color, str) and HEX.fullmatch(color):
                if status == "community" and semantics != "2025_6th_fes_penlight":
                    continue
                indexed[channel_id] = {"mode": "solid", "hexes": (color.upper(),), "source": "2025 6th Fes community penlight" if status == "community" else "verified support color"}
    return indexed


def accent_style(channel_id: str, colors: dict[str, dict]) -> str:
    """CSS custom properties, using only validated HEX; empty means neutral."""
    entry = colors.get(channel_id)
    if not entry:
        return ""
    if entry["mode"] == "dual_color":
        left, right = entry["hexes"]
        return (f' style="--member-accent:{left};'
                f'--member-accent-dual:linear-gradient(90deg,{left} 0%,{left} 50%,{right} 50%,{right} 100%)"'
                f' data-support-mode="dual_color" title="2025 6th Fes 社群應援色（非官方永久代表色）"')
    return f' style="--member-accent:{entry["hexes"][0]}"'
