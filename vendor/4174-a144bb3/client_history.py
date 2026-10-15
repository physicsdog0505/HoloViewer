"""4174 historical day browser. Read-only, bounded, no provider calls."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from html import escape
import os
import sqlite3
from urllib.parse import quote
from pathlib import Path
from urllib.parse import urlencode

from client_home import HomeStream, _stream_card, build_home_html
from client_runtime import client_runtime_root
from client_stream_catalog import catalog_path
from frontend_time import TAIPEI
from youtube_history_event_source import ConsolidatedYouTubeEventSource, _parse_time


PAGE_SIZE = 50
DAYS_WINDOW = 30


def history_day_bounds(now: datetime | None = None) -> tuple[date, date]:
    today = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date()
    return today - timedelta(days=DAYS_WINDOW), today - timedelta(days=1)


def parse_history_day(raw: str, *, now: datetime | None = None) -> date:
    earliest, latest = history_day_bounds(now)
    selected = date.fromisoformat(raw) if raw else latest
    if not earliest <= selected <= latest:
        raise ValueError("僅能瀏覽最近 30 天已結束的日期。")
    return selected


def history_database_path() -> Path:
    override = os.environ.get("PTT_CLIENT_HISTORY_DB", "").strip()
    if override:
        return Path(override).expanduser()
    # Existing 66-channel metadata cache; never initialize/copy a DB.
    runtime = client_runtime_root()
    local = runtime / ".holoviewer" / "hololive_history_66.sqlite3"
    if local.is_file():
        return local
    return Path.home() / ".holoviewer" / "hololive_history_66.sqlite3"


def _datetime_for_event(event) -> tuple[datetime | None, str]:
    for field, label in (("actual_start", "實際開始"), ("scheduled_start", "預定開始")):
        value = _parse_time(getattr(event, field))
        if value is not None:
            return value.astimezone(TAIPEI), label
    return None, ""


def _catalog_history_day(selected: date, *, page: int, root: Path) -> tuple[list[HomeStream], bool]:
    """Fallback to verified ended Stream Catalog VODs without provider calls."""
    path = catalog_path(root)
    if not path.is_file():
        return [], False
    begin = datetime.combine(selected, time.min, TAIPEI).astimezone(timezone.utc)
    finish = begin + timedelta(days=1)
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            """SELECT s.video_id,s.title,s.channel_id,s.actual_start,
                      s.scheduled_start,c.channel_name,c.avatar_url
               FROM streams s LEFT JOIN channels c ON c.channel_id=s.channel_id
               WHERE s.lifecycle_state='ended' AND s.actual_end IS NOT NULL
                 AND COALESCE(s.actual_start,s.scheduled_start)>=?
                 AND COALESCE(s.actual_start,s.scheduled_start)<?
               ORDER BY COALESCE(s.actual_start,s.scheduled_start) DESC,s.video_id DESC
               LIMIT ? OFFSET ?""",
            (begin.isoformat(), finish.isoformat(), PAGE_SIZE, (page-1)*PAGE_SIZE),
        ).fetchall()
    cards = []
    for row in rows:
        at = _parse_time(row["actual_start"] or row["scheduled_start"])
        if at is None or at.astimezone(TAIPEI).date() != selected:
            continue
        local = at.astimezone(TAIPEI)
        cards.append(HomeStream(
            video_id=str(row["video_id"]), title=str(row["title"] or ""),
            channel_id=str(row["channel_id"] or ""),
            channel_title=str(row["channel_name"] or ""),
            avatar_url=str(row["avatar_url"] or ""),
            start_label=local.strftime("%H:%M") + ("（預定）" if not row["actual_start"] else ""),
            state="ended", start_at=local,
        ))
    return cards, len(rows) == PAGE_SIZE


def _history_row_to_card(event, selected: date) -> HomeStream | None:
    at, provenance = _datetime_for_event(event)
    if at is None or at.date() != selected or event.lifecycle_state != "ended":
        return None
    return HomeStream(
        video_id=event.video_id, title=event.title,
        channel_title=event.channel_title, channel_id=event.channel_id,
        avatar_url=event.avatar_url,
        start_label=at.strftime("%H:%M") + ("（預定）" if provenance == "預定開始" else ""),
        state="ended", start_at=at,
    )


MAX_DAY_ROWS_PER_SOURCE = 1000


def load_history_day(
    selected: date,
    *,
    page: int = 1,
    source: ConsolidatedYouTubeEventSource | None = None,
) -> tuple[list[HomeStream], bool]:
    """Merge durable historical and operational streams, not source-level fallbacks.

    Both sources are read-only and independently bounded to the selected day.
    Pagination happens after de-duplication so an overlapping video never
    appears twice or consumes a page slot. No YouTube/provider calls occur.
    """
    if page < 1 or page > MAX_DAY_ROWS_PER_SOURCE // PAGE_SIZE:
        raise ValueError("歷史頁數超出單日安全查詢上限。")
    root = client_runtime_root()
    if source is None:
        catalog_db = catalog_path(root)
        provider = ConsolidatedYouTubeEventSource(
            history_database_path(),
            catalog_db=catalog_db if catalog_db.is_file() else None,
        )
    else:
        provider = source
    begin = datetime.combine(selected, time.min, TAIPEI).astimezone(timezone.utc)
    finish = begin + timedelta(days=1)
    merged: dict[str, HomeStream] = {}

    # History 66's canonical historical rows provide the initial projection.
    # A recently ended stream might still lack actual_end in History 66.
    for offset in range(0, MAX_DAY_ROWS_PER_SOURCE, PAGE_SIZE):
        try:
            rows = provider.list_events(
                start=begin.isoformat(), end=finish.isoformat(),
                limit=PAGE_SIZE, offset=offset,
            )
        except (OSError, sqlite3.Error, ValueError):
            if source is not None:
                raise
            break  # Catalog remains available when History 66 is absent.
        for event in rows:
            card = _history_row_to_card(event, selected)
            if card:
                merged[card.video_id] = card
        if len(rows) < PAGE_SIZE:
            break

    if source is None:
        # This is a union, not a fallback. Every verified-ended catalog row
        # participates, including when History 66 already has some videos.
        for catalog_page in range(1, MAX_DAY_ROWS_PER_SOURCE // PAGE_SIZE + 1):
            try:
                rows, more = _catalog_history_day(
                    selected, page=catalog_page, root=root,
                )
            except (OSError, sqlite3.Error, ValueError):
                # An unavailable/incompatible optional Catalog cannot erase
                # valid historical rows already loaded from History 66.
                break
            for card in rows:
                prior = merged.get(card.video_id)
                # Catalog may have more recent lifecycle evidence. Preserve a
                # useful History 66 title/profile if the Catalog lacks it.
                if prior is not None:
                    card = HomeStream(
                        video_id=card.video_id,
                        title=card.title or prior.title,
                        channel_title=card.channel_title or prior.channel_title,
                        channel_id=card.channel_id or prior.channel_id,
                        avatar_url=card.avatar_url or prior.avatar_url,
                        start_label=card.start_label,
                        state="ended", start_at=card.start_at,
                    )
                merged[card.video_id] = card
            if not more:
                break

    ordered = sorted(
        merged.values(),
        key=lambda card: (card.start_at or datetime.min.replace(tzinfo=TAIPEI), card.video_id),
        reverse=True,
    )
    start_index = (page - 1) * PAGE_SIZE
    return ordered[start_index:start_index + PAGE_SIZE], len(ordered) > start_index + PAGE_SIZE


def build_history_day_html(
    selected: date,
    cards: list[HomeStream],
    *,
    page: int,
    has_more: bool,
    error: str = "",
    now: datetime | None = None,
) -> str:
    earliest, latest = history_day_bounds(now)
    date_iso = selected.isoformat()
    links = []
    for caption, day in (
        ("昨天", latest),
        ("前天", latest - timedelta(days=1)),
        ("7 天前", latest - timedelta(days=6)),
        ("← 前一天", selected - timedelta(days=1)),
        ("後一天 →", selected + timedelta(days=1)),
    ):
        if earliest <= day <= latest:
            links.append('<a class="subtle-action" href="/history?'
                         + urlencode({"date": day.isoformat()}) + '">' + caption + '</a>')
    picker = (
        '<form action="/history" method="get" class="history-picker">'
        '<label for="historyDate">選擇日期</label>'
        f'<input id="historyDate" name="date" type="date" value="{date_iso}" '
        f'min="{earliest.isoformat()}" max="{latest.isoformat()}" required>'
        '<button class="primary-action" type="submit">查看</button></form>'
    )
    notice = '<p class="form-error">' + escape(error) + '</p>' if error else ""
    if cards:
        card_html = '<div class="client-grid">' + "".join(_stream_card(card) for card in cards) + '</div>'
    else:
        card_html = '<p class="empty-note">這一天沒有可顯示的已結束直播，或歷史資料尚未接入。</p>'
    pagination = []
    if page > 1:
        pagination.append('<a class="subtle-action" href="/history?' +
                          urlencode({"date": date_iso, "page": page - 1}) + '">上一頁</a>')
    if has_more:
        pagination.append('<a class="subtle-action" href="/history?' +
                          urlencode({"date": date_iso, "page": page + 1}) + '">下一頁</a>')
    content = (
        '<div id="homeDynamic"><div class="page-head"><div><h1>歷史直播</h1>'
        '<p>依直播開始日期瀏覽最近 30 天的已結束影片。</p></div></div>'
        + picker + '<div class="history-shortcuts">' + "".join(links) + '</div>'
        + notice + '<section class="section"><div class="section-head"><div><h2>'
        + escape(selected.strftime("%Y/%m/%d"))
        + '</h2></div></div>' + card_html + '</section>'
        + '<nav class="history-shortcuts" aria-label="歷史直播分頁">'
        + "".join(pagination) + '</nav></div>'
    )
    return build_home_html(
        [], [], [], today_label=selected.strftime("%Y/%m/%d"),
        history_content=content,
    )
