"""Request-local Today support-color binding for accepted 4174 renderers."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CURRENT = ContextVar("holoviewer_support_styles", default=None)


def extract_support_styles(payload: dict) -> dict[str, dict]:
    rows = payload.get("streams", payload.get("items"))
    if not isinstance(rows, list):
        return {}
    styles: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel_id = str(row.get("channel_id") or "")
        if not channel_id:
            continue
        mode = str(row.get("support_mode") or "neutral")
        accent = row.get("member_accent")
        dual = row.get("member_accent_dual")
        if mode == "dual_color" and isinstance(dual, list) and len(dual) == 2 and all(isinstance(v, str) and HEX.fullmatch(v) for v in dual):
            styles[channel_id] = {"mode": "dual_color", "hexes": tuple(v.upper() for v in dual)}
        elif mode == "solid" and isinstance(accent, str) and HEX.fullmatch(accent):
            styles[channel_id] = {"mode": "solid", "hexes": (accent.upper(),)}
        else:
            styles[channel_id] = {"mode": "neutral", "hexes": ()}
    return styles


def install_support_style_adapter(client_home) -> None:
    if getattr(client_home, "_holoviewer_api_style_installed", False):
        return
    original = client_home._channel_style

    def channel_style(item):
        styles = _CURRENT.get()
        if styles is not None and item.channel_id in styles:
            entry = styles[item.channel_id]
            if entry["mode"] == "dual_color":
                left, right = entry["hexes"]
                return (
                    f' style="--member-accent:{left};'
                    f'--member-accent-dual:linear-gradient(90deg,{left} 0%,{left} 50%,{right} 50%,{right} 100%)"'
                    ' data-support-mode="dual_color" title="2025 6th Fes 社群應援色（非官方永久代表色）"'
                )
            if entry["mode"] == "solid":
                return f' style="--member-accent:{entry["hexes"][0]}"'
            return ""
        return original(item)

    client_home._channel_style = channel_style
    client_home._holoviewer_api_style_installed = True


@contextmanager
def using_support_styles(styles: dict[str, dict]):
    token = _CURRENT.set(styles)
    try:
        yield
    finally:
        _CURRENT.reset(token)
