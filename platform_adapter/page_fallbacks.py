"""Accepted 4174 page-first fallbacks for temporarily unavailable providers.

These functions render only original 4174 UI builders with empty/explicit data.
They never synthesize backend records and never touch local runtime databases.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from frontend_time import TAIPEI


def render_page_fallback(target: str) -> tuple[int, str] | None:
    parsed = urlsplit(target)
    query = parse_qs(parsed.query)
    today = datetime.now(TAIPEI).date()

    if parsed.path == "/":
        from client_home import build_home_html
        return 200, build_home_html([], [], [], [], today_label=today.strftime("%Y/%m/%d"))

    if parsed.path == "/history":
        from client_history import build_history_day_html, parse_history_day
        try:
            selected = parse_history_day(query.get("date", [today.isoformat()])[0])
            page = int(query.get("page", ["1"])[0])
        except (ValueError, OverflowError):
            selected, page = today, 1
        return 200, build_history_day_html(
            selected, [], page=max(1, page), has_more=False,
            error="歷史資料暫未接通。"
        )

    if parsed.path == "/custom-view":
        from client_custom_view import build_custom_view_html
        return 200, build_custom_view_html(live_streams=[])

    if parsed.path == "/custom-view/session":
        from client_custom_view import (
            build_custom_view_html,
            build_custom_view_session_html,
            custom_view_session_from_query,
        )
        try:
            session = custom_view_session_from_query(
                query.get("stream", []),
                layout=query.get("layout", ["auto"])[0],
                primary_index=int(query.get("primary", ["0"])[0]),
                audio_master_index=int(query.get("audio", ["0"])[0]),
            )
        except (ValueError, TypeError):
            return 200, build_custom_view_html(
                error="直播資料暫未接通，可直接貼上 YouTube 網址建立觀看。",
                live_streams=[],
            )
        return 200, build_custom_view_session_html(
            session,
            show_live_ptt=query.get("ptt", ["live"])[0] == "live",
        )

    if parsed.path == "/collab":
        from client_home import build_collab_hub_html
        return 200, build_collab_hub_html([], [], [])

    if parsed.path == "/collab/session":
        from client_custom_view import (
            build_custom_view_html,
            build_custom_view_session_html,
            custom_view_session_from_query,
        )
        try:
            session = custom_view_session_from_query(
                query.get("stream", []),
                layout="auto",
                primary_index=0,
                audio_master_index=0,
            )
        except (ValueError, TypeError):
            return 200, build_custom_view_html(
                error="多人連動資料暫未接通。",
                live_streams=[],
            )
        return 200, build_custom_view_session_html(
            session,
            show_live_ptt=True,
            ptt_alignment_notice="多人連動資料暫未接通；目前只顯示明確指定的 POV。",
        )

    if parsed.path == "/ptt-today":
        from client_ptt_today import build_ptt_today_focus_html, build_ptt_today_page_html
        if query.get("focus", ["0"])[0] == "1":
            return 200, build_ptt_today_focus_html(
                [], today, embedded=query.get("embed", ["0"])[0] == "1"
            )
        return 200, build_ptt_today_page_html([], today)

    if parsed.path == "/watchalong":
        from client_watchalong import build_watchalong_landing_html
        return 200, build_watchalong_landing_html(
            recent_pool=(),
            error="同時視聽資料暫未接通；頁面功能會在資料服務接上後恢復。",
            master_value=query.get("master", [""])[0],
        )

    if parsed.path == "/watchalong/session":
        # Page-first: until Watchalong providers are connected, never import or
        # execute the heavyweight session/translation/runtime path. Preserve
        # the user's inputs and return the accepted 4174 builder page instead.
        from client_watchalong import build_watchalong_landing_html
        master = query.get("master", [""])[0]
        source = query.get("source", [""])[0]
        return 200, build_watchalong_landing_html(
            recent_pool=(),
            error="同時視聽資料暫未接通；設定已保留，可返回修改。",
            master_value=master,
            source_value=source,
        )

    return None
