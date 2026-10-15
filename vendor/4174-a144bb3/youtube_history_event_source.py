"""Read-only consolidated event adapter for Hololive YouTube history.

The UI contract intentionally does not expose SQLite table names or require a
fixed database path. History metadata remains authoritative for historical
video rows; an optional Stream Catalog supplies channel profile enrichment.
Both databases are opened read-only and this module never initializes/migrates
schemas.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class ConsolidatedYouTubeEvent:
    video_id: str
    channel_id: str
    channel_title: str
    title: str
    scheduled_start: str | None
    actual_start: str | None
    actual_end: str | None
    lifecycle_state: str
    is_live: bool
    avatar_url: str
    youtube_url: str


def _connect_read_only(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve(strict=True)
    db = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only = ON")
    return db


def _tables(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lifecycle(row: sqlite3.Row, *, now: datetime) -> str:
    if row["actual_end"]:
        return "ended"
    if row["actual_start"]:
        return "live"
    scheduled = _parse_time(row["scheduled_start"])
    if scheduled is not None and scheduled > now:
        return "upcoming"
    # History is_live means YouTube returned live/upcoming metadata at the last
    # observation; it is not by itself proof that an old row is live now.
    return "unknown"


class ConsolidatedYouTubeEventSource:
    """Stable read-only event surface for 4174 and other consumers."""

    def __init__(
        self,
        history_db: str | Path,
        *,
        catalog_db: str | Path | None = None,
    ) -> None:
        self.history_db = Path(history_db).expanduser()
        self.catalog_db = Path(catalog_db).expanduser() if catalog_db else None

    def _profiles(self, channel_ids: Iterable[str]) -> dict[str, tuple[str, str]]:
        ids = sorted({value for value in channel_ids if value})
        if not ids or self.catalog_db is None or not self.catalog_db.exists():
            return {}
        with _connect_read_only(self.catalog_db) as db:
            if "channels" not in _tables(db):
                return {}
            columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(channels)")
            }
            if not {"channel_id", "channel_name", "avatar_url"} <= columns:
                return {}
            result: dict[str, tuple[str, str]] = {}
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows = db.execute(
                    "SELECT channel_id,channel_name,avatar_url FROM channels "
                    f"WHERE channel_id IN ({placeholders})",
                    batch,
                )
                for row in rows:
                    result[str(row["channel_id"])] = (
                        str(row["channel_name"] or ""),
                        str(row["avatar_url"] or ""),
                    )
            return result

    def list_events(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        channel_ids: Iterable[str] | None = None,
        limit: int = 500,
        offset: int = 0,
        now: datetime | None = None,
    ) -> list[ConsolidatedYouTubeEvent]:
        if limit < 1 or limit > 5000 or offset < 0:
            raise ValueError("limit must be 1..5000 and offset must be >= 0")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)

        with _connect_read_only(self.history_db) as db:
            if "videos" not in _tables(db):
                raise ValueError("history database is missing videos")
            required = {
                "video_id", "channel_id", "title", "scheduled_start",
                "actual_start", "actual_end", "is_live", "url",
            }
            columns = {
                str(row[1]) for row in db.execute("PRAGMA table_info(videos)")
            }
            missing = required - columns
            if missing:
                raise ValueError(
                    "history videos schema missing: " + ", ".join(sorted(missing))
                )

            clauses: list[str] = []
            params: list[object] = []
            event_clock = "COALESCE(actual_start,scheduled_start,published_at)"
            if start:
                clauses.append(f"{event_clock} >= ?")
                params.append(start)
            if end:
                clauses.append(f"{event_clock} < ?")
                params.append(end)
            requested_channels = sorted(set(channel_ids or []))
            if requested_channels:
                placeholders = ",".join("?" for _ in requested_channels)
                clauses.append(f"channel_id IN ({placeholders})")
                params.extend(requested_channels)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = db.execute(
                "SELECT video_id,channel_id,title,scheduled_start,actual_start,"
                "actual_end,is_live,url FROM videos"
                + where
                + f" ORDER BY {event_clock} DESC, video_id DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()

        profiles = self._profiles(str(row["channel_id"]) for row in rows)
        result: list[ConsolidatedYouTubeEvent] = []
        for row in rows:
            channel_id = str(row["channel_id"])
            channel_title, avatar_url = profiles.get(channel_id, ("", ""))
            state = _lifecycle(row, now=current)
            result.append(
                ConsolidatedYouTubeEvent(
                    video_id=str(row["video_id"]),
                    channel_id=channel_id,
                    channel_title=channel_title,
                    title=str(row["title"] or ""),
                    scheduled_start=row["scheduled_start"],
                    actual_start=row["actual_start"],
                    actual_end=row["actual_end"],
                    lifecycle_state=state,
                    is_live=state == "live",
                    avatar_url=avatar_url,
                    youtube_url=str(row["url"] or ""),
                )
            )
        return result

    def get_event(
        self,
        video_id: str,
        *,
        now: datetime | None = None,
    ) -> ConsolidatedYouTubeEvent | None:
        if not video_id:
            raise ValueError("video_id is required")
        # video_id is the canonical identity, so a bounded filtered lookup is
        # sufficient without exposing SQL to callers.
        with _connect_read_only(self.history_db) as db:
            if "videos" not in _tables(db):
                raise ValueError("history database is missing videos")
            row = db.execute(
                "SELECT video_id,channel_id,title,scheduled_start,actual_start,"
                "actual_end,is_live,url FROM videos WHERE video_id=? LIMIT 1",
                (video_id,),
            ).fetchone()
        if row is None:
            return None
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        channel_id = str(row["channel_id"])
        channel_title, avatar_url = self._profiles([channel_id]).get(
            channel_id, ("", "")
        )
        state = _lifecycle(row, now=current)
        return ConsolidatedYouTubeEvent(
            video_id=str(row["video_id"]),
            channel_id=channel_id,
            channel_title=channel_title,
            title=str(row["title"] or ""),
            scheduled_start=row["scheduled_start"],
            actual_start=row["actual_start"],
            actual_end=row["actual_end"],
            lifecycle_state=state,
            is_live=state == "live",
            avatar_url=avatar_url,
            youtube_url=str(row["url"] or ""),
        )
