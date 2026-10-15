"""Read-only SQLite queries for the Streamlit frontend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import sqlite3

from frontend_time import article_published_at, push_datetime


@dataclass(frozen=True)
class FrontendPush:
    article_id: int
    aid: str
    article_title: str
    article_url: str
    source_line: int
    kind: str
    author: str
    content: str
    occurred_at: datetime
    floor: int | None = None


def connect_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"找不到資料庫：{resolved}")
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _rows_to_pushes(rows) -> list[FrontendPush]:
    pushes = []
    for row in rows:
        occurred_at = push_datetime(
            row["ptt_date"], row["ptt_time"],
            article_title=row["title_hint"], article_url=row["url"],
        )
        keys = row.keys() if hasattr(row, "keys") else ()
        raw_floor = row["floor"] if "floor" in keys else None
        floor = int(raw_floor) if raw_floor is not None else None
        pushes.append(
            FrontendPush(
                article_id=int(row["article_id"]), aid=row["aid"],
                article_title=row["title_hint"], article_url=row["url"],
                source_line=int(row["source_line"]), kind=row["kind"],
                author=row["author"], content=row["content"],
                occurred_at=occurred_at,
                floor=floor,
            )
        )
    return pushes


def _collector_query(connection: sqlite3.Connection) -> str:
    has_screens = bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='article_screens'"
        ).fetchone()
    )
    screens_cond = (
        "EXISTS (SELECT 1 FROM article_screens WHERE article_id = p.article_id AND start_line <= 1)"
        if has_screens
        else "0"
    )
    return f"""
        WITH numbered_pushes AS (
            SELECT p.article_id, p.source_line, p.kind, p.author, p.content,
                   p.ptt_date, p.ptt_time, a.aid, a.url, a.title_hint,
                   CASE WHEN (
                        {screens_cond}
                        OR MIN(p.source_page) OVER (PARTITION BY p.article_id) <= 1
                   ) THEN ROW_NUMBER() OVER (PARTITION BY p.article_id ORDER BY p.source_line)
                   ELSE NULL END AS floor
            FROM pushes AS p
            JOIN articles AS a ON a.id = p.article_id
        )
        SELECT article_id, source_line, kind, author, content,
               ptt_date, ptt_time, aid, url, title_hint, floor
        FROM numbered_pushes
    """


def _live_timeline_sort_key(push: FrontendPush) -> tuple:
    """Sort realtime rows by visible time while keeping handoffs deterministic."""
    return (
        push.occurred_at,
        article_published_at(push.article_url),
        push.floor if push.floor is not None else push.source_line,
        push.aid,
    )


def latest_pushes(path: str | Path, limit: int = 300) -> list[FrontendPush]:
    """Return the newest pushes as one timeline across consecutive threads.

    Thread rollover is a storage detail. The realtime reader should keep the tail
    of the previous thread behind the new one, including any overlap around the
    handoff. The display limit therefore applies to the combined chronological
    timeline rather than to only the newest article.
    """
    if not Path(path).exists() or limit <= 0:
        return []
    with connect_read_only(path) as connection:
        query = _collector_query(connection)
        rows = connection.execute(
            query + " ORDER BY article_id, source_line"
        ).fetchall()
    pushes = sorted(_rows_to_pushes(rows), key=_live_timeline_sort_key)
    return pushes[-limit:]


def pushes_for_date(path: str | Path, selected: date) -> list[FrontendPush]:
    if not Path(path).exists():
        return []
    with connect_read_only(path) as connection:
        query = _collector_query(connection)
        rows = connection.execute(
            query + " ORDER BY article_id, source_line"
        ).fetchall()
    pushes = _rows_to_pushes(rows)
    return sorted(
        (push for push in pushes if push.occurred_at.date() == selected),
        key=_push_sort_key,
    )


def web_pushes_for_date(path: str | Path, selected: date) -> list[FrontendPush]:
    """Read one day from the isolated Web-backfill database.

    Web article ids are negated so they cannot collide with collector article
    ids when both sources are rendered in the same timeline.
    """
    if not Path(path).exists():
        return []
    with connect_read_only(path) as connection:
        rows = connection.execute(
            """
            SELECT p.web_article_id AS article_id, p.floor AS source_line,
                   p.floor, p.kind, p.author, p.content, p.ptt_date, p.ptt_time,
                   a.aid, a.source_url AS url, a.title AS title_hint
            FROM web_pushes AS p
            JOIN web_articles AS a ON a.id = p.web_article_id
            ORDER BY a.id, p.floor
            """
        ).fetchall()
    pushes = _rows_to_pushes(rows)
    selected_pushes = []
    for push in pushes:
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


def _push_dedup_key(push: FrontendPush) -> tuple:
    if push.floor is not None:
        return (push.aid, "floor", push.floor)
    return (push.aid, "content", push.author, push.occurred_at, push.content)


def _push_sort_key(push: FrontendPush) -> tuple:
    return (
        push.occurred_at,
        push.aid,
        push.floor if push.floor is not None else push.source_line,
    )


def merged_pushes_for_date(
    collector_path: str | Path, web_path: str | Path, selected: date
) -> list[FrontendPush]:
    """Merge collector and Web history; collector rows win duplicates."""
    web_pushes = web_pushes_for_date(web_path, selected)
    collector_pushes = pushes_for_date(collector_path, selected)
    merged = {_push_dedup_key(push): push for push in web_pushes}
    merged.update({_push_dedup_key(push): push for push in collector_pushes})
    return sorted(merged.values(), key=_push_sort_key)


def merged_pushes_for_window(
    collector_path: str | Path,
    web_path: str | Path,
    start: datetime,
    end: datetime,
) -> list[FrontendPush]:
    """Return a bounded deduplicated timeline for the requested window."""
    if end <= start:
        raise ValueError("時間窗結束時間必須晚於開始時間")

    # Keep this legacy/public entry point for existing callers, but delegate the
    # actual work to the bounded query path.  Import lazily because
    # frontend_sync_query reuses the row conversion/dedup helpers above.
    from frontend_sync_query import load_sync_window

    pushes, _timing = load_sync_window(collector_path, web_path, start, end)
    return pushes


def database_summary(path: str | Path) -> tuple[int, int]:
    if not Path(path).exists():
        return (0, 0)
    with connect_read_only(path) as connection:
        article_count = int(connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
        push_count = int(connection.execute("SELECT COUNT(*) FROM pushes").fetchone()[0])
    return article_count, push_count
