"""Resolve YouTube playlist URLs into ordered Watchalong source video ids."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlparse

from frontend_time import youtube_video_id
from urllib.request import Request, urlopen


PLAYLIST_ITEMS_API = "https://www.googleapis.com/youtube/v3/playlistItems"


class WatchalongPlaylistError(RuntimeError):
    pass


def youtube_playlist_id(value: str) -> str | None:
    """Extract a YouTube playlist id from a normal playlist/watch URL."""
    value = str(value or "").strip()
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
    }:
        return None
    playlist_id = parse_qs(parsed.query).get("list", [""])[0].strip()
    return playlist_id or None


def is_raw_playlist_url(value: str) -> bool:
    """Return True when a URL identifies a playlist but not a playable YouTube video."""
    return bool(youtube_playlist_id(value)) and youtube_video_id(value) is None


def slice_playlist(
    video_ids: tuple[str, ...] | list[str],
    start_index: int,
    count: int | None = None,
) -> tuple[str, ...]:
    """Return a 1-based playlist window, optionally bounded by item count."""
    if start_index < 1:
        raise ValueError("playlist start index must be >= 1")
    if count is not None and count < 1:
        raise ValueError("playlist count must be >= 1")
    ordered = tuple(str(video_id).strip() for video_id in video_ids if str(video_id).strip())
    if not ordered:
        raise WatchalongPlaylistError("YouTube playlist contains no playable videos")
    if start_index > len(ordered):
        raise WatchalongPlaylistError(
            f"playlist start index {start_index} exceeds {len(ordered)} available videos"
        )
    selected = ordered[start_index - 1 :]
    return selected if count is None else selected[:count]


def resolve_youtube_playlist(
    playlist_url: str,
    api_key: str,
    *,
    start_index: int = 1,
    count: int | None = None,
    opener=urlopen,
) -> tuple[str, ...]:
    """Resolve all playlist items with the YouTube Data API and preserve order."""
    playlist_id = youtube_playlist_id(playlist_url)
    if not playlist_id:
        raise WatchalongPlaylistError("無法辨識 YouTube Playlist URL")
    api_key = str(api_key or "").strip()
    if not api_key:
        raise WatchalongPlaylistError("缺少 YouTube API key，無法展開 Playlist")

    video_ids: list[str] = []
    page_token = ""
    while True:
        query = {
            "part": "contentDetails",
            "maxResults": "50",
            "playlistId": playlist_id,
            "key": api_key,
        }
        if page_token:
            query["pageToken"] = page_token
        request = Request(
            f"{PLAYLIST_ITEMS_API}?{urlencode(query)}",
            headers={"User-Agent": "Hololive-PTT-reader/watchalong"},
        )
        try:
            with opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise WatchalongPlaylistError(
                f"YouTube Playlist API 連線失敗：{type(exc).__name__}"
            ) from exc

        if payload.get("error"):
            error = payload.get("error") or {}
            message = error.get("message") or "YouTube Playlist API 回傳錯誤"
            raise WatchalongPlaylistError(str(message))

        for item in payload.get("items") or []:
            content = item.get("contentDetails") or {}
            video_id = str(content.get("videoId") or "").strip()
            if video_id:
                video_ids.append(video_id)

        # Archived Watchalong only needs the first selected N episodes.
        # Stop paging once that window is complete; live queues still request
        # the full Playlist by passing count=None.
        if count is not None and len(video_ids) >= (start_index - 1 + count):
            break
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            break

    if not video_ids:
        raise WatchalongPlaylistError(
            "Playlist 沒有可用影片；可能是空清單、私人清單或影片不可用"
        )
    return slice_playlist(video_ids, start_index, count)


def playlist_source_urls(
    playlist_url: str,
    api_key: str,
    *,
    start_index: int = 1,
    count: int | None = None,
    opener=urlopen,
) -> tuple[str, ...]:
    """Resolve a playlist into canonical YouTube watch URLs for the existing source sequence."""
    video_ids = resolve_youtube_playlist(
        playlist_url,
        api_key,
        start_index=start_index,
        count=count,
        opener=opener,
    )
    return tuple(f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids)
