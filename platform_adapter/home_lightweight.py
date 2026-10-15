"""Lightweight Home dispatcher for Cloudflare Python Workers.

Uses the accepted 4174 Home builders without importing the full client_app graph.
"""
from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import urlsplit

from platform_adapter.product_bindings import home_groups_from_payload
from platform_adapter.public_api import DEFAULT_API, PublicAPI
from platform_adapter.support_style_binding import (
    extract_support_styles,
    install_support_style_adapter,
    using_support_styles,
)
from platform_adapter.worker_transport import TransportResponse


def build_request_live_rail() -> str:
    """Render the accepted live rail from the request-local preloaded Today payload."""
    import client_home

    install_support_style_adapter(client_home)
    payload = PublicAPI(DEFAULT_API).read_today()
    live, _upcoming, _ended, _unknown = home_groups_from_payload(
        payload, client_home.HomeStream
    )
    styles = extract_support_styles(payload)
    with using_support_styles(styles):
        return client_home._live_channel_rail(live)


def dispatch_lightweight_home(target: str) -> TransportResponse:
    parsed = urlsplit(target)
    if parsed.path not in {"/", "/api/home"}:
        raise ValueError("not a lightweight Home route")

    import client_home
    from frontend_time import TAIPEI

    install_support_style_adapter(client_home)
    payload = PublicAPI(DEFAULT_API).read_today()
    live, upcoming, ended, unknown = home_groups_from_payload(
        payload, client_home.HomeStream
    )
    styles = extract_support_styles(payload)
    now = datetime.now(TAIPEI)
    today_label = now.strftime("%Y/%m/%d")

    with using_support_styles(styles):
        if parsed.path == "/":
            body = client_home.build_home_html(
                live, upcoming, ended, unknown, today_label=today_label
            ).encode("utf-8")
            return TransportResponse(
                200,
                (("Content-Type", "text/html; charset=utf-8"),
                 ("Cache-Control", "no-store")),
                body,
            )

        fragment = client_home.build_home_fragment(
            live, upcoming, ended, unknown, today_label=today_label
        )
        body = json.dumps(
            {"today_label": today_label, "html": fragment},
            ensure_ascii=False,
        ).encode("utf-8")
        return TransportResponse(
            200,
            (("Content-Type", "application/json; charset=utf-8"),
             ("Cache-Control", "no-store")),
            body,
        )
