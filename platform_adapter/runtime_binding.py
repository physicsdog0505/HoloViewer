"""Explicit opt-in runtime binding of accepted 4174 data entry functions.

The imported vendor modules remain byte-identical. Do not use this in the
Checkpoint-3 parity harness; the baseline there is intentionally offline.
"""
from __future__ import annotations

from typing import Any
from http import HTTPStatus
from html import escape

from platform_adapter.product_bindings import bind_home_reader, bind_history_reader
from platform_adapter.public_api import PublicAPI, PublicAPIUnavailable


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

    # Accepted 4174 collab pages use the same Today stream evidence, but
    # RuntimeCollabEventSource captured the old local loader as a default.
    # Rebind only the provider seam so /collab and /collab/session render
    # the original accepted UI without touching local SQLite in Cloudflare.
    def collab_reader(*args, **kwargs):
        live, upcoming, ended, _unknown = reader()
        return live, upcoming, ended
    client_home.load_collab_event_streams = collab_reader
    client_app.load_collab_event_streams = collab_reader
    # History renderer/pagination remain the accepted 4174 implementation.
    history_reader = bind_history_reader(provider, HomeStream)
    client_app.load_history_day = history_reader
    # The accepted request handler has no external-provider failure branch.
    # Add only a transport-level 503 boundary, without changing product HTML,
    # navigation, PTT reader, player, or successful response code paths.
    original_get = getattr(
        client_app.ClientRequestHandler,
        "_holoviewer_original_do_GET",
        client_app.ClientRequestHandler.do_GET,
    )
    def provider_safe_get(handler):
        try:
            return original_get(handler)
        except PublicAPIUnavailable:
            from urllib.parse import urlsplit
            route = urlsplit(handler.path).path
            if route == "/api/home":
                handler._json({"error": "Public data temporarily unavailable"},
                              HTTPStatus.SERVICE_UNAVAILABLE)
            else:
                handler._html(
                    '<p role="alert">' + escape("正式資料服務暫時無法讀取，請稍後重新整理。") + '</p>',
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
    # Rebinding is idempotent: never wrap an already-wrapped dispatcher.
    client_app.ClientRequestHandler._holoviewer_original_do_GET = original_get
    client_app.ClientRequestHandler.do_GET = provider_safe_get
    return {
        "provider": "holoviewer-public-api",
        "read_today": "/v1/catalog/today",
        "read_day_legacy_compatible": "/v1/history?day=YYYY-MM-DD&limit=50&offset=N",
        "database_binding": "DB -> holoviewer-public-v1 (existing API owns binding)",
    }
