"""Offline Publisher CLI synthetic fixtures: no D1, no owner rows."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from ptt_offline.publisher_cli import prepare, coverage_receipt, exclusive_lock
from ptt_offline.public_today_contract import ContractError


class PublisherCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/"synthetic.sqlite3"
        with sqlite3.connect(self.source) as db:
            db.executescript("""
                CREATE TABLE articles (
                  id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
                  title_hint TEXT,created_at TEXT,last_seen_at TEXT,
                  last_page INTEGER,total_pages INTEGER,last_source_line INTEGER);
                CREATE TABLE pushes (
                  id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,
                  source_page INTEGER,kind TEXT,author TEXT,content TEXT,
                  ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
                CREATE TABLE article_screens (
                  id INTEGER PRIMARY KEY,article_id INTEGER,source_page INTEGER,
                  total_pages INTEGER,start_line INTEGER,end_line INTEGER,
                  captured_at TEXT);
                INSERT INTO articles VALUES
                  (1,'C_Chat','A1','u','title','a','b',3,3,50);
                INSERT INTO pushes VALUES
                  (1,1,4,1,'推','author','sensitive-content','10/15','11:21','now');
                INSERT INTO article_screens VALUES
                  (1,1,1,3,1,20,'now'),
                  (2,1,2,3,21,40,'now'),
                  (3,1,3,3,41,50,'now');
            """)
        self.receipt=self.root/"checkpoint.json"

    def test_dry_run_receipt_has_no_content_or_d1_calls(self):
        result=prepare(source=str(self.source),day="2026-10-15",
                       aid="A1",receipt_path=str(self.receipt))
        self.assertEqual(result["publishable_rows"],0)
        self.assertTrue(result["coverage"]["complete"])
        self.assertFalse(result["coverage"]["has_gap"])
        self.assertEqual(result["coverage"]["covered_start"],1)
        self.assertEqual(result["coverage"]["covered_end"],50)
        self.assertEqual(result["coverage"]["last_source_line"],50)
        self.assertEqual(json.loads(self.receipt.read_text())["status"],
                         "BLOCKED_UNVERIFIED_TIMESTAMP")
        self.assertNotIn("sensitive-content",self.receipt.read_text())
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_coverage_detects_internal_and_tail_gap(self):
        with sqlite3.connect(self.source) as db:
            db.execute("DELETE FROM article_screens")
            db.executemany(
                """INSERT INTO article_screens
                   (id,article_id,source_page,total_pages,start_line,end_line,captured_at)
                   VALUES (?,?,?,?,?,?,?)""",
                [(1,1,1,3,1,10,"now"),(2,1,3,3,21,30,"now")],
            )
            result=coverage_receipt(db,"A1")
        self.assertFalse(result["complete"])
        self.assertTrue(result["has_gap"])
        self.assertEqual(result["gaps"],[[11,20],[31,50]])

    def test_pushes_do_not_imply_complete_without_screen_coverage(self):
        with sqlite3.connect(self.source) as db:
            db.execute("DELETE FROM article_screens")
            result=coverage_receipt(db,"A1")
        self.assertFalse(result["complete"])
        self.assertTrue(result["has_gap"])
        self.assertEqual(result["gaps"],[[1,50]])

    def test_reject_live_and_out_of_cap_and_invalid_date(self):
        args=dict(source=str(self.source),day="2026-10-15",
                  aid="A1",receipt_path=str(self.receipt))
        for replacement in ({"dry_run":False},{"batch":6},{"day":"2026-02-30"},
                            {"aid":"NOT_FOUND"}):
            with self.subTest(replacement=replacement):
                with self.assertRaises(ContractError):
                    prepare(**(args|replacement))

    def test_exclusive_lock_denies_second_owner(self):
        target=self.root/"receipt.lock"
        with exclusive_lock(target):
            with self.assertRaises(ContractError):
                with exclusive_lock(target):
                    pass

if __name__=="__main__":
    unittest.main()
