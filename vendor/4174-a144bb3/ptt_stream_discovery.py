"""Offline helpers for measuring YouTube discovery from stored PTT thread bodies.

Issue #117 is investigation-first.  This module deliberately stays independent
from Streamlit, network access, and production database mutation so extraction
quality/cost can be measured before choosing parse-on-demand versus a derived
index/cache.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from frontend_time import youtube_video_id


URL_RE = re.compile(r"https?://[^\s<>\"']+")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}
_TRAILING_PUNCTUATION = ").,，。;；:：!?！？]}>」』】"


@dataclass(frozen=True)
class BodyUrl:
    url: str
    line_number: int
    char_offset: int
    video_id: str | None
    youtube_host: bool


@dataclass(frozen=True)
class DiscoveredStream:
    video_id: str
    url: str
    first_line: int
    occurrence_count: int


def _clean_url(raw: str) -> str:
    return raw.rstrip(_TRAILING_PUNCTUATION)


def _is_youtube_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in _YOUTUBE_HOSTS


def extract_body_urls(body_text: str) -> tuple[BodyUrl, ...]:
    """Return HTTP(S) URLs with stable line/offset provenance.

    ``web_backfill.parse_body_parts`` stores full anchor targets in body text,
    so no DOM/network access is required here.
    """
    found: list[BodyUrl] = []
    absolute_offset = 0
    for line_number, line in enumerate(body_text.splitlines(keepends=True), start=1):
        for match in URL_RE.finditer(line):
            url = _clean_url(match.group(0))
            if not url:
                continue
            found.append(
                BodyUrl(
                    url=url,
                    line_number=line_number,
                    char_offset=absolute_offset + match.start(),
                    video_id=youtube_video_id(url),
                    youtube_host=_is_youtube_url(url),
                )
            )
        absolute_offset += len(line)
    return tuple(found)


def discover_streams(body_text: str) -> tuple[DiscoveredStream, ...]:
    """Deduplicate recognizable YouTube video IDs, preserving first occurrence."""
    urls = extract_body_urls(body_text)
    grouped: dict[str, list[BodyUrl]] = {}
    order: list[str] = []
    for item in urls:
        if item.video_id is None:
            continue
        if item.video_id not in grouped:
            grouped[item.video_id] = []
            order.append(item.video_id)
        grouped[item.video_id].append(item)
    return tuple(
        DiscoveredStream(
            video_id=video_id,
            url=grouped[video_id][0].url,
            first_line=grouped[video_id][0].line_number,
            occurrence_count=len(grouped[video_id]),
        )
        for video_id in order
    )


def extraction_metrics(body_text: str) -> dict[str, int]:
    """Return deterministic counts used by the Issue #117 investigation probe."""
    urls = extract_body_urls(body_text)
    youtube_urls = [item for item in urls if item.youtube_host]
    recognized = [item for item in youtube_urls if item.video_id is not None]
    unique_ids = {item.video_id for item in recognized}
    return {
        "total_urls": len(urls),
        "youtube_urls": len(youtube_urls),
        "recognized_youtube_urls": len(recognized),
        "unique_video_ids": len(unique_ids),
        "duplicate_youtube_urls": len(recognized) - len(unique_ids),
        "unrecognized_youtube_urls": len(youtube_urls) - len(recognized),
    }
