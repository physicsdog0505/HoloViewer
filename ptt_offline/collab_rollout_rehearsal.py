"""Disposable local rehearsal for the canonical Collab Production rollout.

Consumes one validated public-collab-projection-v1 artifact, creates a temporary
SQLite target, applies the proposed schema and rendered SQL, verifies idempotence
and next-live replacement semantics, then prints a machine-readable receipt.

No network and no Cloudflare/D1 mutation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from ptt_offline.collab_projection_import import render_sql, validate


def rehash(doc: dict) -> dict:
    source = doc["source"]
    basis = {
        "projection_key": doc["projection_key"],
        "range_start": source["range_start"],
        "range_end": source["range_end"],
        "detection_version": source["detection_version"],
        "events": doc["events"],
    }
    canonical = json.dumps(
        basis,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    doc["source_revision"] = "sha256:" + hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return doc


def next_empty_live(doc: dict) -> dict:
    nxt = deepcopy(doc)
    start = datetime.fromisoformat(
        doc["source"]["range_end"].replace("Z", "+00:00")
    )
    end = start + timedelta(days=1)
    nxt["source"]["range_start"] = start.isoformat()
    nxt["source"]["range_end"] = end.isoformat()
    nxt["generated_at"] = end.isoformat()
    nxt["events"] = []
    nxt["source_event_count"] = 0
    nxt["effective_event_count"] = 0
    return rehash(nxt)


def run_rehearsal(schema_path: Path, artifact_path: Path) -> dict:
    doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    events = validate(doc)
    first_sql = render_sql(doc)

    with tempfile.TemporaryDirectory(prefix="collab-rollout-") as tmp:
        db_path = Path(tmp) / "public.sqlite3"
        db = sqlite3.connect(db_path)
        try:
            db.executescript(schema_path.read_text(encoding="utf-8"))
            db.executescript(first_sql)

            event_rows = db.execute(
                "SELECT COUNT(*) FROM public_collab_events WHERE is_current=1"
            ).fetchone()[0]
            meta_rows = db.execute(
                "SELECT COUNT(*) FROM public_collab_projection_meta WHERE projection_key=?",
                (doc["projection_key"],),
            ).fetchone()[0]
            live_rows = db.execute(
                "SELECT COUNT(*) FROM public_collab_events WHERE is_current=1 AND live_scope=1"
            ).fetchone()[0]

            if event_rows != len(events):
                raise RuntimeError(f"event row mismatch: {event_rows} != {len(events)}")
            if meta_rows != 1:
                raise RuntimeError("projection meta row mismatch")

            db.executescript(first_sql)
            replay_event_rows = db.execute(
                "SELECT COUNT(*) FROM public_collab_events WHERE is_current=1"
            ).fetchone()[0]
            replay_meta_rows = db.execute(
                "SELECT COUNT(*) FROM public_collab_projection_meta WHERE projection_key=?",
                (doc["projection_key"],),
            ).fetchone()[0]
            if replay_event_rows != event_rows or replay_meta_rows != 1:
                raise RuntimeError("idempotent replay failed")

            cross_day = None
            if doc["projection_key"] == "live":
                nxt = next_empty_live(doc)
                db.executescript(render_sql(nxt))
                after_live = db.execute(
                    "SELECT COUNT(*) FROM public_collab_events WHERE is_current=1 AND live_scope=1"
                ).fetchone()[0]
                history_kept = db.execute(
                    "SELECT COUNT(*) FROM public_collab_events WHERE is_current=1"
                ).fetchone()[0]
                if after_live != 0:
                    raise RuntimeError("prior live membership survived next live projection")
                if history_kept != event_rows:
                    raise RuntimeError("next live projection retired canonical history")
                cross_day = {
                    "next_live_rows": after_live,
                    "history_rows_preserved": history_kept,
                    "pass": True,
                }
        finally:
            db.close()

    statements = [x.strip() for x in first_sql.split(";") if x.strip()]
    dml = [
        x for x in statements
        if x.upper().startswith(("UPDATE ", "INSERT "))
    ]
    return {
        "mode": "DISPOSABLE_LOCAL_REHEARSAL",
        "projection_key": doc["projection_key"],
        "source_revision": doc["source_revision"],
        "artifact_event_count": len(events),
        "initial_current_event_rows": event_rows,
        "initial_live_rows": live_rows,
        "projection_meta_rows": meta_rows,
        "idempotent_replay": True,
        "cross_day_live_replacement": cross_day,
        "sql_statement_count_including_begin_commit": len(statements),
        "sql_dml_statement_count": len(dml),
        "expected_dml_formula": len(events) + 2,
        "cloudflare_called": False,
        "production_mutated": False,
        "pass": True,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--schema", required=True)
    p.add_argument("--artifact", required=True)
    args = p.parse_args()

    receipt = run_rehearsal(Path(args.schema), Path(args.artifact))
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
