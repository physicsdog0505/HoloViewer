"""Validate an 8501 canonical Collab projection and emit bounded D1 SQL.

Offline only: this module never calls Cloudflare or opens a network connection.
The generated SQL targets only public_collab_events/public_collab_projection_meta.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

SCHEMA_VERSION = "public-collab-projection-v1"
EVENT_ID = re.compile(r"^[A-Za-z0-9:_-]{1,160}$")
STATUS = {"candidate", "approved", "needs_review"}


def q(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def validate(doc: dict) -> list[dict]:
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    revision = doc.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
        raise ValueError("invalid source_revision")
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
        streams = payload.get("streams")
        if not isinstance(streams, list) or len(streams) < 2:
            raise ValueError("published event requires >=2 POVs")
        if len({s.get("video_id") for s in streams if isinstance(s, dict)}) != len(streams):
            raise ValueError("duplicate/missing stream video_id")
        out.append(row)
    return out


def render_sql(doc: dict) -> str:
    rows = validate(doc)
    source = doc.get("source") or {}
    start = source.get("range_start")
    end = source.get("range_end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("source range missing")
    revision = doc["source_revision"]
    published = doc.get("generated_at")
    if not isinstance(published, str):
        raise ValueError("generated_at missing")

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
        "INSERT INTO public_collab_projection_meta(singleton,source_revision,published_at,source_event_count,effective_event_count) "
        f"VALUES(1,{q(revision)},{q(published)},{int(doc.get('source_event_count',len(rows)))},{int(doc.get('effective_event_count',len(rows)))}) "
        "ON CONFLICT(singleton) DO UPDATE SET source_revision=excluded.source_revision,"
        "published_at=excluded.published_at,source_event_count=excluded.source_event_count,"
        "effective_event_count=excluded.effective_event_count;"
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
