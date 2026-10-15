"""Read-only Stream Catalog projection helpers for the standalone Client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
from urllib.parse import quote

from frontend_time import TAIPEI


@dataclass(frozen=True, slots=True)
class ClientCatalogStream:
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    avatar_url: str
    lifecycle_state: str
    scheduled_start: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    last_checked_at: datetime | None = None


LIVE_OBSERVATION_FRESHNESS = timedelta(minutes=20)


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def catalog_path(runtime_root: str | Path) -> Path:
    return Path(runtime_root).expanduser().resolve() / "hololive_stream_catalog.sqlite3"


def load_client_catalog_streams(
    runtime_root: str | Path,
    *,
    now: datetime,
) -> tuple[ClientCatalogStream, ...]:
    """Return only rows eligible for the Client Today surface.

    LIVE is date-independent. Ended rows use a Taipei-noon previous-day grace
    window. Upcoming rows are current-day/future only. No external refresh occurs.
    """

    current = now if now.tzinfo is not None else now.replace(tzinfo=TAIPEI)
    current = current.astimezone(TAIPEI)
    path = catalog_path(runtime_root)
    if not path.exists():
        return ()

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        stream_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(streams)")
        }
        checked_expr = (
            "s.last_checked_at"
            if "last_checked_at" in stream_columns
            else "NULL"
        )
        rows = connection.execute(
            f"""
            SELECT
                s.video_id, s.title, s.channel_id, s.scheduled_start,
                s.actual_start, s.actual_end, s.lifecycle_state,
                {checked_expr} AS last_checked_at,
                c.channel_name, c.avatar_url
            FROM streams AS s
            LEFT JOIN channels AS c ON c.channel_id = s.channel_id
            WHERE s.lifecycle_state IN ('live', 'upcoming', 'ended')
            ORDER BY s.video_id
            """
        ).fetchall()
    finally:
        connection.close()

    today = current.date()
    yesterday = today - timedelta(days=1)
    before_noon = current.timetz().replace(tzinfo=None) < time(12, 0)
    result: list[ClientCatalogStream] = []
    for row in rows:
        state = str(row["lifecycle_state"] or "")
        scheduled = _parse(row["scheduled_start"])
        actual_start = _parse(row["actual_start"])
        actual_end = _parse(row["actual_end"])
        last_checked_at = _parse(row["last_checked_at"])

        include = False
        if state == "live":
            if "last_checked_at" in stream_columns:
                age = (
                    current.astimezone(timezone.utc)
                    - last_checked_at.astimezone(timezone.utc)
                    if last_checked_at is not None
                    else None
                )
                include = bool(
                    age is not None
                    and timedelta(0) <= age <= LIVE_OBSERVATION_FRESHNESS
                )
            else:
                # Legacy/read-only fixtures without the observation column retain
                # their former behavior. Production catalogs have last_checked_at.
                include = True
        elif state == "upcoming":
            reference = (scheduled or actual_start)
            include = reference is None or reference.astimezone(TAIPEI).date() >= today
        elif state == "ended" and actual_end is not None:
            ended_day = actual_end.astimezone(TAIPEI).date()
            include = ended_day == today or (before_noon and ended_day == yesterday)

        if not include:
            continue
        result.append(
            ClientCatalogStream(
                video_id=str(row["video_id"] or ""),
                title=str(row["title"] or ""),
                channel_id=str(row["channel_id"] or ""),
                channel_name=str(row["channel_name"] or ""),
                avatar_url=str(row["avatar_url"] or ""),
                lifecycle_state=state,
                scheduled_start=scheduled,
                actual_start=actual_start,
                actual_end=actual_end,
                last_checked_at=last_checked_at,
            )
        )
    return tuple(item for item in result if item.video_id)


def load_client_catalog_metadata(
    runtime_root: str | Path,
    video_ids: set[str] | tuple[str, ...] | list[str],
) -> dict[str, ClientCatalogStream]:
    """Load identity/metadata for known video ids without Today freshness filtering.

    This is enrichment only. Callers must not use these rows as fresh lifecycle
    evidence; it exists so stale-but-still-listed discovery cards keep canonical
    channel_id, avatar and support-color identity.
    """
    wanted = tuple(dict.fromkeys(str(value) for value in video_ids if str(value)))
    if not wanted:
        return {}
    path = catalog_path(runtime_root)
    if not path.is_file():
        return {}
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        stream_columns = {
            str(item[1]) for item in connection.execute("PRAGMA table_info(streams)")
        }
        checked_expr = "s.last_checked_at" if "last_checked_at" in stream_columns else "NULL"
        placeholders = ",".join("?" for _ in wanted)
        rows = connection.execute(
            f"""SELECT s.video_id,s.title,s.channel_id,s.scheduled_start,
                      s.actual_start,s.actual_end,s.lifecycle_state,
                      {checked_expr} AS last_checked_at,
                      c.channel_name,c.avatar_url
               FROM streams s
               LEFT JOIN channels c ON c.channel_id=s.channel_id
               WHERE s.video_id IN ({placeholders})""",
            wanted,
        ).fetchall()
    finally:
        connection.close()
    result: dict[str, ClientCatalogStream] = {}
    for row in rows:
        item = ClientCatalogStream(
            video_id=str(row["video_id"] or ""),
            title=str(row["title"] or ""),
            channel_id=str(row["channel_id"] or ""),
            channel_name=str(row["channel_name"] or ""),
            avatar_url=str(row["avatar_url"] or ""),
            lifecycle_state=str(row["lifecycle_state"] or ""),
            scheduled_start=_parse(row["scheduled_start"]),
            actual_start=_parse(row["actual_start"]),
            actual_end=_parse(row["actual_end"]),
            last_checked_at=_parse(row["last_checked_at"]),
        )
        if item.video_id:
            result[item.video_id] = item
    return result


def load_client_catalog_video(
    runtime_root: str | Path, video_id: str
) -> ClientCatalogStream | None:
    """Read one dated VOD independent of Today's limited display window.

    This is read-only. Never infer channel identity from titles.
    """
    if not video_id:
        return None
    path = catalog_path(runtime_root)
    if not path.is_file():
        return None
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        stream_columns = {
            str(item[1]) for item in connection.execute("PRAGMA table_info(streams)")
        }
        checked_expr = (
            "s.last_checked_at"
            if "last_checked_at" in stream_columns
            else "NULL"
        )
        row = connection.execute(
            f"""SELECT s.video_id,s.title,s.channel_id,s.scheduled_start,
                      s.actual_start,s.actual_end,s.lifecycle_state,
                      {checked_expr} AS last_checked_at,
                      c.channel_name,c.avatar_url
               FROM streams s
               LEFT JOIN channels c ON c.channel_id=s.channel_id
               WHERE s.video_id=? LIMIT 1""",
            (video_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return ClientCatalogStream(
        video_id=str(row["video_id"] or ""),
        title=str(row["title"] or ""),
        channel_id=str(row["channel_id"] or ""),
        channel_name=str(row["channel_name"] or ""),
        avatar_url=str(row["avatar_url"] or ""),
        lifecycle_state=str(row["lifecycle_state"] or ""),
        scheduled_start=_parse(row["scheduled_start"]),
        actual_start=_parse(row["actual_start"]),
        actual_end=_parse(row["actual_end"]),
        last_checked_at=_parse(row["last_checked_at"]),
    )

