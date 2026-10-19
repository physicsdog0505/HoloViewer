from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
STATES = {"collecting", "provisional", "verifying", "complete", "repair_needed", "retry_pending", "failed"}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def taipei_day(value: str) -> str:
    return parse_time(value).astimezone(TAIPEI).date().isoformat()


def validate_day(value: str) -> str:
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid ISO day")
    return value


def identity(source: str, row: dict) -> str:
    if source == "youtube":
        value = row.get("video_id")
        if not isinstance(value, str) or not value:
            raise ValueError("youtube video_id required")
        return value
    if source == "ptt":
        aid, line = row.get("aid"), row.get("source_line")
        if not isinstance(aid, str) or not aid or type(line) is not int or line < 1:
            raise ValueError("PTT aid and positive source_line required")
        return f"{row.get('day')}:{aid}:{line}"
    raise ValueError("unsupported source")
