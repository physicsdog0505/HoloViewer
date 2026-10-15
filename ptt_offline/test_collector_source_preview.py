"""Synthetic canonical Collector schema preview tests. No owner data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from ptt_offline.collector_source_preview import open_source, verify_schema, preview
from ptt_offline.public_today_contract import ContractError


class CollectorSourcePreviewTests(unittest.TestCase):
    def test_readonly_explicit_schema_preview_fails_closed_on_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"collector-synthetic.sqlite3"
            db=sqlite3.connect(path)
            db.executescript("""
              CREATE TABLE articles (
                id INTEGER PRIMARY KEY, board TEXT, aid TEXT, url TEXT,
                title_hint TEXT, created_at TEXT, last_seen_at TEXT);
              CREATE TABLE pushes (
                id INTEGER PRIMARY KEY, article_id INTEGER,
                source_line INTEGER, source_page INTEGER, kind TEXT,
                author TEXT, content TEXT, ptt_date TEXT, ptt_time TEXT,
                collected_at TEXT);
              INSERT INTO articles VALUES (
                1,'C_Chat','A1','https://www.ptt.cc/bbs/C_Chat/M.1234567890.A.ABC.html',
                'title','2026-10-15T00:00:00Z','2026-10-15T00:00:00Z');
              INSERT INTO pushes VALUES (
                1,1,1,1,'推','tester','private-content',
                '10/15','12:30','2026-10-15T00:00:00Z');
            """)
            db.close()
            with open_source(path) as source:
                verify_schema(source)
                info=preview(source,day="2026-10-15")
                self.assertEqual(info["publishable_rows"],0)
                self.assertNotIn("private-content",str(info))
                self.assertEqual(info["time_identity"],"UNVERIFIED")
            with open_source(path) as source:
                with self.assertRaises(ContractError):
                    preview(source,day="2026-10-15",limit=6)
                with self.assertRaises(sqlite3.OperationalError):
                    source.execute("DELETE FROM pushes")

    def test_missing_columns_fail_schema(self):
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE articles(id INTEGER)")
            with self.assertRaises(ContractError):
                verify_schema(db)


if __name__=="__main__":
    unittest.main()
