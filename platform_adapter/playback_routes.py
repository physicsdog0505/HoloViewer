"""Playback-only route seam using unmodified accepted 4174 UI renderers.

The PTT region remains part of the original viewing layout. This module
does not manufacture PTT data or call local databases/YouTube metadata APIs.
"""
from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

def playback_handler(accepted_handler):
    """Subclass original handler; only intercept two custom-view GET pages."""

    class PlaybackOnlyHandler(accepted_handler):
        def do_GET(self):
            from client_custom_view import (
                build_custom_view_html,
                build_custom_view_session_html,
                custom_view_session_from_query,
            )
            parsed = urlsplit(self.path)
            if parsed.path == "/custom-view":
                from client_home import load_home_streams
                self._html(build_custom_view_html(live_streams=load_home_streams()[0]))
                return
            if parsed.path != "/custom-view/session":
                return super().do_GET()

            query = parse_qs(parsed.query)
            ptt_mode = query.get("ptt", ["live"])[0]
            try:
                if ptt_mode not in {"live", "video"}:
                    raise ValueError("不支援的 PTT 觀看版型。")
                # Reject pre-verified PTT coupling: no background Youtube metadata
                # lookup or arbitrary remote API subrequest in playback-only mode.
                if any(query.get(k) for k in ("ptt_aid", "ptt_api", "ptt_video_id")):
                    raise ValueError("PTT 同步尚未接通，請先使用一般播放器。")
                session = custom_view_session_from_query(
                    query.get("stream", []),
                    layout=query.get("layout", ["auto"])[0],
                    primary_index=int(query.get("primary", ["0"])[0]),
                    audio_master_index=int(query.get("audio", ["0"])[0]),
                )
            except (ValueError, TypeError) as exc:
                from client_home import load_home_streams
                self._html(
                    build_custom_view_html(error=str(exc), live_streams=load_home_streams()[0]),
                    HTTPStatus.BAD_REQUEST,
                )
                return

            # No player markup, CSS, control, or accepted layout is rewritten.
            # In live layout the original iframe stays in its original position;
            # its embedded view is intentionally blank until #48 is ready.
            self._html(build_custom_view_session_html(
                session,
                show_live_ptt=(ptt_mode == "live"),
            ))

    return PlaybackOnlyHandler
