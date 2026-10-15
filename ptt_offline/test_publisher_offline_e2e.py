"""Offline source stage -> durable ACK -> replay integration, no D1 network."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ptt_offline.collector_day_stage import stage_selected_day
from ptt_offline.publisher_session import run_synthetic_one
from ptt_offline.public_today_contract import ContractError


class PublisherOfflineE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.receipt=str(Path(self.tmp.name)/"ack.json")
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
            INSERT INTO articles VALUES(1,'C_Chat','A1',
                'https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.ABC.html',
                'synthetic','now','now',1,1,20);
            INSERT INTO article_screens VALUES(1,1,1,1,1,20,'now');
            INSERT INTO pushes VALUES(1,1,1,1,'推','a','previous-day','12/31','23:01','now');
        """)
        self.db.executemany("""INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)""",
            [(n,n and 1,n,1,"推","author",f"synthetic-{n}",
              "01/01",f"00:{n:02}", "now") for n in range(2,9)])
        self.verifier=lambda board,aid,url: board=="C_Chat" and aid=="A1"

    def stage(self,after=0):
        return stage_selected_day(self.db,day="2026-01-01",aid="A1",
            identity_verifier=self.verifier,after_source_line=after)

    def ack(self,batch):
        return {"status":"ACK","batch_id":batch["batch_id"],
            "digest":batch["digest"],"http_requests":1,
            "d1_query_count":16,"d1_rows_written":12,
            "logical_rows_acked":len(batch["rows"])}

    def test_mixed_day_five_then_two_and_identity_stability(self):
        first=self.stage()
        self.assertEqual(first["selected_rows_total"],7)
        self.assertEqual(len(first["rows"]),5)
        self.assertTrue(first["has_more"])
        ident=first["source_identity"]
        self.assertEqual(self.stage(after=first["next_after_source_line"])["selected_rows_total"],2)
        def failed(batch):
            raise ContractError("synthetic lost ACK")
        with self.assertRaises(ContractError):
            run_synthetic_one(checkpoint_path=self.receipt,source_identity=ident,
                day="2026-01-01",aids=["A1"],rows=first["rows"],executor=failed)
        self.assertFalse(Path(self.receipt).exists())
        one=run_synthetic_one(checkpoint_path=self.receipt,source_identity=ident,
            day="2026-01-01",aids=["A1"],rows=first["rows"],executor=self.ack)
        self.assertEqual(one["checkpoint"]["aids"]["A1"],6)
        second=self.stage(after=6)
        two=run_synthetic_one(checkpoint_path=self.receipt,source_identity=ident,
            day="2026-01-01",aids=["A1"],rows=second["rows"],executor=self.ack)
        self.assertEqual(two["checkpoint"]["aids"]["A1"],8)
        self.assertEqual(self.stage(after=8)["rows"],[])
        # A rescan that edits an existing source_line is also a new source identity.
        self.db.execute("UPDATE pushes SET content=? WHERE source_line=3",("reparsed",))
        changed_content=self.stage(after=8)
        self.assertNotEqual(changed_content["source_identity"],ident)
        with self.assertRaises(ContractError):
            run_synthetic_one(checkpoint_path=self.receipt,
                source_identity=changed_content["source_identity"],day="2026-01-01",
                aids=["A1"],rows=changed_content["rows"],executor=self.ack)
        # A URL change is a source identity change; an old checkpoint
        # cannot follow it even when the synthetic verifier permits it.
        self.db.execute("UPDATE articles SET url=REPLACE(url,'.ABC.html','.DEF.html')")
        changed=self.stage(after=8)
        self.assertNotEqual(changed["source_identity"],ident)
        with self.assertRaises(ContractError):
            run_synthetic_one(checkpoint_path=self.receipt,
                source_identity=changed["source_identity"],day="2026-01-01",
                aids=["A1"],rows=changed["rows"],executor=self.ack)


if __name__=="__main__":
    unittest.main()
