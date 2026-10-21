"""Validated read-only contracts for authoritative local recovery projections."""
from __future__ import annotations

import re

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")

_DAILY_SCHEMA = "holoviewer-admin-daily-recovery-v1"
_LIBRARY_SCHEMA = "holoviewer-authoritative-data-library-v1"


def _int(value, *, maximum=10_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError("invalid bounded count")
    return value


def _code(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not CODE_RE.fullmatch(value):
        raise ValueError("invalid bounded code")
    return value


def validate_daily_recovery(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("daily recovery object required")
    if value.get("schema_version") != _DAILY_SCHEMA or value.get("sanitized") is not True:
        raise ValueError("daily recovery schema/sanitization mismatch")
    day = value.get("target_day")
    if day is not None and (not isinstance(day, str) or not DAY_RE.fullmatch(day)):
        raise ValueError("invalid target day")
    overall = _code(value.get("overall_state"))
    youtube = value.get("youtube")
    ptt = value.get("ptt")
    transcript = value.get("transcript")
    translation = value.get("translation")
    if not all(isinstance(x, dict) for x in (youtube, ptt, transcript, translation)):
        raise ValueError("daily recovery domain blocks required")

    yt = {
        key: _int(youtube.get(key))
        for key in (
            "candidate_ids", "new_video_ids", "inserted", "updated", "unresolved",
            "playlist_calls", "video_lookup_calls", "search_calls",
        )
    }
    yt["status"] = _code(youtube.get("status"))
    if yt["search_calls"] != 0:
        raise ValueError("normal Daily Recovery must not use search.list")
    ids = youtube.get("unresolved_video_ids")
    if not isinstance(ids, list) or len(ids) > 200 or any(
        not isinstance(item, str) or not VIDEO_RE.fullmatch(item) for item in ids
    ):
        raise ValueError("invalid unresolved video IDs")
    yt["unresolved_video_ids"] = list(ids)

    pt = {
        key: _int(ptt.get(key))
        for key in ("expected_aids", "finalized", "repaired", "unresolved")
    }
    pt["state"] = _code(ptt.get("state"))
    pt["archive_job_status"] = _code(ptt.get("archive_job_status"))
    if not isinstance(ptt.get("readback_verified"), bool):
        raise ValueError("invalid PTT readback flag")
    pt["readback_verified"] = ptt["readback_verified"]
    pt["error_code"] = _code(ptt.get("error_code"), optional=True)

    tr = {
        key: _int(transcript.get(key))
        for key in (
            "due", "recovered", "already_complete", "no_public_caption",
            "retry_pending", "failed", "repaired_missing_binding",
        )
    }
    tx = {
        key: _int(translation.get(key))
        for key in (
            "due_requested_jobs", "resumed", "completed",
            "retry_pending", "failed", "not_requested",
        )
    }
    return {
        "schema_version": _DAILY_SCHEMA,
        "sanitized": True,
        "target_day": day,
        "last_run_at": value.get("last_run_at") if isinstance(value.get("last_run_at"), str) else None,
        "dry_run": value.get("dry_run") is True,
        "overall_state": overall,
        "youtube": yt,
        "ptt": pt,
        "transcript": tr,
        "translation": tx,
    }


def _optional_text(value, limit):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("invalid bounded text")
    return value


def validate_data_library(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("data library object required")
    if value.get("schema_version") != _LIBRARY_SCHEMA or value.get("sanitized") is not True:
        raise ValueError("data library schema/sanitization mismatch")
    rows = value.get("rows")
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise ValueError("invalid library rows")
    clean = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid library row")
        video_id = row.get("video_id")
        if not isinstance(video_id, str) or not VIDEO_RE.fullmatch(video_id) or video_id in seen:
            raise ValueError("invalid/duplicate video identity")
        seen.add(video_id)
        ptt = row.get("ptt")
        transcript = row.get("transcript")
        translation = row.get("translation")
        if not all(isinstance(x, dict) for x in (ptt, transcript, translation)):
            raise ValueError("library evidence blocks required")
        available = ptt.get("available")
        if available not in {True, False, None}:
            raise ValueError("invalid PTT availability")
        clean.append({
            "video_id": video_id,
            "channel_id": _optional_text(row.get("channel_id"), 64) or "",
            "title": _optional_text(row.get("title"), 500) or "",
            "youtube_url": _optional_text(row.get("youtube_url"), 200) or "",
            "published_at": _optional_text(row.get("published_at"), 64),
            "scheduled_start": _optional_text(row.get("scheduled_start"), 64),
            "actual_start": _optional_text(row.get("actual_start"), 64),
            "actual_end": _optional_text(row.get("actual_end"), 64),
            "lifecycle_state": _code(row.get("lifecycle_state")),
            "ptt": {
                "available": available,
                "completeness": _code(ptt.get("completeness")),
                "day": _optional_text(ptt.get("day"), 10),
            },
            "transcript": {
                "status": _code(transcript.get("status")),
                "transcript_id": _optional_text(transcript.get("transcript_id"), 128),
                "content_hash": _optional_text(transcript.get("content_hash"), 128),
                "source_type": _optional_text(transcript.get("source_type"), 40),
                "language": _optional_text(transcript.get("language"), 20),
                "observed_at": _optional_text(transcript.get("observed_at"), 64),
                "segment_count": (
                    _int(transcript.get("segment_count"))
                    if transcript.get("segment_count") is not None else None
                ),
            },
            "translation": {
                "status": _code(translation.get("status")),
                "artifact_id": _optional_text(translation.get("artifact_id"), 128),
                "transcript_hash": _optional_text(translation.get("transcript_hash"), 128),
                "job_status": _optional_text(translation.get("job_status"), 40),
            },
            "history_updated_at": _optional_text(row.get("history_updated_at"), 64),
            "reconciled_at": _optional_text(row.get("reconciled_at"), 64),
        })
    declared = value.get("row_count")
    if not isinstance(declared, int) or declared != len(clean):
        raise ValueError("library row count mismatch")
    return {
        "schema_version": _LIBRARY_SCHEMA,
        "sanitized": True,
        "reconciled_at": _optional_text(value.get("reconciled_at"), 64),
        "row_count": len(clean),
        "rows": clean,
    }
