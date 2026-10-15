"""Prepare request-local canonical API payloads before synchronous 4174 rendering.

No product route output, renderer or navigation logic is copied. The only
routing here selects which approved external data entry must be read in advance.
"""
from __future__ import annotations

from datetime import datetime
import json
from urllib.parse import parse_qs, urlencode, urlsplit

from platform_adapter.public_api import DEFAULT_API, PublicAPIUnavailable


async def preload_for_accepted_request(target: str, get_json):
    """Map one accepted request to its canonical API reads.

    get_json(url) is an async injected transport. It must return a JSON dict.
    """
    parsed = urlsplit(target)
    if parsed.path in {"/", "/api/home", "/custom-view", "/custom-view/session"}:
        value = await get_json(DEFAULT_API + "/v1/catalog/today")
        if not isinstance(value, dict):
            raise PublicAPIUnavailable("Invalid Today envelope")
        return {("/v1/catalog/today", ()): value}
    # /v1/history remains a legacy compatibility API read per #45.\n    if parsed.path != "/history":
        return {}

    # Use accepted date and bounds rules, never duplicate date semantics.
    from frontend_time import TAIPEI
    from client_history import parse_history_day, history_day_bounds

    now = datetime.now(TAIPEI)
    _, default_day = history_day_bounds(now)
    query = parse_qs(parsed.query)
    try:
        selected = parse_history_day(query.get("date", [default_day.isoformat()])[0], now=now)
        page = int(query.get("page", ["1"])[0])
    except (ValueError, OverflowError):
        return {}  # accepted handler itself produces its 400 error
    if page < 1 or page > 10000:
        return {}
    params = {"day": selected.isoformat(), "limit": "50", "offset": str((page - 1) * 50)}
    value = await get_json(DEFAULT_API + "/v1/history?" + urlencode(params))
    if not isinstance(value, dict):
        raise PublicAPIUnavailable("Invalid History envelope")
    return {("/v1/history", tuple(sorted(params.items()))): value}

async def fetch_canonical_json(url: str, *, api_service=None) -> dict:
    """Pyodide HTTP adapter; never performs synchronous urllib in a Worker."""
    if not url.startswith(DEFAULT_API + "/"):
        raise PublicAPIUnavailable("Non-canonical Public API URL rejected")
    try:
        if api_service is not None:
            # ServiceBinding.fetch returns a JS Response proxy; JSON text parsing
            # avoids passing JS object proxies into Python consumer contracts.
            response = await api_service.fetch(url)
            if response.status != 200:
                raise PublicAPIUnavailable("Canonical Public API HTTP error")
            data = json.loads(str(await response.text()))
        else:
            from pyodide.http import pyfetch
            response = await pyfetch(url, method="GET", headers={"Accept": "application/json"})
            if response.status != 200:
                raise PublicAPIUnavailable("Canonical Public API HTTP error")
            data = await response.json()
    except PublicAPIUnavailable:
        raise
    except Exception as exc:
        raise PublicAPIUnavailable("Canonical Public API fetch failed") from exc
    if not isinstance(data, dict):
        raise PublicAPIUnavailable("Invalid Public API JSON")
    return data
