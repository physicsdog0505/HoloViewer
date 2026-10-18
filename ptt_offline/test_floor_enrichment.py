import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.controlled_floor_enrichment import run_one
from ptt_offline.floor_enrichment_plan import build_plan
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError


class FloorEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.source=root/"collector.sqlite3"
        self.remote=root/"remote.json"
        self.plan=root/"plan.json"
        self.receipt=root/"receipt.json"
        url="https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"
        self.aid=aid_from_article_url(url)[1]
        db=sqlite3.connect(self.source)
        try:
            db.executescript("""
              CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
              CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
              CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,source_page INTEGER,total_pages INTEGER,start_line INTEGER,end_line INTEGER,captured_at TEXT);
            """)
            db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",(self.aid,url))
            db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
              (1,1,10,1,'推','a','old','10/14','09:00','2026-10-15T10:00:00Z'),
              (2,1,20,1,'推','b','new one','10/15','18:00','2026-10-15T10:01:05Z'),
              (3,1,30,2,'→','c','new two','10/15','18:01','2026-10-15T10:02:07Z'),
            ])
            db.execute("INSERT INTO article_screens VALUES(1,1,1,2,1,40,'now')")
            db.commit()
        finally:
            db.close()

    def _write_remote(self, rows):
        self.remote.write_text(json.dumps([{"results":rows}]),encoding="utf-8")

    def test_plan_uses_push_ordinal_not_source_line(self):
        self._write_remote([
            {"aid":self.aid,"source_line":20,"source_record_key":f"{self.aid}:20",
             "push_id":None,"floor":None},
            {"aid":self.aid,"source_line":30,"source_record_key":f"{self.aid}:30",
             "push_id":None,"floor":None},
        ])
        result=build_plan(source=str(self.source),aid=self.aid,remote_json=str(self.remote))
        self.assertEqual(result["status"],"READ_ONLY_FLOOR_ENRICHMENT_PLAN")
        self.assertEqual(result["enrichment_rows"],2)
        rows=result["batches"][0]["rows"]
        self.assertEqual([r["source_line"] for r in rows],[20,30])
        self.assertEqual([r["floor"] for r in rows],[2,3])
        self.assertEqual(result["remote_writes"],0)
        self.assertEqual(result["checkpoint_mutations"],0)

    def test_plan_fails_closed_without_article_start_coverage(self):
        db=sqlite3.connect(self.source)
        try:
            db.execute("DELETE FROM article_screens")
            db.execute("INSERT INTO article_screens VALUES(1,1,2,2,20,40,'now')")
            db.commit()
        finally:
            db.close()
        self._write_remote([])
        with self.assertRaisesRegex(ContractError,"article-start coverage"):
            build_plan(source=str(self.source),aid=self.aid,remote_json=str(self.remote))

    def test_controlled_sender_inspect_and_one_attempt_ack(self):
        self._write_remote([
            {"aid":self.aid,"source_line":20,"source_record_key":f"{self.aid}:20","floor":None},
            {"aid":self.aid,"source_line":30,"source_record_key":f"{self.aid}:30","floor":None},
        ])
        plan=build_plan(source=str(self.source),aid=self.aid,remote_json=str(self.remote))
        # Fill exact push identities from the reviewed plan into fresh remote evidence.
        rows=plan["batches"][0]["rows"]
        self._write_remote([
            {"aid":self.aid,"source_line":r["source_line"],"source_record_key":r["source_record_key"],
             "push_id":r["push_id"],"floor":None} for r in rows
        ])
        self.plan.write_text(json.dumps(plan),encoding="utf-8")
        digest=plan["batches"][0]["queue_digest"]
        inspected=run_one(source=str(self.source),aid=self.aid,plan_json=str(self.plan),
            remote_json=str(self.remote),batch_no=1,approved_digest=digest,send=False)
        self.assertEqual(inspected["status"],"READY_TO_ENRICH")
        self.assertEqual(inspected["floors"],[2,3])
        self.assertEqual(inspected["http_requests"],0)

        calls=[]
        def executor(batch):
            calls.append(batch)
            self.assertEqual([r["floor"] for r in batch["rows"]],[2,3])
            return {"status":"ACK","batch_id":batch["batch_id"],"digest":batch["digest"],
                "logical_rows_acked":2,"d1_query_count":12,"d1_rows_written":2,"http_requests":1}
        sent=run_one(source=str(self.source),aid=self.aid,plan_json=str(self.plan),
            remote_json=str(self.remote),batch_no=1,approved_digest=digest,send=True,
            receipt_path=str(self.receipt),executor=executor,proof_secret="k"*40)
        self.assertEqual(sent["status"],"ACK")
        self.assertEqual(sent["http_requests"],1)
        self.assertEqual(len(calls),1)
        with self.assertRaisesRegex(ContractError,"already ACKed"):
            run_one(source=str(self.source),aid=self.aid,plan_json=str(self.plan),
                remote_json=str(self.remote),batch_no=1,approved_digest=digest,send=True,
                receipt_path=str(self.receipt),executor=executor,proof_secret="k"*40)

    def test_non_null_conflicting_remote_floor_blocks(self):
        self._write_remote([
            {"aid":self.aid,"source_line":20,"source_record_key":f"{self.aid}:20",
             "floor":99},
        ])
        with self.assertRaisesRegex(ContractError,"remote floor conflicts"):
            build_plan(source=str(self.source),aid=self.aid,remote_json=str(self.remote))


if __name__=="__main__":
    unittest.main()
