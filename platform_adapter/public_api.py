"""Read-only platform transport for canonical Public API.

Owned by 8788 platform integration. Never imports or alters the pinned product
snapshot. In particular this is NOT a second Today/PTT writer or D1 client.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
import json
import re
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API = "https://holoviewer-public-api.singlebagel.workers.dev"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

_PRELOADED = ContextVar("holoviewer_canonical_api_preload", default=None)


@contextmanager
def preloaded_public_reads(mapping: dict):
    """A Worker request consumes only the canonical async-prefetched reads."""
    token = _PRELOADED.set(dict(mapping))
    try:
        yield
    finally:
        _PRELOADED.reset(token)



class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


_READ_OPENER = urllib.request.build_opener(_NoRedirect)


class PublicAPIUnavailable(RuntimeError):
    """The canonical API could not provide a valid consumer read."""


@dataclass(frozen=True)
class PublicAPI:
    origin: str = DEFAULT_API
    timeout_seconds: float = 8.0
    _test_only_allow_alternate_origin: bool = False

    def __post_init__(self) -> None:
        if self.origin != DEFAULT_API and not self._test_only_allow_alternate_origin:
            raise ValueError("Only the canonical holoviewer-public-api is authorized")
        parsed = urllib.parse.urlsplit(self.origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/")):
            raise ValueError("Public API origin must be an HTTPS origin")

    def _read(self, path: str, *, query: dict[str, str] | None = None) -> dict:
        if not path.startswith("/v1/") or "//" in path:
            raise ValueError("unsupported Public API route")
        preload = _PRELOADED.get()
        if preload is not None:
            key = (path, tuple(sorted((query or {}).items())))
            if key not in preload:
                raise PublicAPIUnavailable("Canonical provider read not preloaded")
            value = preload[key]
            if not isinstance(value, dict):
                raise PublicAPIUnavailable("Invalid preloaded Public API envelope")
            return value

        url = self.origin.rstrip("/") + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url, method="GET", headers={"Accept": "application/json"}
        )
        try:
            with _READ_OPENER.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise PublicAPIUnavailable(f"Public API HTTP {response.status}")
                content_type = response.headers.get_content_type()
                if content_type != "application/json":
                    raise PublicAPIUnavailable("Public API returned non-JSON")
                # Bounded read; no unbounded download of records.
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise PublicAPIUnavailable("Public API response too large")
        except (TimeoutError, OSError, urllib.error.URLError) as exc:
            raise PublicAPIUnavailable("Canonical Public API unavailable") from exc
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PublicAPIUnavailable("Invalid Public API JSON") from exc
        if not isinstance(data, dict):
            raise PublicAPIUnavailable("Expected Public API JSON object")
        return data

    def read_today(self) -> dict:
        """Canonical GET /v1/catalog/today; no lifecycle inference."""
        result = self._read("/v1/catalog/today")
        if not isinstance(result.get("streams", result.get("items")), list):
            raise PublicAPIUnavailable("Today consumer list missing")
        return result

    def read_video(self, video_id: str) -> dict:
        """Single verified video; identity must be supplied by caller."""
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError("Invalid YouTube video id")
        return self._read("/v1/catalog/videos/" + video_id)

    def read_day(self, day: date, *, limit: int = 50, offset: int = 0) -> dict:
        """Canonical History pagination; no fake complete marker."""
        if not isinstance(day, date) or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid history page")
        result = self._read("/v1/history", query={
            "day": day.isoformat(), "limit": str(limit), "offset": str(offset)
        })
        if not isinstance(result.get("items"), list):
            raise PublicAPIUnavailable("History consumer list missing")
        return result
