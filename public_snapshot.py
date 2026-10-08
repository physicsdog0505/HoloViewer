"""Read-only published snapshot contract for the isolated HoloViewer staging site.

No network requests, credential access, SQLite connection or private repo imports.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

KINDS = {"live", "upcoming", "ended"}
MAX_BYTES = 2_000_000
MAX_ITEMS = 500


def load_snapshot(path: Path) -> tuple[dict | None, str]:
    if not path.is_file() or path.is_symlink():
        return None, "No reviewed public snapshot has been published."
    if path.stat().st_size > MAX_BYTES:
        return None, "Snapshot exceeds published size limit."
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        return None, "Snapshot is unreadable."
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None, "Snapshot schema is not supported."
    stamp = raw.get("generated_at")
    if not isinstance(stamp, str) or not stamp.endswith("Z"):
        return None, "Snapshot freshness metadata is missing."
    try:
        generated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None, "Snapshot freshness metadata is invalid."
    if generated.tzinfo is None or generated.utcoffset().total_seconds() != 0:
        return None, "Snapshot freshness metadata must be UTC."
    if generated > datetime.now(timezone.utc):
        return None, "Snapshot is dated in the future."
    entries = raw.get("streams")
    if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
        return None, "Snapshot stream list is invalid."
    clean = []
    seen_ids = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return None, "Snapshot contains invalid stream records."
        if (not isinstance(entry.get("title"), str) or not entry["title"].strip()
                or not isinstance(entry.get("video_id"), str)
                or len(entry["video_id"]) != 11
                or not all(c.isascii() and (c.isalnum() or c in "_-") for c in entry["video_id"])
                or entry.get("status") not in KINDS
                or len(entry["title"]) > 200):
            return None, "Snapshot contains an invalid video record."
        if entry["video_id"] in seen_ids:
            return None, "Snapshot contains duplicate video records."
        seen_ids.add(entry["video_id"])
        clean.append({"title": entry["title"], "video_id": entry["video_id"], "status": entry["status"]})
    return {"generated_at": raw["generated_at"], "streams": clean}, ""
