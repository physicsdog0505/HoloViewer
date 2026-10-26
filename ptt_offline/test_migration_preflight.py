"""Offline-only execution-package checks; no cloud or owner SQLite."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from ptt_offline.migration_preflight import TABLES, schema_receipt, inspect_fixture, SCHEMA, MANIFEST


class MigrationPreflightTests(unittest.TestCase):
    def test_frozen_source_checksum_is_reproducible(self):
        import hashlib
        receipt = schema_receipt()
        self.assertEqual(receipt["sha256"], hashlib.sha256(SCHEMA.read_bytes()).hexdigest())
        self.assertEqual(len(receipt["sha256"]), 64)
        self.assertTrue(receipt["manifest_verified"])
        import json
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(receipt["sha256"], manifest["immutable_migrations"][0]["sha256"])
        self.assertEqual(receipt["git_blob_sha"], manifest["immutable_migrations"][0]["git_blob_sha"])
        self.assertEqual(receipt["git_blob_sha"], "7466163e331b05c2b12ca559affbf2386f49460c")
        self.assertEqual(set(receipt["required_tables"]), set(TABLES))

    def test_reviewed_blob_pin_mismatch_rejected_even_if_sha256_is_updated(self):
        import hashlib
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            sql = Path(directory) / "changed.sql"
            manifest = Path(directory) / "manifest.json"
            payload = SCHEMA.read_bytes() + b"-- modified v1, forbidden\\n"
            sql.write_bytes(payload)
            baseline = json.loads(MANIFEST.read_text(encoding="utf-8"))
            entry = baseline["immutable_migrations"][0]
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
            entry["bytes"] = len(payload)
            manifest.write_text(json.dumps(baseline), encoding="utf-8")
            with patch("ptt_offline.migration_preflight.SCHEMA", sql), patch(
                "ptt_offline.migration_preflight.MANIFEST", manifest
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum/length mismatch"):
                    schema_receipt()

    def test_synthetic_fixture_preflight_and_missing_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.sqlite3"
            db = sqlite3.connect(path)
            db.executescript(SCHEMA.read_text(encoding="utf-8"))
            db.close()
            good = inspect_fixture(path)
            self.assertTrue(good["ready"])
            self.assertEqual(good["missing_tables"], [])
            empty = Path(directory) / "empty.sqlite3"
            sqlite3.connect(empty).close()
            bad = inspect_fixture(empty)
            self.assertFalse(bad["ready"])
            self.assertIn("ptt_pushes", bad["missing_tables"])


if __name__ == "__main__":
    unittest.main()
