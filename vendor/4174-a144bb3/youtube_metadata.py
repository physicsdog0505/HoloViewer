"""Fetch and cache public YouTube livestream metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from pathlib import Path
import sqlite3
import subprocess
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KEYCHAIN_SERVICE = "Hololive-PTT-YouTube"
KEYCHAIN_ACCOUNT = "youtube-data-api-v3"
API_URL = "https://www.googleapis.com/youtube/v3/videos"


class YoutubeMetadataError(RuntimeError):
    pass


class YoutubeApiKeyMissing(YoutubeMetadataError):
    pass


@dataclass(frozen=True)
class YoutubeVideo:
    video_id: str
    title: str
    channel_title: str
    live_state: str
    scheduled_start: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    checked_at: datetime

    @property
    def preferred_start(self) -> datetime | None:
        return self.actual_start or self.scheduled_start

    @property
    def completed(self) -> bool:
        return self.actual_end is not None


def load_api_key() -> str:
    """Prefer a server-side secret for Linux/cloud; keep the Mac Keychain fallback.

    Neither the source code nor any client API response exposes this value.
    """
    for name in ("YOUTUBE_API_KEY", "YOUTUBE_DATA_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if sys.platform != "darwin":
        raise YoutubeApiKeyMissing(
            "伺服器未設定 YouTube API Key（YOUTUBE_API_KEY）。"
        )
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
             "-a", KEYCHAIN_ACCOUNT, "-w"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise YoutubeMetadataError("讀取 YouTube API Key 失敗或逾時") from exc
    value = result.stdout.strip() if result.returncode == 0 else ""
    if not value:
        raise YoutubeApiKeyMissing("macOS 鑰匙圈中找不到 YouTube API Key")
    return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch_video(video_id: str, api_key: str, *, opener=urlopen) -> YoutubeVideo:
    query = urlencode({
        "part": "snippet,liveStreamingDetails",
        "id": video_id,
        "key": api_key,
    })
    request = Request(f"{API_URL}?{query}", headers={"User-Agent": "Hololive-PTT-reader/18.5"})
    try:
        with opener(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise YoutubeMetadataError(f"YouTube API 連線失敗：{type(exc).__name__}") from exc

    if payload.get("error"):
        message = payload["error"].get("message", "YouTube API 回傳錯誤")
        raise YoutubeMetadataError(str(message))
    items = payload.get("items") or []
    if not items:
        raise YoutubeMetadataError("找不到影片，或影片不是可讀取的公開／非公開直播")
    item = items[0]
    snippet = item.get("snippet") or {}
    live = item.get("liveStreamingDetails") or {}
    if not live:
        raise YoutubeMetadataError("這支影片不是 YouTube 直播或直播存檔")
    return YoutubeVideo(
        video_id=video_id,
        title=str(snippet.get("title", "")),
        channel_title=str(snippet.get("channelTitle", "")),
        live_state=str(snippet.get("liveBroadcastContent", "none")),
        scheduled_start=_parse_datetime(live.get("scheduledStartTime")),
        actual_start=_parse_datetime(live.get("actualStartTime")),
        actual_end=_parse_datetime(live.get("actualEndTime")),
        checked_at=datetime.now(timezone.utc),
    )


class YoutubeMetadataStore:
    def __init__(self, path: str | Path, *, cache_enabled: bool = True) -> None:
        self.path = Path(path)
        self.cache_enabled = cache_enabled

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS youtube_videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                live_state TEXT NOT NULL,
                scheduled_start TEXT,
                actual_start TEXT,
                actual_end TEXT,
                checked_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> YoutubeVideo:
        return YoutubeVideo(
            video_id=row["video_id"], title=row["title"],
            channel_title=row["channel_title"], live_state=row["live_state"],
            scheduled_start=_parse_datetime(row["scheduled_start"]),
            actual_start=_parse_datetime(row["actual_start"]),
            actual_end=_parse_datetime(row["actual_end"]),
            checked_at=_parse_datetime(row["checked_at"]) or datetime.now(timezone.utc),
        )

    def get(self, video_id: str) -> YoutubeVideo | None:
        if not self.cache_enabled:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM youtube_videos WHERE video_id = ?", (video_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def put(self, video: YoutubeVideo) -> None:
        if not self.cache_enabled:
            return
        def iso(value: datetime | None) -> str | None:
            return value.astimezone(timezone.utc).isoformat() if value else None

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO youtube_videos (
                    video_id, title, channel_title, live_state,
                    scheduled_start, actual_start, actual_end, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title=excluded.title,
                    channel_title=excluded.channel_title,
                    live_state=excluded.live_state,
                    scheduled_start=excluded.scheduled_start,
                    actual_start=excluded.actual_start,
                    actual_end=excluded.actual_end,
                    checked_at=excluded.checked_at
                """,
                (video.video_id, video.title, video.channel_title, video.live_state,
                 iso(video.scheduled_start), iso(video.actual_start), iso(video.actual_end),
                 iso(video.checked_at)),
            )

    def get_or_fetch(
        self, video_id: str, *, max_age: timedelta = timedelta(minutes=5)
    ) -> tuple[YoutubeVideo, bool]:
        cached = self.get(video_id)
        now = datetime.now(timezone.utc)
        if cached and (cached.completed or now - cached.checked_at <= max_age):
            return cached, True
        video = fetch_video(video_id, load_api_key())
        self.put(video)
        return video, False
