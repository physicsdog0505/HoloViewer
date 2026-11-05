import sqlite3
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from ptt_offline.source_audit_cli import audit
from datetime import datetime,timezone
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.source_audit_stage import audit_source_day

class SourceAuditStageTests(unittest.TestCase):
    def test_real_identity_with_row_level_ambiguity_never_publishes(self):
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        epoch=int(datetime(2025,12,31,15,tzinfo=timezone.utc).timestamp())
        url=f"https://www.ptt.cc/bbs/C_Chat/M.{epoch}.A.ABC.html"
        aid=aid_from_article_url(url)[1]
        db.executescript("""
            CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,
              title_hint TEXT,created_at TEXT,last_seen_at TEXT,
              last_page INTEGER,total_pages INTEGER,last_source_line INTEGER);
            CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,
              source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,
              content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
            CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,
              source_page INTEGER,total_pages INTEGER,start_line INTEGER,end_line INTEGER,
              captured_at TEXT);
            INSERT INTO article_screens VALUES(1,1,1,1,1,4,'now');
        """)
        db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now',1,1,4)",(aid,url))
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
            (1,1,1,1,'推','a','x','01/01','00:01','2026-01-01T00:02:00Z'),
            (2,1,2,1,'推','a','y','bad','00:02','2026-01-01T00:03:00Z'),
            (3,1,3,1,'推','a','z','01/01','00:03','2026-01-01T00:04:00Z'),
        ])
        receipt=audit_source_day(db,day="2026-01-01",aid=aid,
                                timezone_evidence=True)
        self.assertEqual(receipt["source_rows_examined"],3)
        self.assertEqual([r["source_line"] for r in receipt["inferred_day"]],[1,3])
        self.assertEqual(receipt["checkpoint_blocked_at"],2)
        self.assertEqual(receipt["publishable_rows"],[])
        self.assertEqual(receipt["pending"][0]["reason"],"invalid-source-calendar")
        with patch("ptt_offline.source_audit_cli.open_source",return_value=nullcontext(db)):
            redacted=audit(source="/synthetic/readonly.sqlite3",day="2026-01-01",aid=aid)
        self.assertEqual(redacted["pending_count"],3)
        self.assertEqual(redacted["publishable_count"],0)
        self.assertNotIn("content",str(redacted))
        self.assertNotIn("author",redacted)

if __name__=="__main__":
    unittest.main()
