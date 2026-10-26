import sqlite3
import unittest
from ptt_offline.real_ptt_read_export import read_article
from ptt_offline.ptt_aid_identity import aid_from_article_url

class RealReadExportTests(unittest.TestCase):
    def test_raw_source_rows_preserved_without_claiming_year(self):
        db=sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        url="https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"
        aid=aid_from_article_url(url)[1]
        db.executescript("""
            CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
            CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
        """)
        db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'title','now','now')",(aid,url))
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
            (1,1,1,1,'推','tester','原文','09/11','07:05','2026-09-11T00:01:00Z'),
            (2,1,2,1,'→','tester2','另一行','09/11','07:06','2026-09-11T00:02:00Z')])
        one=read_article(db,aid=aid,limit=1)
        self.assertEqual(one["pushes"][0]["content"],"原文")
        self.assertEqual(one["pushes"][0]["ptt_date"],"09/11")
        self.assertTrue(one["has_more"])
        self.assertFalse(one["canonical_d1_published"])
        two=read_article(db,aid=aid,after_line=one["next_after_source_line"])
        self.assertEqual(two["pushes"][0]["source_line"],2)
        self.assertIsNone(two["next_after_source_line"])

if __name__=="__main__": unittest.main()
