"""Persistent local archive-session store for Watchalong metadata.

This is deliberately separate from the authoritative PTT SQLite database.
``transcript_text`` remains a compatibility/session snapshot; reusable
transcript identity and versions are owned by ``TranscriptCorpus``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

from frontend_time import youtube_video_id


@dataclass(frozen=True, slots=True)
class SavedWatchalongSession:
    id: int
    master_url: str
    source_urls: tuple[str, ...]
    transcript_text: str
    transcript_sha256: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True, slots=True)
class SavedWatchalongSourceMapping:
    master_identity: str
    master_url: str
    playlist_url: str
    playlist_start_index: int
    source_urls: tuple[str, ...]
    waiting_urls: tuple[str, ...]
    updated_at_utc: str


def default_store_path(base_dir: str | Path = ".") -> Path:
    return Path(base_dir) / "data" / "watchalong" / "watchalong_archive.sqlite3"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS watchalong_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_url TEXT NOT NULL,
            source_urls_json TEXT NOT NULL,
            transcript_text TEXT NOT NULL,
            transcript_sha256 TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL,
            UNIQUE(master_url, transcript_sha256)
        );
        CREATE INDEX IF NOT EXISTS idx_watchalong_sessions_updated
        ON watchalong_sessions(updated_at_utc DESC);

        CREATE TABLE IF NOT EXISTS watchalong_source_mappings (
            master_identity TEXT PRIMARY KEY,
            master_url TEXT NOT NULL,
            playlist_url TEXT NOT NULL,
            playlist_start_index INTEGER NOT NULL,
            source_urls_json TEXT NOT NULL,
            waiting_urls_json TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        );
        """
    )
    return conn


def _row_to_session(row: tuple[object, ...]) -> SavedWatchalongSession:
    return SavedWatchalongSession(
        int(row[0]),
        str(row[1]),
        tuple(json.loads(str(row[2]))),
        str(row[3]),
        str(row[4]),
        str(row[5]),
        str(row[6]),
    )


def _master_identity(master_url: str) -> str:
    master = master_url.strip()
    if not master:
        raise ValueError("master_url must not be empty")
    return youtube_video_id(master) or master


def _row_to_source_mapping(row: tuple[object, ...]) -> SavedWatchalongSourceMapping:
    return SavedWatchalongSourceMapping(
        master_identity=str(row[0]),
        master_url=str(row[1]),
        playlist_url=str(row[2]),
        playlist_start_index=int(row[3]),
        source_urls=tuple(json.loads(str(row[4]))),
        waiting_urls=tuple(json.loads(str(row[5]))),
        updated_at_utc=str(row[6]),
    )


def save_watchalong_source_mapping(
    *,
    master_url: str,
    playlist_url: str,
    playlist_start_index: int,
    source_urls: list[str] | tuple[str, ...],
    waiting_urls: list[str] | tuple[str, ...] = (),
    path: str | Path | None = None,
) -> SavedWatchalongSourceMapping:
    master = master_url.strip()
    playlist = playlist_url.strip()
    sources = tuple(item.strip() for item in source_urls if item.strip())
    waiting = tuple(item.strip() for item in waiting_urls if item.strip())
    if not playlist:
        raise ValueError("playlist_url must not be empty")
    if playlist_start_index < 1:
        raise ValueError("playlist_start_index must be >= 1")
    if not sources:
        raise ValueError("at least one source URL is required")
    identity = _master_identity(master)
    db_path = Path(path) if path is not None else default_store_path()
    now = datetime.now(timezone.utc).isoformat()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO watchalong_source_mappings(
                master_identity, master_url, playlist_url, playlist_start_index,
                source_urls_json, waiting_urls_json, updated_at_utc
            ) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(master_identity) DO UPDATE SET
                master_url=excluded.master_url,
                playlist_url=excluded.playlist_url,
                playlist_start_index=excluded.playlist_start_index,
                source_urls_json=excluded.source_urls_json,
                waiting_urls_json=excluded.waiting_urls_json,
                updated_at_utc=excluded.updated_at_utc
            """,
            (
                identity,
                master,
                playlist,
                playlist_start_index,
                json.dumps(sources, ensure_ascii=False),
                json.dumps(waiting, ensure_ascii=False),
                now,
            ),
        )
    return SavedWatchalongSourceMapping(
        identity,
        master,
        playlist,
        playlist_start_index,
        sources,
        waiting,
        now,
    )


def load_watchalong_source_mapping(
    master_url: str,
    path: str | Path | None = None,
) -> SavedWatchalongSourceMapping | None:
    master = master_url.strip()
    if not master:
        return None
    identity = youtube_video_id(master) or master
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT master_identity, master_url, playlist_url, playlist_start_index,
                   source_urls_json, waiting_urls_json, updated_at_utc
            FROM watchalong_source_mappings
            WHERE master_identity=?
            """,
            (identity,),
        ).fetchone()
    return _row_to_source_mapping(row) if row else None


def load_latest_watchalong_source_mapping(
    path: str | Path | None = None,
) -> SavedWatchalongSourceMapping | None:
    """Load the newest saved source mapping, without creating a new store."""
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return None
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as conn:
        row = conn.execute(
            """
            SELECT master_identity, master_url, playlist_url, playlist_start_index,
                   source_urls_json, waiting_urls_json, updated_at_utc
            FROM watchalong_source_mappings
            ORDER BY updated_at_utc DESC, rowid DESC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_source_mapping(row) if row else None


def save_watchalong_session(
    *,
    master_url: str,
    source_urls: list[str] | tuple[str, ...],
    transcript_text: str,
    path: str | Path | None = None,
) -> SavedWatchalongSession:
    master = master_url.strip()
    sources = tuple(item.strip() for item in source_urls if item.strip())
    transcript = transcript_text.strip()
    if not master:
        raise ValueError("master_url must not be empty")
    if not sources:
        raise ValueError("at least one source URL is required")
    if not transcript:
        raise ValueError("transcript_text must not be empty")

    db_path = Path(path) if path is not None else default_store_path()
    now = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    payload = json.dumps(sources, ensure_ascii=False)

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, created_at_utc FROM watchalong_sessions WHERE master_url=? AND transcript_sha256=?",
            (master, digest),
        ).fetchone()
        if row:
            session_id, created_at = int(row[0]), str(row[1])
            conn.execute(
                "UPDATE watchalong_sessions SET source_urls_json=?, transcript_text=?, updated_at_utc=? WHERE id=?",
                (payload, transcript, now, session_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO watchalong_sessions(master_url, source_urls_json, transcript_text, transcript_sha256, created_at_utc, updated_at_utc) VALUES(?,?,?,?,?,?)",
                (master, payload, transcript, digest, now, now),
            )
            session_id = int(cur.lastrowid)
            created_at = now

    return SavedWatchalongSession(session_id, master, sources, transcript, digest, created_at, now)


def backup_store(path: str | Path | None = None, *, keep: int = 10) -> Path | None:
    """Create a consistent SQLite backup and rotate old snapshots."""
    if keep <= 0:
        raise ValueError("keep must be > 0")
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"watchalong_archive-{stamp}.sqlite3"
    with sqlite3.connect(db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    backups = sorted(backup_dir.glob("watchalong_archive-*.sqlite3"), reverse=True)
    for stale in backups[keep:]:
        stale.unlink(missing_ok=True)
    return target


def load_recent_sessions(path: str | Path | None = None, *, limit: int = 20) -> tuple[SavedWatchalongSession, ...]:
    if limit <= 0:
        return ()
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return ()
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, master_url, source_urls_json, transcript_text, transcript_sha256, created_at_utc, updated_at_utc FROM watchalong_sessions ORDER BY updated_at_utc DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return tuple(_row_to_session(row) for row in rows)


def load_latest_session_for_master(
    master_url: str,
    path: str | Path | None = None,
) -> SavedWatchalongSession | None:
    """Return the most recently saved session for one exact master URL."""
    master = master_url.strip()
    if not master:
        return None
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, master_url, source_urls_json, transcript_text, transcript_sha256, created_at_utc, updated_at_utc "
            "FROM watchalong_sessions WHERE master_url=? ORDER BY updated_at_utc DESC, id DESC LIMIT 1",
            (master,),
        ).fetchone()
    return _row_to_session(row) if row else None


def load_latest_session_for_master_identity(
    master_url: str,
    path: str | Path | None = None,
) -> SavedWatchalongSession | None:
    """Restore an exact session, then an equivalent canonical YouTube master."""
    exact = load_latest_session_for_master(master_url, path)
    if exact is not None:
        return exact
    video_id = youtube_video_id(master_url.strip())
    if video_id is None:
        return None
    db_path = Path(path) if path is not None else default_store_path()
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, master_url, source_urls_json, transcript_text, transcript_sha256, created_at_utc, updated_at_utc "
            "FROM watchalong_sessions ORDER BY updated_at_utc DESC, id DESC"
        ).fetchall()
    return next(
        (
            session
            for session in map(_row_to_session, rows)
            if youtube_video_id(session.master_url) == video_id
        ),
        None,
    )
