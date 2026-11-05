import sqlite3
import unittest
from datetime import datetime, timezone

from ptt_offline.collector_day_stage import stage_selected_day
from ptt_offline.public_today_contract import ContractError


class CollectorDayStageTests(unittest.TestCase):
    verifier=staticmethod(lambda board,aid,url: board == "C_Chat" and aid == "A1")
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        epoch=int(datetime(2025,12,31,15,0,tzinfo=timezone.utc).timestamp())
        self.db.executescript(f"""
            CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
                title_hint TEXT,created_at TEXT,last_seen_at TEXT,
                last_page INTEGER,total_pages INTEGER,last_source_line INTEGER);
            CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,
                source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,
                content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
            CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,
                source_page INTEGER,total_pages INTEGER,start_line INTEGER,
                end_line INTEGER,captured_at TEXT);
            INSERT INTO articles VALUES
                (1,'C_Chat','#A1','https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.ABC.html',
                'synthetic','now','now',1,1,10);
            INSERT INTO article_screens VALUES (1,1,1,1,1,10,'now');
            INSERT INTO pushes VALUES
                (1,1,5,1,'推','author','before','12/31','23:10','now'),
                (2,1,6,1,'推','author','after','01/01','00:01','now');
        """)

    def test_selected_day_only_and_source_identity(self):
        earlier=stage_selected_day(self.db,identity_verifier=self.verifier,day="2025-12-31",aid="A1")
        later=stage_selected_day(self.db,identity_verifier=self.verifier,day="2026-01-01",aid="#A1")
        self.assertEqual(earlier["selected_rows_total"],1)
        self.assertEqual(later["selected_rows_total"],1)
        self.assertEqual(later["rows"][0]["content"],"after")
        self.assertEqual(later["next_after_source_line"],6)
        self.assertEqual(later["rows"][0]["source_record_key"],"A1:6")
        self.assertEqual(later["rows"][0]["occurred_at"],"2025-12-31T16:01:00Z")
        self.assertTrue(later["coverage"]["complete"])

    def test_resume_after_ack_does_not_restage_old_source_line(self):
        result=stage_selected_day(self.db,identity_verifier=self.verifier,day="2026-01-01",aid="A1",
                                  after_source_line=6)
        self.assertEqual(result["selected_rows_total"],0)
        self.assertEqual(result["rows"],[])

    def test_unverified_identity_and_invalid_day_rejected(self):
        with self.assertRaises(ContractError):
            stage_selected_day(self.db,day="2026-01-01",aid="A1")
        with self.assertRaises(ContractError):
            stage_selected_day(self.db,identity_verifier=self.verifier,
                               day="2026-02-30",aid="A1")

    def test_unknown_aid_and_cap_fail_closed(self):
        with self.assertRaises(ContractError):
            stage_selected_day(self.db,day="2026-01-01",aid="missing")
        with self.assertRaises(ContractError):
            stage_selected_day(self.db,day="2026-01-01",aid="A1",limit=6)


if __name__=="__main__":
    unittest.main()
