import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.audit_baseline_gap import audit


class BaselineGapAuditTests(unittest.TestCase):
    def test_classifies_remote_ack_baseline_skip_and_post_baseline_unpublished(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"collector.sqlite3"
            db=sqlite3.connect(source)
            db.executescript("""
              CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
              CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
            """)
            url="https://www.ptt.cc/bbs/C_Chat/M.1792180800.A.001.html"
            # AID is intentionally read from the actual identity implementation
            # by using the hash-prefixed Collector form accepted by the source.
            from ptt_offline.ptt_aid_identity import aid_from_article_url
            aid=aid_from_article_url(url)[1]
            db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",("#"+aid,url))
            db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
                (1,1,1,1,'推','a','one','10/17','15:00','2026-10-17T07:00:30Z'),
                (2,1,2,1,'推','b','two','10/17','15:01','2026-10-17T07:01:30Z'),
                (3,1,3,1,'推','c','three','10/17','15:02','2026-10-17T07:02:30Z'),
                (4,1,4,1,'推','d','four','10/17','15:03','2026-10-17T07:03:30Z'),
            ])
            db.commit()
            db.close()

            state=root/"state.json"
            state.write_text(json.dumps({
                "status":"BASELINED",
                "source_identity":"a"*64,
                "baseline_source_line":3,
                "accepted":{f"{aid}:1":"x",f"{aid}:2":"y"},
            }),encoding="utf-8")
            remote=root/"remote.json"
            remote.write_text(json.dumps({"results":[{"source_line":1}]}),encoding="utf-8")

            result=audit(source=str(source),state=str(state),aid="#"+aid,remote_json=str(remote))
            self.assertEqual(result["collector_rows"],4)
            self.assertEqual(result["checkpoint_accepted"],2)
            self.assertEqual(result["baseline_source_line"],3)
            self.assertEqual(result["counts"]["REMOTE_ACKED"],1)
            self.assertEqual(result["counts"]["BASELINE_ACCEPTED_LOCAL_ONLY"],1)
            self.assertEqual(result["counts"]["BASELINE_SKIPPED_READY"],1)
            self.assertEqual(result["counts"]["UNPUBLISHED_READY"],1)
            self.assertEqual(result["unpublished_source_lines"],[2,3,4])
            self.assertEqual(result["safety"]["remote_writes"],0)


if __name__=="__main__":
    unittest.main()
