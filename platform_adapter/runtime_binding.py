"""Explicit opt-in runtime binding of accepted 4174 data entry functions.

The imported vendor modules remain byte-identical. Do not use this in the
Checkpoint-3 parity harness; the baseline there is intentionally offline.
"""
from __future__ import annotations

from typing import Any

from platform_adapter.product_bindings import bind_home_reader, bind_history_reader
from platform_adapter.public_api import PublicAPI


def bind_public_today(client_app: Any, *, api_base: str) -> dict[str, str]:
    """Wire the canonical Public Today reader, without rewriting render logic.

    This is an opt-in platform integration seam, not a production cutover.
    """
    from client_home import HomeStream
    import client_home
    provider = PublicAPI(api_base)
    reader = bind_home_reader(provider, HomeStream)
    client_home.load_home_streams = reader
    client_app.load_home_streams = reader
    # History renderer/pagination remain the accepted 4174 implementation.
    history_reader = bind_history_reader(provider, HomeStream)
    client_app.load_history_day = history_reader
    return {
        "provider": "holoviewer-public-api",
        "read_today": "/v1/catalog/today",
        "read_day": "/v1/history?day=YYYY-MM-DD&limit=50&offset=N",
        "database_binding": "DB -> holoviewer-public-v1 (existing API owns binding)",
    }
