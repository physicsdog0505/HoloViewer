"""Provider detection/capability metadata for watch-along sources."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class WatchalongProvider:
    key: str
    label: str
    mode: str
    authenticated_browser_preferred: bool
    direct_seek_supported: bool


YOUTUBE = WatchalongProvider(
    key="youtube",
    label="YouTube",
    mode="embedded",
    authenticated_browser_preferred=False,
    direct_seek_supported=True,
)

BAHAMUT_ANIME = WatchalongProvider(
    key="bahamut_anime",
    label="巴哈姆特動畫瘋",
    mode="companion",
    authenticated_browser_preferred=True,
    direct_seek_supported=False,
)

PRIME_VIDEO = WatchalongProvider(
    key="prime_video",
    label="Prime Video",
    mode="companion",
    authenticated_browser_preferred=True,
    direct_seek_supported=False,
)

UNKNOWN = WatchalongProvider(
    key="unknown",
    label="其他來源",
    mode="companion",
    authenticated_browser_preferred=True,
    direct_seek_supported=False,
)


def detect_provider(url: str) -> WatchalongProvider:
    """Classify a source URL without making any network request."""
    value = (url or "").strip()
    if not value:
        return UNKNOWN
    try:
        parsed = urlparse(value)
    except ValueError:
        return UNKNOWN
    host = (parsed.hostname or "").lower().rstrip(".")
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return YOUTUBE
    if host == "ani.gamer.com.tw" or host.endswith(".ani.gamer.com.tw"):
        return BAHAMUT_ANIME
    if host in {"primevideo.com", "www.primevideo.com"} or host.endswith(".primevideo.com"):
        return PRIME_VIDEO
    return UNKNOWN


def is_http_source(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
