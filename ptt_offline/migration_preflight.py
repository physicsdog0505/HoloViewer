"""Offline-only #48 migration inventory, checksum and SQL preflight.

No cloud, networking, secrets, or production DB mutations. The --local-db
argument must be an explicitly supplied synthetic SQLite fixture and opens
that database READ-ONLY. It is never inferred from an owner machine path.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("d1_migrations") / "0001_canonical_ptt.sql"
MANIFEST = SCHEMA.with_name("manifest.json")
TABLES = (
    "ptt_threads", "ptt_pushes", "ptt_source_evidence",
    "ptt_provider_state", "ptt_gap_repairs", "public_ptt_schema_migrations",
)
COLS = {
    "ptt_pushes": {"push_id", "aid", "day", "source_line", "kind", "author",
                   "content", "occurred_at", "floor", "source_url"},
    "ptt_provider_state": {"day", "aid", "last_success_at", "has_gap",
                           "relay_cursor", "purged_through_cursor", "gap_closed_at"},
}


def schema_receipt():
    """Fail closed on immutable, reviewed migration-byte drift."""
    payload = SCHEMA.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("immutable_migrations")
    if not isinstance(entries, list) or len(entries) != 1:
        raise RuntimeError("migration manifest missing or unexpected version set")
    entry = entries[0]
    digest = hashlib.sha256(payload).hexdigest()
    blob_digest = hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + bytes([0]) + payload).hexdigest()
    if (entry.get("version") != 1
        or entry.get("path") != "ptt_offline/d1_migrations/0001_canonical_ptt.sql"
        or entry.get("git_blob_sha") != blob_digest
        or entry.get("sha256") != digest
        or entry.get("bytes") != len(payload)):
        raise RuntimeError("immutable migration v1 checksum/length mismatch; create v2 instead")
    return {"migration": SCHEMA.as_posix(), "sha256": digest,
            "git_blob_sha": blob_digest,
            "bytes": len(payload), "manifest_verified": True,
            "required_tables": list(TABLES)}


def inspect_fixture(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    try:
        present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(set(TABLES) - present)
        columns = {}
        for name, required in COLS.items():
            if name in present:
                actual = {row[1] for row in db.execute(f"PRAGMA table_info({name})")}
                columns[name] = {"missing": sorted(required - actual)}
        return {"available_tables": sorted(present & set(TABLES)),
                "missing_tables": missing, "column_checks": columns,
                "ready": not missing and all(not x["missing"] for x in columns.values())}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-db", help="Explicit synthetic fixture DB, read-only")
    args = parser.parse_args()
    receipt = schema_receipt()
    if args.local_db:
        receipt["synthetic_fixture_preflight"] = inspect_fixture(args.local_db)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    # No production execution is implemented by design.


if __name__ == "__main__":
    main()
