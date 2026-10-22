"""Validate an 8501 canonical Collab projection and emit bounded D1 SQL.

Offline only: this module never calls Cloudflare or opens a network connection.
The generated SQL targets only public_collab_events/public_collab_projection_meta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import re

SCHEMA_VERSION = "public-collab-projection-v1"
EVENT_ID = re.compile(r"^[A-Za-z0-9:_-]{1,160}$")
STATUS = {"candidate", "approved", "needs_review"}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PROJECTION_KEY = re.compile(r"^(?:live|history:\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2})$")
MAX_RANGE_DAYS = 31


def q(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("missing timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def validate(doc: dict) -> list[dict]:
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")

    projection_key = doc.get("projection_key")
    if not isinstance(projection_key, str) or not PROJECTION_KEY.fullmatch(projection_key):
        raise ValueError("invalid projection_key")

    revision = doc.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
        raise ValueError("invalid source_revision")

    source = doc.get("source")
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    start = _parse_time(source.get("range_start"))
    end = _parse_time(source.get("range_end"))
    if end <= start or (end - start).total_seconds() > MAX_RANGE_DAYS * 86400:
        raise ValueError("invalid/broad source range")
    detection_version = source.get("detection_version")
    if not isinstance(detection_version, str) or not detection_version:
        raise ValueError("missing detection_version")

    events = doc.get("events")
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    seen = set()
    out = []
    for row in events:
        if not isinstance(row, dict):
            raise ValueError("event row must be object")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
            raise ValueError("invalid event_id")
        if event_id in seen:
            raise ValueError("duplicate event_id")
        seen.add(event_id)
        if row.get("review_status") not in STATUS:
            raise ValueError("rejected/invalid event must not be published")
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("event_id") != event_id:
            raise ValueError("payload identity mismatch")
        if payload.get("event_key") != row.get("event_key"):
            raise ValueError("event_key mismatch")
        if payload.get("label") != row.get("label"):
            raise ValueError("label mismatch")
        if payload.get("confidence") != row.get("confidence"):
            raise ValueError("confidence mismatch")
        if payload.get("event_date") != row.get("event_date"):
            raise ValueError("event_date mismatch")
        if payload.get("event_start_at") != row.get("start_at"):
            raise ValueError("event start mismatch")
        if payload.get("event_end_at") != row.get("end_at"):
            raise ValueError("event end mismatch")
        streams = payload.get("streams")
        if not isinstance(streams, list) or len(streams) < 2:
            raise ValueError("published event requires >=2 POVs")
        video_ids = []
        for stream in streams:
            if not isinstance(stream, dict):
                raise ValueError("invalid stream row")
            video_id = stream.get("video_id")
            if not isinstance(video_id, str) or not VIDEO_ID.fullmatch(video_id):
                raise ValueError("invalid stream video_id")
            video_ids.append(video_id)
        if len(set(video_ids)) != len(video_ids):
            raise ValueError("duplicate stream video_id")
        out.append(row)

    source_count = doc.get("source_event_count")
    effective_count = doc.get("effective_event_count")
    if not isinstance(source_count, int) or not isinstance(effective_count, int):
        raise ValueError("invalid event counts")
    if effective_count != len(out) or source_count < effective_count:
        raise ValueError("event count mismatch")

    revision_basis = {
        "projection_key": projection_key,
        "range_start": source["range_start"],
        "range_end": source["range_end"],
        "detection_version": detection_version,
        "events": out,
    }
    canonical = json.dumps(
        revision_basis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if expected != revision:
        raise ValueError("source_revision mismatch")
    return out


def render_sql(doc: dict) -> str:
    rows = validate(doc)
    source = doc.get("source") or {}
    start = source.get("range_start")
    end = source.get("range_end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("source range missing")
    projection_key = doc["projection_key"]
    revision = doc["source_revision"]
    published = doc.get("generated_at")
    _parse_time(published)

    statements = [
        "BEGIN TRANSACTION;",
        f"UPDATE public_collab_events SET is_current=0 WHERE start_at>={q(start)} AND start_at<{q(end)};",
    ]
    for row in rows:
        payload_json = json.dumps(row["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        statements.append(
            "INSERT INTO public_collab_events("
            "event_id,event_key,label,confidence,event_date,start_at,end_at,review_status,"
            "payload_json,live_scope,is_current,source_revision,published_at"
            ") VALUES("
            + ",".join([
                q(row["event_id"]),q(row.get("event_key","")),q(row.get("label","")),
                q(row.get("confidence","candidate")),q(row["event_date"]),q(row["start_at"]),
                q(row["end_at"]),q(row["review_status"]),q(payload_json),
                "1" if row.get("live_scope") else "0","1",q(revision),q(published)
            ])
            + ") ON CONFLICT(event_id) DO UPDATE SET "
            "event_key=excluded.event_key,label=excluded.label,confidence=excluded.confidence,"
            "event_date=excluded.event_date,start_at=excluded.start_at,end_at=excluded.end_at,"
            "review_status=excluded.review_status,payload_json=excluded.payload_json,"
            "live_scope=excluded.live_scope,is_current=1,source_revision=excluded.source_revision,"
            "published_at=excluded.published_at;"
        )
    statements.append(
        "INSERT INTO public_collab_projection_meta(projection_key,source_revision,published_at,range_start,range_end,source_event_count,effective_event_count) "
        f"VALUES({q(projection_key)},{q(revision)},{q(published)},{q(start)},{q(end)},{int(doc.get('source_event_count',len(rows)))},{int(doc.get('effective_event_count',len(rows)))}) "
        "ON CONFLICT(projection_key) DO UPDATE SET source_revision=excluded.source_revision,"
        "published_at=excluded.published_at,range_start=excluded.range_start,range_end=excluded.range_end,"
        "source_event_count=excluded.source_event_count,effective_event_count=excluded.effective_event_count;"
    )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    doc=json.loads(Path(args.input).read_text(encoding="utf-8"))
    sql=render_sql(doc)
    Path(args.output).write_text(sql,encoding="utf-8")
    print(f"events={len(doc.get('events',[]))}")
    print(f"source_revision={doc.get('source_revision')}")
    print(f"output={args.output}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
