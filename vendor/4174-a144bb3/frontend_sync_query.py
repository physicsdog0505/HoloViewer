"""Bounded PTT window reads for the standalone single-stream sync page.

The legacy date helpers intentionally favor simplicity and materialize every push
before filtering by date.  That is fine for the normal history view, but it makes
an active livestream expensive because the old sync path also queried an 18-hour
future window.  This module keeps the same merge/dedup semantics while narrowing
SQLite work to the raw PTT dates that can actually contribute to the requested
window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter

from frontend_db import (
    FrontendPush,
    _push_dedup_key,
    _push_sort_key,
    _rows_to_pushes,
    connect_read_only,
)
from frontend_time import TAIPEI


@dataclass(frozen=True)
class SyncQueryTiming:
    collector_seconds: float
    web_seconds: float
    merge_seconds: float
    total_seconds: float
    dates_read: int
    push_count: int


def _raw_ptt_dates(selected: date) -> tuple[str, ...]:
    """Return raw MM/DD values that can normalize to *selected*.

    A small amount of imported history used overflow dates such as 09/31 for
    10/01.  Keep that compatibility without materializing every row in the DB.
    """
    values = {selected.strftime("%m/%d")}
    if selected.day == 1:
        previous_month_last = selected - timedelta(days=1)
        values.add(
            f"{previous_month_last.month:02d}/{previous_month_last.day + 1:02d}"
        )
    return tuple(sorted(values))


def _collector_pushes_for_date(path: str | Path, selected: date) -> list[FrontendPush]:
    resolved = Path(path)
    if not resolved.exists():
        return []
    raw_dates = _raw_ptt_dates(selected)
    placeholders = ",".join("?" for _ in raw_dates)
    with connect_read_only(resolved) as connection:
        has_screens = bool(
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_screens'"
            ).fetchone()
        )
        screens_cond = (
            "EXISTS (SELECT 1 FROM article_screens "
            "WHERE article_id = p.article_id AND start_line <= 1)"
            if has_screens else "0"
        )
        # Select target article ids first. Window functions still see every push
        # in those articles, preserving floor numbering across midnight, while
        # avoiding a sort/window pass over unrelated history.
        rows = connection.execute(
            f"""
            WITH target_articles AS (
                SELECT DISTINCT article_id
                FROM pushes
                WHERE ptt_date IN ({placeholders})
            ), numbered_pushes AS (
                SELECT p.article_id, p.source_line, p.kind, p.author, p.content,
                       p.ptt_date, p.ptt_time, a.aid, a.url, a.title_hint,
                       CASE WHEN (
                            {screens_cond}
                            OR MIN(p.source_page) OVER (PARTITION BY p.article_id) <= 1
                       ) THEN ROW_NUMBER() OVER (
                            PARTITION BY p.article_id ORDER BY p.source_line
                       ) ELSE NULL END AS floor
                FROM pushes AS p
                JOIN target_articles AS t ON t.article_id = p.article_id
                JOIN articles AS a ON a.id = p.article_id
            )
            SELECT article_id, source_line, kind, author, content,
                   ptt_date, ptt_time, aid, url, title_hint, floor
            FROM numbered_pushes
            WHERE ptt_date IN ({placeholders})
            ORDER BY article_id, source_line
            """,
            (*raw_dates, *raw_dates),
        ).fetchall()
    pushes = _rows_to_pushes(rows)
    return sorted(
        (push for push in pushes if push.occurred_at.date() == selected),
        key=_push_sort_key,
    )


def _web_pushes_for_date(path: str | Path, selected: date) -> list[FrontendPush]:
    resolved = Path(path)
    if not resolved.exists():
        return []
    raw_dates = _raw_ptt_dates(selected)
    placeholders = ",".join("?" for _ in raw_dates)
    with connect_read_only(resolved) as connection:
        rows = connection.execute(
            f"""
            SELECT p.web_article_id AS article_id, p.floor AS source_line,
                   p.floor, p.kind, p.author, p.content, p.ptt_date, p.ptt_time,
                   a.aid, a.source_url AS url, a.title AS title_hint
            FROM web_pushes AS p
            JOIN web_articles AS a ON a.id = p.web_article_id
            WHERE p.ptt_date IN ({placeholders})
            ORDER BY a.id, p.floor
            """,
            raw_dates,
        ).fetchall()
    selected_pushes: list[FrontendPush] = []
    for push in _rows_to_pushes(rows):
        if push.occurred_at.date() != selected:
            continue
        selected_pushes.append(
            FrontendPush(
                article_id=-push.article_id,
                aid=push.aid,
                article_title=push.article_title,
                article_url=push.article_url,
                source_line=push.source_line,
                kind=push.kind,
                author=push.author,
                content=push.content,
                occurred_at=push.occurred_at,
                floor=push.floor,
            )
        )
    return selected_pushes


def load_sync_window(
    collector_path: str | Path,
    web_path: str | Path,
    start: datetime,
    end: datetime,
) -> tuple[list[FrontendPush], SyncQueryTiming]:
    """Read a bounded timeline and expose enough timing to diagnose slow loads."""
    if end <= start:
        return [], SyncQueryTiming(0.0, 0.0, 0.0, 0.0, 0, 0)

    started = perf_counter()
    collector_seconds = 0.0
    web_seconds = 0.0
    merge_seconds = 0.0
    dates_read = 0
    merged: dict[tuple, FrontendPush] = {}

    # PTT rows are calendar-local Asia/Taipei values. YouTube metadata is often
    # UTC, so derive the lookup dates only after converting both window edges.
    current = start.astimezone(TAIPEI).date()
    last = end.astimezone(TAIPEI).date()
    while current <= last:
        dates_read += 1
        tick = perf_counter()
        web_pushes = _web_pushes_for_date(web_path, current)
        web_seconds += perf_counter() - tick

        tick = perf_counter()
        collector_pushes = _collector_pushes_for_date(collector_path, current)
        collector_seconds += perf_counter() - tick

        tick = perf_counter()
        for push in web_pushes:
            merged[_push_dedup_key(push)] = push
        # Collector rows win duplicates, matching merged_pushes_for_date().
        for push in collector_pushes:
            merged[_push_dedup_key(push)] = push
        merge_seconds += perf_counter() - tick
        current += timedelta(days=1)

    minute_start = start.replace(second=0, microsecond=0)
    tick = perf_counter()
    pushes = sorted(
        (push for push in merged.values() if minute_start <= push.occurred_at <= end),
        key=_push_sort_key,
    )
    merge_seconds += perf_counter() - tick
    total = perf_counter() - started
    return pushes, SyncQueryTiming(
        collector_seconds=collector_seconds,
        web_seconds=web_seconds,
        merge_seconds=merge_seconds,
        total_seconds=total,
        dates_read=dates_read,
        push_count=len(pushes),
    )
