"""Standalone user-facing Client UI server.

This is deliberately separate from the existing Streamlit/Internal/Admin/Test
launchers and ports. It currently exposes the first production-facing Client
slice: Watchalong.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
import sqlite3
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from client_custom_view import (
    build_custom_view_html,
    build_custom_view_session_html,
    custom_view_session_from_query,
)
from client_history import build_history_day_html, load_history_day, parse_history_day, history_day_bounds
from client_home import build_collab_hub_html, build_home_fragment, build_home_html, load_collab_event_streams, load_home_streams
from client_collab_candidates import detect_collab_candidates, resolve_collab_candidate
from client_stream_catalog import load_client_catalog_video
from client_runtime import client_runtime_root
from frontend_config import database_paths
from frontend_db import merged_pushes_for_window
from frontend_multistream_sync import _timeline_messages
from client_ptt_today import (
    build_ptt_today_focus_html,
    build_ptt_today_page_html,
    load_today_pushes,
    today_pushes_payload,
)
from client_watchalong import (
    build_companion_session_html,
    build_watchalong_landing_html,
    build_watchalong_session_html,
    load_recent_watchalong_cards,
    load_client_watchalong_source_mapping,
    load_latest_client_watchalong_source_mapping,
    load_client_watchalong_ptt,
    load_client_cached_ab_translation,
    new_client_watchalong_telemetry,
    resolve_watchalong_alignment,
    resolve_watchalong_master_mode,
    save_client_watchalong_source_mapping,
)
from frontend_time import TAIPEI
from watchalong_playlist import WatchalongPlaylistError, resolve_youtube_playlist
from youtube_metadata import YoutubeApiKeyMissing, YoutubeMetadataError, load_api_key, fetch_video
from today_stream_refresh import refresh_today_snapshot

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4174


def _watchalong_timed(stage: str, callback, *args, **kwargs):
    """Opt-in server-side latency trace; never log URLs, video IDs or API keys."""
    enabled = os.environ.get("PTT_CLIENT_WATCHALONG_TIMING") == "1"
    if not enabled:
        return callback(*args, **kwargs)
    started = time.perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        # Stage is a fixed internal identifier, not user-controlled input.
        print(json.dumps({
            "component": "client_watchalong_timing",
            "stage": stage,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }), file=sys.stderr, flush=True)


def _start_today_refresh_loop(runtime_root: str, *, interval_seconds: int = 60) -> tuple[threading.Event, threading.Thread]:
    """Keep 4174 lifecycle evidence fresh without blocking HTTP requests.

    The Client reads persisted runtime data on every /api/home request. This
    lightweight producer only advances the canonical today-stream snapshot and
    catalog projection. It is intentionally replaceable by the production
    backend later; the browser never receives or stores the YouTube API key.
    """
    stop = threading.Event()
    root = str(runtime_root)

    def run() -> None:
        while not stop.is_set():
            try:
                refresh_today_snapshot(root)
            except (OSError, ValueError, TypeError, sqlite3.Error, YoutubeApiKeyMissing, YoutubeMetadataError):
                # Preserve the last-good snapshot; the next cadence retries.
                pass
            stop.wait(max(15, int(interval_seconds)))

    thread = threading.Thread(
        target=run,
        name="4174-today-stream-refresh",
        daemon=True,
    )
    thread.start()
    return stop, thread


def _ptt_video_payload(video_id: str) -> dict:
    """Resolve PTT against one video's verified wall clock without guessing relationships."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return {"mode": "unavailable", "video_id": video_id, "reason": "invalid_video_id"}
    try:
        row = load_client_catalog_video(client_runtime_root(), video_id)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        row = None
    if (
        row is None
        or row.actual_start is None
        or row.actual_start.tzinfo is None
    ):
        return {
            "mode": "unavailable",
            "video_id": video_id,
            "reason": "missing_verified_start",
        }

    collector, web_db = database_paths(root=client_runtime_root())
    if row.lifecycle_state == "ended":
        if row.actual_end is None or row.actual_end <= row.actual_start:
            return {
                "mode": "unavailable",
                "video_id": video_id,
                "reason": "missing_verified_end",
            }
        try:
            pushes = merged_pushes_for_window(
                collector, web_db, row.actual_start, row.actual_end
            )
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pushes = []
        messages = _timeline_messages(pushes, row.actual_start)
        if not messages or len(messages) > 20000:
            return {
                "mode": "unavailable",
                "video_id": video_id,
                "reason": "archive_ptt_unavailable",
            }
        return {
            "mode": "archive",
            "video_id": video_id,
            "start": row.actual_start.isoformat(),
            "messages": messages,
        }

    if row.lifecycle_state == "live":
        now = datetime.now(TAIPEI)
        try:
            pushes = merged_pushes_for_window(
                collector, web_db, row.actual_start, now
            )
        except (OSError, ValueError, TypeError, sqlite3.Error):
            pushes = []
        messages = _timeline_messages(pushes, row.actual_start)
        if len(messages) > 20000:
            messages = messages[-20000:]
        return {
            "mode": "live",
            "video_id": video_id,
            "start": row.actual_start.isoformat(),
            "messages": messages,
        }

    return {
        "mode": "unavailable",
        "video_id": video_id,
        "reason": "not_playable_lifecycle",
    }


class ClientRequestHandler(BaseHTTPRequestHandler):
    server_version = "HololivePTTClient/0.1"

    def _html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/":
            live, upcoming, ended, unknown = load_home_streams()
            self._html(
                build_home_html(
                    live,
                    upcoming,
                    ended,
                    unknown,
                    today_label=datetime.now(TAIPEI).strftime("%Y/%m/%d"),
                )
            )
            return

        if parsed.path == "/history":
            query = parse_qs(parsed.query)
            current = datetime.now(TAIPEI)
            _, default_day = history_day_bounds(current)
            raw = query.get("date", [default_day.isoformat()])[0]
            try:
                selected = parse_history_day(raw, now=current)
                page = int(query.get("page", ["1"])[0])
                if page < 1 or page > 10000:
                    raise ValueError("無效的頁數。")
            except (ValueError, OverflowError):
                self._html("無效的歷史日期或頁數。", HTTPStatus.BAD_REQUEST)
                return
            error = ""
            try:
                cards, has_more = load_history_day(selected, page=page)
            except (OSError, ValueError, sqlite3.Error) as exc:
                cards, has_more = [], False
                error = "歷史資料目前無法讀取；請檢查唯讀 History DB 是否已接入。"
            self._html(build_history_day_html(
                selected, cards, page=page, has_more=has_more,
                error=error, now=current,
            ))
            return

        if parsed.path == "/api/home":
            current = datetime.now(TAIPEI)
            live, upcoming, ended, unknown = load_home_streams(now=current)
            today_label = current.strftime("%Y/%m/%d")
            self._json(
                {
                    "today_label": today_label,
                    "html": build_home_fragment(
                        live,
                        upcoming,
                        ended,
                        unknown,
                        today_label=today_label,
                    ),
                }
            )
            return

        if parsed.path in {"/api/translation/preflight", "/api/translation/prepare", "/api/watchalong/reanalyze"}:
            # 4174 is read-only for translation/alignment artifacts. Generation
            # and re-analysis are owner-side 8501/background responsibilities.
            self._json(
                {"error": "4174 僅讀取已完成的 Transcript／A／B 與既有對齊結果；不執行翻譯或重新分析。"},
                HTTPStatus.NOT_FOUND,
            )
            return

        if parsed.path == "/api/watchalong/progressive":
            self._json(
                {"error": "4174 僅讀取已完成的翻譯成果；不執行漸進翻譯。"},
                HTTPStatus.NOT_FOUND,
            )
            return

        if parsed.path == "/watchalong":
            query = parse_qs(parsed.query)
            master = query.get("master", [""])[0]
            fresh = query.get("fresh", ["0"])[0] == "1"
            mapping = load_client_watchalong_source_mapping(master) if master else None
            if not master and not fresh:
                mapping = load_latest_client_watchalong_source_mapping()
                if mapping is not None:
                    master = mapping.master_url
            self._html(
                build_watchalong_landing_html(
                    recent_pool=load_recent_watchalong_cards(),
                    master_value=master,
                    playlist_value=(mapping.playlist_url if mapping else ""),
                    playlist_start_value=(mapping.playlist_start_index if mapping else 1),
                )
            )
            return

        if parsed.path == "/api/ptt/today":
            query = parse_qs(parsed.query)
            after = query.get("after", [""])[0]
            if len(after) > 100 or (after and not re.fullmatch(r"[0-9]+:[0-9]+", after)):
                self._json({"error": "Invalid push cursor"}, HTTPStatus.BAD_REQUEST)
                return
            try:
                selected, pushes = load_today_pushes()
            except (OSError, ValueError, TypeError, sqlite3.Error):
                self._json({"error": "PTT source unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
                return
            self._json(today_pushes_payload(selected, pushes, after_key=after))
            return

        if parsed.path == "/ptt-today":
            query = parse_qs(parsed.query)
            try:
                selected, pushes = load_today_pushes()
            except (OSError, ValueError, TypeError, sqlite3.Error):
                self._html(
                    build_ptt_today_page_html([], datetime.now(TAIPEI).date()),
                    HTTPStatus.OK,
                )
                return
            if query.get("focus", ["0"])[0] == "1":
                self._html(build_ptt_today_focus_html(pushes, selected, embedded=query.get("embed", ["0"])[0] == "1"))
            else:
                self._html(build_ptt_today_page_html(pushes, selected))
            return

        if parsed.path == "/api/ptt/video":
            query = parse_qs(parsed.query)
            video_id = query.get("video_id", [""])[0].strip()
            self._json(_ptt_video_payload(video_id))
            return

        if parsed.path == "/custom-view":
            self._html(build_custom_view_html(live_streams=load_home_streams()[0]))
            return

        if parsed.path == "/collab":
            live, upcoming, ended = load_collab_event_streams()
            self._html(build_collab_hub_html(live, upcoming, ended))
            return

        if parsed.path == "/api/collab/live":
            query = parse_qs(parsed.query)
            if query.get("collab", [""])[0] not in {"ark", "shared-topic"}:
                self._json({"error": "Unsupported collab"}, HTTPStatus.BAD_REQUEST)
                return
            live, upcoming, ended = load_collab_event_streams()
            candidates = detect_collab_candidates([*live, *upcoming, *ended])
            candidate = resolve_collab_candidate(candidates, query.get("stream", []))
            if candidate is None:
                self._json({"event": None, "streams": []})
                return
            self._json({
                "event": candidate.label,
                "streams": [
                    {"video_id": item.video_id, "channel_id": item.channel_id,
                     "label": item.channel_title or item.title}
                    for item in live if item.video_id in candidate.video_ids
                ],
            })
            return

        if parsed.path == "/collab/session":
            query = parse_qs(parsed.query)
            if query.get("collab", [""])[0] not in {"ark", "shared-topic"}:
                self._html(build_custom_view_html(error="不支援的多人連動類型。", live_streams=load_home_streams()[0]), HTTPStatus.BAD_REQUEST)
                return
            requested = query.get("stream", [])
            live, upcoming, ended = load_collab_event_streams()
            candidates = detect_collab_candidates([*live, *upcoming, *ended])
            candidate = resolve_collab_candidate(candidates, requested)
            if candidate is None:
                self._html(build_custom_view_html(error="目前找不到可驗證的多人連動候選。", live_streams=live), HTTPStatus.NOT_FOUND)
                return
            live_ids = {item.video_id for item in live}
            initial = [video_id for video_id in candidate.video_ids if video_id in live_ids]
            if not initial:
                initial = list(candidate.video_ids)
            try:
                session = custom_view_session_from_query(
                    initial, layout="auto", primary_index=0, audio_master_index=0,
                )
            except (ValueError, TypeError) as exc:
                self._html(build_custom_view_html(error=str(exc), live_streams=live), HTTPStatus.BAD_REQUEST)
                return
            ended_ids = {item.video_id for item in ended}
            historical_collab = bool(initial) and all(
                video_id in ended_ids for video_id in initial
            )
            worker_config = None
            ptt_alignment_notice = ""
            verified_start_times = ()
            collab_poll_url = ""

            if historical_collab:
                # Historical collab sessions must never embed today's live PTT.
                # Reuse the same verified archive path as ended single-VOD viewing.
                ptt_alignment_notice = (
                    "這場多人連動已結束，但尚無可用且完整的歷史 PTT 時間範圍。"
                    "不會拿今日專串冒充當時留言。"
                )
                try:
                    catalog_rows = [
                        load_client_catalog_video(client_runtime_root(), video_id)
                        for video_id in initial
                    ]
                    if all(
                        row is not None
                        and row.lifecycle_state == "ended"
                        and row.actual_start is not None
                        and row.actual_start.tzinfo is not None
                        and row.actual_end is not None
                        and row.actual_end > row.actual_start
                        for row in catalog_rows
                    ):
                        verified_start_times = tuple(
                            row.actual_start.timestamp() for row in catalog_rows
                        )
                        master = catalog_rows[0]
                        event_start = min(row.actual_start for row in catalog_rows)
                        event_end = max(row.actual_end for row in catalog_rows)
                        collector, web_db = database_paths(root=client_runtime_root())
                        pushes = merged_pushes_for_window(
                            collector, web_db, event_start, event_end
                        )
                        messages = _timeline_messages(pushes, master.actual_start)
                        if messages and len(messages) <= 20000:
                            worker_config = {
                                "mode": "archive",
                                "videoId": master.video_id,
                                "start": master.actual_start.isoformat(),
                                "rows": messages,
                            }
                            ptt_alignment_notice = ""
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    pass
            else:
                poll_query = "&".join(
                    [f"collab={candidate.event_key}"]
                    + [f"stream={video_id}" for video_id in candidate.video_ids]
                )
                collab_poll_url = "/api/collab/live?" + poll_query

            self._html(build_custom_view_session_html(
                session,
                show_live_ptt=True,
                ptt_worker_config=worker_config,
                ptt_alignment_notice=ptt_alignment_notice,
                verified_start_times=verified_start_times,
                collab_poll_url=collab_poll_url,
                collab_label=candidate.label,
                ptt_resolver_url="/api/ptt/video",
            ))
            return

        if parsed.path == "/custom-view/session":
            query = parse_qs(parsed.query)
            streams = query.get("stream", [])
            try:
                session = custom_view_session_from_query(
                    streams,
                    layout=query.get("layout", ["auto"])[0],
                    primary_index=int(query.get("primary", ["0"])[0]),
                    audio_master_index=int(query.get("audio", ["0"])[0]),
                )
            except (ValueError, TypeError) as exc:
                self._html(build_custom_view_html(error=str(exc), live_streams=load_home_streams()[0]), HTTPStatus.BAD_REQUEST)
                return
            # Manual/custom multi-VOD selection is not proof of a shared event.
            # Keep automatic absolute-time sync OFF by default, but expose an
            # owner-controlled opt-in when every selected item is a completed
            # VOD with a catalog-confirmed actual_start.
            verified_start_times = ()
            manual_start_times = ()
            if len(session.streams) > 1:
                try:
                    manual_rows = [
                        load_client_catalog_video(
                            client_runtime_root(), stream.video_id
                        )
                        for stream in session.streams
                    ]
                    if all(
                        row is not None
                        and row.lifecycle_state == "ended"
                        and row.actual_start is not None
                        and row.actual_start.tzinfo is not None
                        for row in manual_rows
                    ):
                        manual_start_times = tuple(
                            row.actual_start.timestamp() for row in manual_rows
                        )
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    manual_start_times = ()
            ptt_mode = query.get("ptt", ["live"])[0]
            if ptt_mode not in {"video", "live"}:
                self._html(build_custom_view_html(error="不支援的 PTT 觀看版型。", live_streams=load_home_streams()[0]), HTTPStatus.BAD_REQUEST)
                return
            worker_config = None
            ptt_alignment_notice = ""
            # Never show today's PTT article as if it belonged to an ended VOD.
            # Missing verified per-video article provenance must fail closed.
            if ptt_mode == "live" and len(session.streams) == 1:
                try:
                    match = load_client_catalog_video(
                        client_runtime_root(), session.streams[0].video_id
                    )
                    if match is not None and match.lifecycle_state == "ended":
                        ptt_alignment_notice = (
                            "這部影片已結束，但尚無可用且完整的歷史 PTT 時間範圍。"
                            "不會拿今日專串冒充影片當時的留言。"
                        )
                        if (
                            match.actual_start is not None
                            and match.actual_end is not None
                            and match.actual_end > match.actual_start
                        ):
                            try:
                                collector, web_db = database_paths(root=client_runtime_root())
                                pushes = merged_pushes_for_window(
                                    collector, web_db, match.actual_start, match.actual_end
                                )
                                messages = _timeline_messages(pushes, match.actual_start)
                                if messages and len(messages) <= 20000:
                                    worker_config = {
                                        "mode": "archive",
                                        "videoId": match.video_id,
                                        "start": match.actual_start.isoformat(),
                                        "rows": messages,
                                    }
                                    ptt_alignment_notice = ""
                            except (OSError, ValueError, TypeError, sqlite3.Error):
                                pass
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    pass
            # Opt-in only: no implicit association between a YouTube video and a PTT article.
            aid = query.get("ptt_aid", [""])[0].strip()
            endpoint = query.get("ptt_api", [""])[0].strip()
            video_id = query.get("ptt_video_id", [""])[0].strip()
            if ptt_mode == "live" and aid and endpoint:
                if not video_id and len(session.streams) == 1:
                    video_id = session.streams[0].video_id
                url = urlparse(endpoint)
                if (
                    not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", aid, re.I)
                    or not url.scheme == "https"
                    or bool(url.username or url.password)
                    or url.path != "/v1/ptt"
                    or video_id not in {stream.video_id for stream in session.streams}
                ):
                    self._html(build_custom_view_html(
                        error="PTT 同步需要有效 AID、HTTPS /v1/ptt 與播放清單內的 Video ID。",
                        live_streams=load_home_streams()[0]), HTTPStatus.BAD_REQUEST)
                    return
                # Only YouTube's actual start, not scheduled start or browser load time.
                try:
                    meta = fetch_video(video_id, load_api_key())
                    actual_start = meta.actual_start
                except (YoutubeMetadataError, YoutubeApiKeyMissing, OSError, ValueError):
                    actual_start = None
                if actual_start is not None and actual_start.tzinfo is not None:
                    worker_config = {
                        "videoId": video_id,
                        "aid": aid,
                        "start": actual_start.isoformat(),
                        "endpoint": endpoint,
                    }
                else:
                    ptt_alignment_notice = "YouTube 尚無可驗證的實際開播時間，暫時無法將 PTT 推文與影片時間對齊。"
            # Translation is deliberately gated to one completed VOD.
            # Live/upcoming/unknown and every multi-view session stay translation-free
            # until a multi-POV subtitle ownership/timeline policy is defined.
            translation_a, translation_b = (), ()
            translation_eligible = False
            translation_video_id = ""
            if len(session.streams) == 1:
                video_id = session.streams[0].video_id
                # The same verified completed-video evidence that enables archive
                # PTT also enables the VOD translation action.  Do not make the
                # button disappear merely because a secondary catalog lookup fails.
                translation_match = None
                try:
                    translation_match = load_client_catalog_video(client_runtime_root(), video_id)
                except (OSError, ValueError, TypeError, sqlite3.Error):
                    translation_match = None
                is_completed_vod = bool(
                    translation_match is not None
                    and translation_match.lifecycle_state == "ended"
                )
                if not is_completed_vod and worker_config and worker_config.get("mode") == "archive":
                    is_completed_vod = True
                if is_completed_vod:
                    # 4174 is cache-only: expose saved A/B tracks, never an action.
                    translation_video_id = video_id
                    try:
                        translation_a, translation_b = load_client_cached_ab_translation(video_id)
                    except (OSError, ValueError, TypeError, sqlite3.Error):
                        translation_a, translation_b = (), ()
            self._html(build_custom_view_session_html(
                session, show_live_ptt=ptt_mode == "live",
                ptt_worker_config=worker_config,
                ptt_alignment_notice=ptt_alignment_notice if worker_config is None else "",
                verified_start_times=verified_start_times,
                manual_start_times=manual_start_times,
                ptt_resolver_url="/api/ptt/video" if ptt_mode == "live" else "",
                translation_a=translation_a,
                translation_b=translation_b,
                translation_eligible=translation_eligible,
                translation_video_id=translation_video_id,
            ))
            return

        if parsed.path == "/watchalong/session":
            query = parse_qs(parsed.query)
            master = query.get("master", [""])[0]
            source_kind = query.get("source_kind", ["youtube"])[0]
            source = query.get("source", [""])[0]
            try:
                if source_kind == "external":
                    external_source = query.get("external_source", [""])[0]
                    page = _watchalong_timed("companion_render", build_companion_session_html, master, external_source)
                else:
                    requested_mode = query.get("view_mode", ["auto"])[0]
                    if requested_mode not in {"auto", "archive", "live"}:
                        raise ValueError("觀看模式無法辨識。")
                    resolved_mode = (
                        _watchalong_timed("master_mode", resolve_watchalong_master_mode, master)
                        if requested_mode == "auto"
                        else requested_mode
                    )
                    if resolved_mode == "unknown":
                        raise ValueError(
                            "無法自動判定這支直播是即時或舊檔，請手動選擇觀看模式。"
                        )

                    youtube_mode = query.get("youtube_mode", ["single"])[0]
                    if youtube_mode == "playlist":
                        playlist_url = query.get("playlist", [""])[0]
                        start_raw = query.get("playlist_start", ["1"])[0]
                        count_raw = query.get("playlist_count", [""])[0].strip()
                        start_index = int(start_raw or "1")
                        explicit_count = int(count_raw) if count_raw else None

                        alignment = _watchalong_timed("alignment", resolve_watchalong_alignment, master)
                        all_starts = alignment.starts if alignment is not None else ()
                        # An archived session only needs cue-matched / explicitly
                        # requested episodes. Avoid paging the entire YouTube
                        # Playlist when the active window is already known.
                        archive_count = (
                            (explicit_count or max(1, len(all_starts)))
                            if resolved_mode == "archive" else None
                        )
                        all_ids = _watchalong_timed(
                            "playlist", resolve_youtube_playlist,
                            playlist_url,
                            _watchalong_timed("api_key", load_api_key),
                            start_index=start_index,
                            **({"count": archive_count} if archive_count is not None else {}),
                        )
                        if resolved_mode == "archive":
                            active_count = archive_count
                            active_ids = all_ids[:active_count]
                            waiting_ids = ()
                        else:
                            active_count = explicit_count or 3
                            active_ids = all_ids[:active_count]
                            waiting_ids = all_ids[active_count:]

                        active_urls = tuple(
                            f"https://www.youtube.com/watch?v={video_id}"
                            for video_id in active_ids
                        )
                        waiting_urls = tuple(
                            f"https://www.youtube.com/watch?v={video_id}"
                            for video_id in waiting_ids
                        )
                        runtime_urls = active_urls + waiting_urls
                        if not active_urls:
                            raise WatchalongPlaylistError("Playlist 沒有可用影片。")

                        save_client_watchalong_source_mapping(
                            master=master,
                            playlist_url=playlist_url,
                            playlist_start_index=start_index,
                            source_urls=active_urls,
                            waiting_urls=waiting_urls,
                        )
                        starts = (
                            all_starts[: len(runtime_urls)]
                            if resolved_mode == "archive"
                            else ()
                        )
                        ptt_payload = _watchalong_timed("ptt", load_client_watchalong_ptt, master)
                        telemetry = new_client_watchalong_telemetry()
                        page = _watchalong_timed("render", build_watchalong_session_html,
                            master,
                            source_urls=runtime_urls,
                            episode_master_starts=starts,
                            live_queue_standby=(resolved_mode == "live"),
                            alignment=alignment,
                            ptt_messages=ptt_payload.messages,
                            telemetry=telemetry,
                            progressive_enabled=False,
                            progressive_requested=False,
                            ab_translation_enabled=False,
                        )
                    else:
                        alignment = _watchalong_timed("alignment", resolve_watchalong_alignment, master)
                        starts = alignment.starts[:1] if alignment is not None else ()
                        ptt_payload = _watchalong_timed("ptt", load_client_watchalong_ptt, master)
                        telemetry = new_client_watchalong_telemetry()
                        progressive_enabled = False
                        page = _watchalong_timed("render", build_watchalong_session_html,
                            master,
                            source,
                            episode_master_starts=starts,
                            live_queue_standby=(resolved_mode == "live"),
                            alignment=alignment,
                            ptt_messages=ptt_payload.messages,
                            telemetry=telemetry,
                            progressive_enabled=False,
                            progressive_requested=False,
                            ab_translation_enabled=False,
                        )
            except (
                ValueError,
                WatchalongPlaylistError,
                YoutubeApiKeyMissing,
                YoutubeMetadataError,
            ) as exc:
                self._html(
                    build_watchalong_landing_html(
                        recent_pool=load_recent_watchalong_cards(),
                        error=str(exc),
                        master_value=master,
                        source_value=source,
                        playlist_value=query.get("playlist", [""])[0],
                        playlist_start_value=1,
                    ),
                    HTTPStatus.BAD_REQUEST,
                )
                return
            self._html(page)
            return

        self._html(
            "<!doctype html><meta charset='utf-8'><title>404</title>"
            "<h1>404</h1><p>找不到這個 Client 頁面。</p>",
            HTTPStatus.NOT_FOUND,
        )

    def log_message(self, format: str, *args) -> None:
        return


def create_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ClientRequestHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hololive PTT Viewer Client UI")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--runtime-root",
        default="",
        help="Read-only runtime data root for DB/discovery sidecars; defaults to this checkout.",
    )
    args = parser.parse_args()
    if args.runtime_root:
        os.environ["PTT_CLIENT_RUNTIME_ROOT"] = args.runtime_root
    server = create_server(args.host, args.port)
    runtime_label = os.environ.get("PTT_CLIENT_RUNTIME_ROOT") or "this checkout"
    refresh_root = client_runtime_root()
    refresh_stop = None
    refresh_thread = None
    if os.environ.get("PTT_CLIENT_DISABLE_TODAY_REFRESH", "").strip() not in {"1", "true", "TRUE"}:
        refresh_stop, refresh_thread = _start_today_refresh_loop(str(refresh_root))
    print(f"Client UI: http://{args.host}:{args.port}/")
    print(f"Client runtime data: {runtime_label}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if refresh_stop is not None:
            refresh_stop.set()
        if refresh_thread is not None:
            refresh_thread.join(timeout=2)
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
