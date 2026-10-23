"""Offline-only fail-closed conversion of the pinned Collab SQL envelope.

This produces *candidate* DML for independent #45 review; it NEVER sends writes.
Importantly, wrangler remote --file is NOT claimed to execute all DML atomically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from ptt_offline.collab_projection_import import render_sql, validate

EXPECTED_ARTIFACT_SHA = "9ab74e8d722e0d53731e85cdd6d83f261e2c9cbafebe11869ac00681847c78b2"
EXPECTED_ORIGINAL_SQL_SHA = "94d106b28b936424813dd00cf1f8b233714697b968a85a3b70b82e68b2f872de"
EXPECTED_REVISION = "sha256:8d0e11e2c08764f643c7751e08ea55e558b71f65eca71a25d89159022ca6fdeb"
EXPECTED_EVENT = "holoserver-hide-and-seek:5680e7ec7c29074a"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate(artifact: bytes, original_sql: bytes) -> bytes:
    if sha256(artifact) != EXPECTED_ARTIFACT_SHA:
        raise ValueError("STOP: artifact SHA mismatch")
    if sha256(original_sql) != EXPECTED_ORIGINAL_SQL_SHA:
        raise ValueError("STOP: original authorized SQL SHA mismatch")
    doc = json.loads(artifact.decode("utf-8"))
    rows = validate(doc)
    if (len(rows) != 1 or rows[0]["event_id"] != EXPECTED_EVENT
            or doc["projection_key"] != "live"
            or doc["source_revision"] != EXPECTED_REVISION
            or bool(rows[0].get("live_scope"))):
        raise ValueError("STOP: unexpected artifact contents")
    if render_sql(doc).encode("utf-8") != original_sql:
        raise ValueError("STOP: source/render parity mismatch")

    sql = original_sql.decode("utf-8")
    lines = sql.splitlines(keepends=True)
    if len(lines) != 5 or lines[0].strip().upper() != "BEGIN TRANSACTION;" or lines[-1].strip().upper() != "COMMIT;":
        raise ValueError("STOP: unexpected transaction envelope")
    dml = [s.strip() for s in lines[1:-1]]
    if (len(dml) != 3
            or not dml[0].upper().startswith("UPDATE PUBLIC_COLLAB_EVENTS SET LIVE_SCOPE=0 WHERE IS_CURRENT=1 AND LIVE_SCOPE=1;")
            or not dml[1].upper().startswith("INSERT INTO PUBLIC_COLLAB_EVENTS(")
            or not dml[2].upper().startswith("INSERT INTO PUBLIC_COLLAB_PROJECTION_META(")
            or any(not s.endswith(";") for s in dml)):
        raise ValueError("STOP: DML shape mismatch")
    # Preserve original DML bytes exactly. No production execution occurs here.
    return "".join(lines[1:-1]).encode("utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description="Prepare import-only candidate for independent review; no network")
    p.add_argument("--artifact", required=True)
    p.add_argument("--original-sql", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = candidate(Path(args.artifact).read_bytes(), Path(args.original_sql).read_bytes())
    Path(args.output).write_bytes(result)
    print(json.dumps({"candidate_sha256": sha256(result), "dml_statements": 3,
                      "remote_atomicity_proven": False,
                      "authorized_for_production": False, "cloudflare_called": False}))


if __name__ == "__main__":
    main()
