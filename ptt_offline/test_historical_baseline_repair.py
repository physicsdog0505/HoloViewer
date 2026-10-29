import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.controlled_baseline_repair import run_one
from ptt_offline.plan_baseline_repair import build_plan
from ptt_offline.plan_historical_baseline_repair import build_historical_plan
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError


class HistoricalBaselineRepairTests(unittest.TestCase):
    def _fixture(self):
        td=tempfile.TemporaryDirectory(); root=Path(td.name)
        source=root/"collector.sqlite3"
        db=sqlite3.connect(source)
        db.executescript("""
          CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
          CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
          CREATE TABLE article_screens(id INTEGER PRIMARY KEY,article_id INTEGER,source_page INTEGER,total_pages INTEGER,start_line INTEGER,end_line INTEGER,captured_at TEXT);
        """)
        url="https://www.ptt.cc/bbs/C_Chat/M.1792180800.A.001.html"
        aid=aid_from_article_url(url)[1]
        db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",(aid,url))
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
            (n,1,n,1,'推','u',f'line-{n}','10/17','15:00','2026-10-17T12:30:00Z')
            for n in range(1,13)
        ])
        db.execute("INSERT INTO article_screens VALUES(1,1,1,1,1,20,'now')")
        db.commit(); db.close()
        state=root/"state.json"
        state.write_text(json.dumps({
            "status":"BASELINED","baseline_source_line":12,
            "accepted":{},
        }),encoding="utf-8")
        remote=root/"remote.json"
        remote.write_text(json.dumps({"results":[]}),encoding="utf-8")
        return td,root,source,aid,state,remote

    def test_delayed_rows_stay_live_pending_but_historical_plan_is_bounded(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        live=build_plan(source=str(source),state=str(state),aid=aid,
            remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        self.assertEqual(live["repairable_ready_rows"],0)
        self.assertEqual(live["pending_rows"],12)
        historical=build_historical_plan(source=str(source),state=str(state),aid=aid,
            remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        self.assertEqual(historical["authority"],"verified_url_epoch_full_article_v1")
        self.assertEqual(historical["repairable_source_lines"],list(range(1,13)))
        self.assertEqual([b["row_count"] for b in historical["batches"]],[10,2])
        self.assertEqual(historical["safety"]["remote_writes"],0)

    def test_incomplete_or_gapped_article_coverage_fails_closed(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        db=sqlite3.connect(source)
        db.execute("UPDATE article_screens SET start_line=2")
        db.commit(); db.close()
        with self.assertRaisesRegex(ContractError,"start at article line 1"):
            build_historical_plan(source=str(source),state=str(state),aid=aid,
                remote_json=str(remote),baseline_source_line=12)

    def test_regressive_source_chronology_fails_closed(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        db=sqlite3.connect(source)
        db.execute("UPDATE pushes SET ptt_time='14:59' WHERE source_line=2")
        db.commit(); db.close()
        with self.assertRaisesRegex(ContractError,"regressive source chronology"):
            build_historical_plan(source=str(source),state=str(state),aid=aid,
                remote_json=str(remote),baseline_source_line=12)

    def test_sender_revalidates_authority_and_uses_one_attempt(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        plan=build_historical_plan(source=str(source),state=str(state),aid=aid,
            remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        plan_path=root/"plan.json"; plan_path.write_text(json.dumps(plan),encoding="utf-8")
        batch=plan["batches"][0]; calls=[]
        def executor(transport):
            calls.append(transport)
            return {"status":"ACK","batch_id":transport["batch_id"],
                "digest":transport["digest"],"logical_rows_acked":len(transport["rows"]),
                "d1_query_count":2+5*len(transport["rows"]),
                "d1_rows_written":2+2*len(transport["rows"]),"http_requests":1}
        result=run_one(source=str(source),aid=aid,plan_json=str(plan_path),
            remote_json=str(remote),batch_no=1,
            approved_digest=batch["queue_digest"],send=True,
            receipt_path=str(root/"receipt.json"),executor=executor,
            proof_secret="k"*40)
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(result["live_checkpoint_mutations"],0)
        self.assertEqual(len(calls),1)

    def test_remote_duplicate_blocks_historical_batch(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        plan=build_historical_plan(source=str(source),state=str(state),aid=aid,
            remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        plan_path=root/"plan.json"; plan_path.write_text(json.dumps(plan),encoding="utf-8")
        first=plan["batches"][0]["rows"][0]
        remote.write_text(json.dumps({"results":[first]}),encoding="utf-8")
        with self.assertRaisesRegex(ContractError,"already exists remotely"):
            run_one(source=str(source),aid=aid,plan_json=str(plan_path),
                remote_json=str(remote),batch_no=1,
                approved_digest=plan["batches"][0]["queue_digest"],send=False)

    def test_other_aid_same_source_lines_do_not_hide_or_block_repair(self):
        td,root,source,aid,state,remote=self._fixture(); self.addCleanup(td.cleanup)
        remote.write_text(json.dumps({"results":[
            {"aid":"differentAID","source_line":line,"push_id":f"other-{line}"}
            for line in range(1,13)
        ]}),encoding="utf-8")
        plan=build_historical_plan(source=str(source),state=str(state),aid=aid,
            remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        self.assertEqual(plan["repairable_source_lines"],list(range(1,13)))
        plan_path=root/"plan.json"; plan_path.write_text(json.dumps(plan),encoding="utf-8")
        inspected=run_one(source=str(source),aid=aid,plan_json=str(plan_path),
            remote_json=str(remote),batch_no=1,
            approved_digest=plan["batches"][0]["queue_digest"],send=False)
        self.assertEqual(inspected["status"],"READY_TO_SEND")


if __name__=="__main__": unittest.main()
