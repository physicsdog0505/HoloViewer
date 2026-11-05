import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.verified_publisher_flow import run_verified_offline_one

class VerifiedPublisherFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"receipt.json")
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        epoch=int(datetime(2025,12,31,15,tzinfo=timezone.utc).timestamp())
        self.url=f"https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.ABC.html"
        self.aid=aid_from_article_url(self.url)[1]
        self.db.executescript("""
            CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
                title_hint TEXT,created_at TEXT,last_seen_at TEXT,
                last_page INTEGER,total_pages INTEGER,last_source_line INTEGER);
            CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,
                source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,
                content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
            CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,
                source_page INTEGER,total_pages INTEGER,start_line INTEGER,
                end_line INTEGER,captured_at TEXT);
            INSERT INTO article_screens VALUES(1,1,1,1,1,30,'now');
        """)
        self.db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now',1,1,30)",(self.aid,self.url))
        self.db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",
          [(n,1,n,1,"推","author",f"content{n}","01/01",f"00:{n:02}","now")
           for n in range(1,8)])

    @staticmethod
    def ack(batch):
        return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
                "http_requests":1,"d1_query_count":15,"d1_rows_written":12,
                "logical_rows_acked":len(batch["rows"])}

    def call(self,verify,executor=None):
        return run_verified_offline_one(self.db,day="2026-01-01",aid=self.aid,
            checkpoint_path=self.path,time_verifier=verify,executor=executor or self.ack)

    def test_all_verified_five_then_two_resume(self):
        one=self.call(lambda row:True)
        self.assertEqual(one["checkpoint"]["aids"][self.aid],5)
        self.assertTrue(one["batch_id"].startswith("ptt48:"))
        two=self.call(lambda row:True)
        self.assertEqual(two["checkpoint"]["aids"][self.aid],7)
        self.assertEqual(self.call(lambda row:True)["status"],"NO_NEW_ROWS")

    def test_pending_stops_before_unverified_row(self):
        one=self.call(lambda row:row["source_line"]!=3)
        self.assertEqual(one["checkpoint"]["aids"][self.aid],2)
        self.assertEqual(one["pending"][0]["source_line"],3)
        attempts=[]
        result=self.call(lambda row:False,lambda b:attempts.append(b))
        self.assertEqual(result["status"],"PENDING_AUTHORITY")
        self.assertEqual(attempts,[])

    def test_unverified_never_executes(self):
        attempts=[]
        self.assertEqual(self.call(lambda row:False,lambda b:attempts.append(b))["status"],
                         "PENDING_AUTHORITY")
        self.assertFalse(attempts)

if __name__=="__main__":
    unittest.main()
