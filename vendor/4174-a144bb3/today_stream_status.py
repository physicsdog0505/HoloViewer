"""Explicit, quota-efficient YouTube status enrichment for today's PTT stream picker.

The picker never calls this module automatically on Streamlit reruns. Callers must
trigger enrichment explicitly. Video IDs are batched into `videos.list` requests
(up to 50 IDs per request) so one page refresh normally costs one quota unit rather
than one request per card.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from youtube_metadata import API_URL, YoutubeMetadataError, YoutubeVideo, load_api_key


MAX_IDS_PER_REQUEST = 50
STATUS_SNAPSHOT_VERSION = 1


def _video_payload(video: YoutubeVideo) -> dict[str, object]:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_title": video.channel_title,
        "live_state": video.live_state,
        "scheduled_start": video.scheduled_start.isoformat() if video.scheduled_start else None,
        "actual_start": video.actual_start.isoformat() if video.actual_start else None,
        "actual_end": video.actual_end.isoformat() if video.actual_end else None,
        "checked_at": video.checked_at.isoformat() if video.checked_at else None,
    }


def _video_from_payload(payload: Mapping[str, object]) -> YoutubeVideo:
    return YoutubeVideo(
        video_id=str(payload.get("video_id") or ""),
        title=str(payload.get("title") or ""),
        channel_title=str(payload.get("channel_title") or ""),
        live_state=str(payload.get("live_state") or ""),
        scheduled_start=_parse_datetime(payload.get("scheduled_start") if isinstance(payload.get("scheduled_start"), str) else None),
        actual_start=_parse_datetime(payload.get("actual_start") if isinstance(payload.get("actual_start"), str) else None),
        actual_end=_parse_datetime(payload.get("actual_end") if isinstance(payload.get("actual_end"), str) else None),
        checked_at=_parse_datetime(payload.get("checked_at") if isinstance(payload.get("checked_at"), str) else None),
    )


def save_status_snapshot(
    path: str | Path,
    *,
    day: str,
    statuses: Mapping[str, YoutubeVideo],
    attempted_at: Mapping[str, datetime] | None = None,
    updated_at: datetime | None = None,
) -> None:
    """Persist rebuildable canonical lifecycle metadata for one calendar day."""

    target = Path(path)
    updated = updated_at or datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    attempts = attempted_at or {}
    payload = {
        "version": STATUS_SNAPSHOT_VERSION,
        "day": str(day),
        "updated_at": updated.astimezone(timezone.utc).isoformat(),
        "videos": {
            video_id: _video_payload(video)
            for video_id, video in sorted(statuses.items())
            if video_id and video.video_id
        },
        "attempted_at": {
            video_id: value.astimezone(timezone.utc).isoformat()
            for video_id, value in sorted(attempts.items())
            if video_id and value is not None
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def load_status_snapshot(
    path: str | Path,
    *,
    day: str,
) -> tuple[dict[str, YoutubeVideo], dict[str, datetime]]:
    """Load only the requested day's canonical lifecycle metadata."""

    target = Path(path)
    if not target.exists():
        return {}, {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("version") != STATUS_SNAPSHOT_VERSION:
        raise ValueError("unsupported today-stream status snapshot version")
    if str(payload.get("day") or "") != str(day):
        return {}, {}
    videos = payload.get("videos")
    attempts = payload.get("attempted_at") or {}
    if not isinstance(videos, dict) or not isinstance(attempts, dict):
        raise ValueError("invalid today-stream status snapshot")
    result: dict[str, YoutubeVideo] = {}
    for video_id, raw in videos.items():
        if not isinstance(raw, dict):
            continue
        video = _video_from_payload(raw)
        if video.video_id and video.video_id == video_id:
            result[video_id] = video
    attempted: dict[str, datetime] = {}
    for video_id, raw in attempts.items():
        if isinstance(raw, str):
            value = _parse_datetime(raw)
            if value is not None:
                attempted[video_id] = value
    return result, attempted



def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _video_from_item(item: dict, checked_at: datetime) -> YoutubeVideo:
    snippet = item.get("snippet") or {}
    live = item.get("liveStreamingDetails") or {}
    return YoutubeVideo(
        video_id=str(item.get("id", "")),
        title=str(snippet.get("title", "")),
        channel_title=str(snippet.get("channelTitle", "")),
        live_state=str(snippet.get("liveBroadcastContent", "")),
        scheduled_start=_parse_datetime(live.get("scheduledStartTime")),
        actual_start=_parse_datetime(live.get("actualStartTime")),
        actual_end=_parse_datetime(live.get("actualEndTime")),
        checked_at=checked_at,
    )


def _has_status_evidence(item: dict) -> bool:
    """Return whether a videos.list item can safely participate in status filtering.

    A returned object with only an ID (or similarly incomplete snippet data) is not
    evidence that the video is an ordinary upload. Treat it like a missing API item
    so the page keeps the PTT-discovered stream as unknown instead of filtering it.
    """
    snippet = item.get("snippet")
    if isinstance(snippet, dict) and "liveBroadcastContent" in snippet:
        return True
    live = item.get("liveStreamingDetails")
    return isinstance(live, dict) and any(
        live.get(key)
        for key in ("scheduledStartTime", "actualStartTime", "actualEndTime")
    )


def _chunks(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def fetch_video_statuses(
    video_ids: Iterable[str],
    *,
    api_key: str | None = None,
    opener=urlopen,
) -> dict[str, YoutubeVideo]:
    """Fetch public stream metadata in deterministic <=50-ID `videos.list` batches."""
    unique = tuple(dict.fromkeys(str(value).strip() for value in video_ids if str(value).strip()))
    if not unique:
        return {}
    key = api_key or load_api_key()
    results: dict[str, YoutubeVideo] = {}
    checked_at = datetime.now(timezone.utc)
    for batch in _chunks(unique, MAX_IDS_PER_REQUEST):
        query = urlencode(
            {
                "part": "snippet,liveStreamingDetails",
                "id": ",".join(batch),
                "key": key,
            }
        )
        request = Request(
            f"{API_URL}?{query}",
            headers={"User-Agent": "Hololive-PTT-reader/117"},
        )
        try:
            with opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise YoutubeMetadataError(
                f"YouTube API 連線失敗：{type(exc).__name__}"
            ) from exc
        if payload.get("error"):
            message = payload["error"].get("message", "YouTube API 回傳錯誤")
            raise YoutubeMetadataError(str(message))
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            if not _has_status_evidence(item):
                continue
            video = _video_from_item(item, checked_at)
            results[video.video_id] = video
    return results


def has_livestream_metadata(video: YoutubeVideo | None) -> bool:
    """True only when YouTube identifies the item as a livestream/premiere lifecycle."""
    if video is None:
        return False
    return bool(
        video.live_state in {"live", "upcoming"}
        or video.scheduled_start is not None
        or video.actual_start is not None
        or video.actual_end is not None
    )


def stream_state(video: YoutubeVideo | None, *, now: datetime | None = None) -> str:
    """Return a stable picker state: live, waiting, upcoming, ended, non_live, unknown."""
    if video is None:
        return "unknown"
    if not has_livestream_metadata(video):
        return "non_live" if video.live_state == "none" else "unknown"
    if video.actual_end is not None:
        return "ended"
    if video.live_state == "live" or (video.actual_start is not None and video.actual_end is None):
        return "live"
    if video.live_state == "upcoming":
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        if video.scheduled_start is not None and video.scheduled_start <= current.astimezone(timezone.utc):
            return "waiting"
        return "upcoming"
    return "unknown"


def status_label(video: YoutubeVideo | None, *, now: datetime | None = None) -> str:
    state = stream_state(video, now=now)
    return {
        "live": "直播中",
        "waiting": "等待中",
        "upcoming": "尚未開始",
        "ended": "已結束",
        "non_live": "非直播",
        "unknown": "狀態未更新",
    }[state]
