"""Read-only preflight for PR #197 Collab Production rollout.

This tool never contacts Cloudflare and never mutates D1.
It validates the owner-confirmed API Wrangler config, a generated projection
artifact, and the rendered SQL so #45 can review the exact mutation envelope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

EXPECTED_WORKER = "holoviewer-public-api"
EXPECTED_DB_NAME = "holoviewer-public-v1"
EXPECTED_DB_ID = "64e1a0ee-1455-4377-9640-3922e8f4d061"
EXPECTED_CRON = "* * * * *"
EXPECTED_COMPATIBILITY_DATE = "2026-10-14"

DESTRUCTIVE_SQL = re.compile(r"\b(DROP|TRUNCATE|DELETE\s+FROM)\b", re.I)


def validate_config(config: dict) -> dict:
    if config.get("name") != EXPECTED_WORKER:
        raise ValueError("unexpected Worker name")

    dbs = config.get("d1_databases") or []
    db = next((x for x in dbs if x.get("binding") == "DB"), None)
    if not db:
        raise ValueError("DB binding missing")
    if db.get("database_name") != EXPECTED_DB_NAME:
        raise ValueError("unexpected D1 database name")
    if db.get("database_id") != EXPECTED_DB_ID:
        raise ValueError("unexpected D1 database id")

    date = config.get("compatibility_date")
    if date != EXPECTED_COMPATIBILITY_DATE:
        raise ValueError(
            f"compatibility_date mismatch: expected {EXPECTED_COMPATIBILITY_DATE}, got {date!r}"
        )

    triggers = config.get("triggers") or {}
    crons = triggers.get("crons") or []
    if crons != [EXPECTED_CRON]:
        raise ValueError(f"cron mismatch: expected [{EXPECTED_CRON!r}], got {crons!r}")

    vars_ = config.get("vars") or {}
    if vars_.get("PTT_PUBLISH_ENABLED") == "true":
        raise ValueError("PTT Publisher must not be silently enabled")
    if "ALLOWED_ORIGIN" in vars_ and not str(vars_["ALLOWED_ORIGIN"]).strip():
        raise ValueError("ALLOWED_ORIGIN present but empty")

    return {
        "worker": EXPECTED_WORKER,
        "db_binding": "DB",
        "db_name": EXPECTED_DB_NAME,
        "db_id": EXPECTED_DB_ID,
        "compatibility_date": date,
        "cron": crons[0],
        "allowed_origin_mode": "configured" if "ALLOWED_ORIGIN" in vars_ else "dashboard_preserved",
        "ptt_publish_enabled": vars_.get("PTT_PUBLISH_ENABLED", "not_in_config"),
    }


def validate_schema(sql: str) -> dict:
    if DESTRUCTIVE_SQL.search(sql):
        raise ValueError("destructive SQL present in schema")
    required = [
        "CREATE TABLE IF NOT EXISTS public_collab_events",
        "CREATE TABLE IF NOT EXISTS public_collab_projection_meta",
        "CREATE INDEX IF NOT EXISTS public_collab_events_live",
        "CREATE INDEX IF NOT EXISTS public_collab_events_history",
        "CREATE INDEX IF NOT EXISTS public_collab_events_retire_range",
    ]
    for needle in required:
        if needle not in sql:
            raise ValueError(f"schema missing {needle}")
    return {
        "tables": 2,
        "indexes": 3,
        "destructive_sql": False,
    }


def inspect_artifact(doc: dict) -> dict:
    events = doc.get("events")
    if not isinstance(events, list):
        raise ValueError("artifact events missing")
    key = doc.get("projection_key")
    if key != "live" and not (isinstance(key, str) and key.startswith("history:")):
        raise ValueError("invalid projection_key")
    return {
        "projection_key": key,
        "source_revision": doc.get("source_revision"),
        "event_count": len(events),
        "event_ids": [x.get("event_id") for x in events],
    }


def inspect_import_sql(sql: str, event_count: int, projection_key: str) -> dict:
    if DESTRUCTIVE_SQL.search(sql):
        raise ValueError("destructive SQL present in import")
    statements = [x.strip() for x in sql.split(";") if x.strip()]
    inserts = [x for x in statements if x.upper().startswith("INSERT INTO PUBLIC_COLLAB_EVENTS")]
    meta = [x for x in statements if x.upper().startswith("INSERT INTO PUBLIC_COLLAB_PROJECTION_META")]
    updates = [x for x in statements if x.upper().startswith("UPDATE PUBLIC_COLLAB_EVENTS")]

    if len(inserts) != event_count:
        raise ValueError(f"event upsert count mismatch: {len(inserts)} != {event_count}")
    if len(meta) != 1:
        raise ValueError("expected exactly one projection meta upsert")
    if len(updates) != 1:
        raise ValueError("expected exactly one bounded membership/range update")

    update = updates[0].upper()
    if projection_key == "live":
        if "IS_CURRENT=1 AND LIVE_SCOPE=1" not in update.replace(" ", ""):
            # normalized fallback below handles ordinary whitespace
            normalized = re.sub(r"\s+", "", update)
            if "WHEREIS_CURRENT=1ANDLIVE_SCOPE=1" not in normalized:
                raise ValueError("live projection update is not current-live bounded")
    else:
        normalized = re.sub(r"\s+", "", update)
        if "WHEREIS_CURRENT=1ANDLIVE_SCOPE=0ANDSTART_AT>=" not in normalized:
            raise ValueError("history retirement is not bounded/non-live")

    dml = len(inserts) + len(meta) + len(updates)
    return {
        "total_statements_including_transaction_markers": len(statements),
        "dml_statements": dml,
        "event_upserts": len(inserts),
        "projection_meta_upserts": 1,
        "membership_or_range_updates": 1,
        "expected_formula": {
            "dml": event_count + 2,
            "including_begin_commit": event_count + 4,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--schema", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--sql", required=True)
    args = p.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    schema_sql = Path(args.schema).read_text(encoding="utf-8")
    artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    import_sql = Path(args.sql).read_text(encoding="utf-8")

    artifact_receipt = inspect_artifact(artifact)
    receipt = {
        "mode": "READ_ONLY_PREFLIGHT",
        "config": validate_config(config),
        "schema": validate_schema(schema_sql),
        "artifact": artifact_receipt,
        "import_sql": inspect_import_sql(
            import_sql,
            artifact_receipt["event_count"],
            artifact_receipt["projection_key"],
        ),
        "cloudflare_called": False,
        "d1_mutated": False,
        "deploy_performed": False,
    }
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
