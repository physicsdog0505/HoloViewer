import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.plan_baseline_repair import build_plan
from ptt_offline.ptt_aid_identity import aid_from_article_url


class BaselineRepairPlanTests(unittest.TestCase):
    def test_plan_dedups_remote_and_excludes_pending_with_ten_row_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            source=root/"collector.sqlite3"
            db=sqlite3.connect(source)
            db.executescript("""
              CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
              CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
            """)
            url="https://www.ptt.cc/bbs/C_Chat/M.1792180800.A.001.html"
            aid=aid_from_article_url(url)[1]
            db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",(aid,url))
            rows=[]
            for n in range(1,14):
                rows.append((n,1,n,1,'推','u',f'line-{n}','10/17','15:00','2026-10-17T07:00:30Z'))
            db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",rows)
            db.commit(); db.close()

            # Baseline checkpoint may contain local-only accepted rows.
            state=root/"state.json"
            state.write_text(json.dumps({
                "status":"ACKED","source_identity":"a"*64,
                "accepted":{f"{aid}:{n}":"x" for n in range(1,14)},
            }),encoding="utf-8")
            remote=root/"remote.json"
            remote.write_text(json.dumps({"results":[{"source_line":1},{"source_line":2}]}),
                              encoding="utf-8")

            result=build_plan(source=str(source),state=str(state),aid=aid,
                              remote_json=str(remote),baseline_source_line=13,batch_cap=10)
            self.assertEqual(result["missing_remote_baseline_rows"],11)
            self.assertEqual(result["repairable_ready_rows"],11)
            self.assertEqual(result["pending_rows"],0)
            self.assertEqual(result["planned_batches"],2)
            self.assertEqual(result["batches"][0]["row_count"],10)
            self.assertEqual(result["batches"][1]["row_count"],1)
            self.assertEqual(result["repairable_source_lines"],list(range(3,14)))
            self.assertEqual(result["safety"]["remote_writes"],0)


if __name__=="__main__":
    unittest.main()
