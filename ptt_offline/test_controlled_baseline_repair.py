import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ptt_offline.controlled_baseline_repair import run_one
from ptt_offline.plan_baseline_repair import build_plan
from ptt_offline.ptt_aid_identity import aid_from_article_url
from ptt_offline.public_today_contract import ContractError


class ControlledBaselineRepairTests(unittest.TestCase):
    def _fixture(self):
        td=tempfile.TemporaryDirectory()
        root=Path(td.name)
        source=root/"collector.sqlite3"
        db=sqlite3.connect(source)
        db.executescript("""
          CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT,url TEXT,title_hint TEXT,created_at TEXT,last_seen_at TEXT);
          CREATE TABLE pushes(id INTEGER PRIMARY KEY,article_id INTEGER,source_line INTEGER,source_page INTEGER,kind TEXT,author TEXT,content TEXT,ptt_date TEXT,ptt_time TEXT,collected_at TEXT);
        """)
        url="https://www.ptt.cc/bbs/C_Chat/M.1792180800.A.001.html"
        aid=aid_from_article_url(url)[1]
        db.execute("INSERT INTO articles VALUES(1,'C_Chat',?,?,'t','now','now')",(aid,url))
        db.executemany("INSERT INTO pushes VALUES(?,?,?,?,?,?,?,?,?,?)",[
            (n,1,n,1,'推','u',f'line-{n}','10/17','15:00','2026-10-17T07:00:30Z')
            for n in range(1,13)
        ])
        db.commit(); db.close()
        state=root/"state.json"
        state.write_text(json.dumps({
            "status":"ACKED","source_identity":"a"*64,
            "accepted":{f"{aid}:{n}":"x" for n in range(1,13)},
        }),encoding="utf-8")
        remote=root/"remote.json"
        remote.write_text(json.dumps({"results":[]}),encoding="utf-8")
        plan=build_plan(source=str(source),state=str(state),aid=aid,
                        remote_json=str(remote),baseline_source_line=12,batch_cap=10)
        plan_path=root/"plan.json"
        plan_path.write_text(json.dumps(plan),encoding="utf-8")
        return td,root,source,aid,remote,plan,plan_path

    def test_inspect_is_zero_write_and_binds_exact_digest(self):
        td,root,source,aid,remote,plan,plan_path=self._fixture()
        self.addCleanup(td.cleanup)
        batch=plan["batches"][0]
        result=run_one(source=str(source),aid=aid,plan_json=str(plan_path),
                       remote_json=str(remote),batch_no=1,
                       approved_digest=batch["queue_digest"],send=False)
        self.assertEqual(result["status"],"READY_TO_SEND")
        self.assertEqual(result["rows"],10)
        self.assertEqual(result["http_requests"],0)
        self.assertEqual(result["live_checkpoint_mutations"],0)

    def test_remote_duplicate_blocks_before_executor(self):
        td,root,source,aid,remote,plan,plan_path=self._fixture()
        self.addCleanup(td.cleanup)
        batch=plan["batches"][0]
        first=batch["rows"][0]
        remote.write_text(json.dumps({"results":[{
            "source_line":first["source_line"],
            "source_record_key":first["source_record_key"],
            "push_id":first["push_id"],
        }]}),encoding="utf-8")
        with self.assertRaisesRegex(ContractError,"already exists remotely"):
            run_one(source=str(source),aid=aid,plan_json=str(plan_path),
                    remote_json=str(remote),batch_no=1,
                    approved_digest=batch["queue_digest"],send=False)

    def test_send_is_one_attempt_and_isolated_receipt_latches_ack(self):
        td,root,source,aid,remote,plan,plan_path=self._fixture()
        self.addCleanup(td.cleanup)
        batch=plan["batches"][0]
        receipt=root/"repair-receipt.json"
        calls=[]
        def executor(transport):
            calls.append(transport)
            return {
                "status":"ACK","batch_id":transport["batch_id"],"digest":transport["digest"],
                "logical_rows_acked":len(transport["rows"]),
                "d1_query_count":2+5*len(transport["rows"]),
                "d1_rows_written":2+2*len(transport["rows"]),
                "http_requests":1,
            }
        result=run_one(source=str(source),aid=aid,plan_json=str(plan_path),
                       remote_json=str(remote),batch_no=1,
                       approved_digest=batch["queue_digest"],send=True,
                       receipt_path=str(receipt),executor=executor,
                       proof_secret="k"*40)
        self.assertEqual(result["status"],"ACK")
        self.assertEqual(len(calls),1)
        self.assertEqual(result["logical_rows_acked"],10)
        saved=json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(saved["status"],"ACK")
        with self.assertRaisesRegex(ContractError,"already ACKed"):
            run_one(source=str(source),aid=aid,plan_json=str(plan_path),
                    remote_json=str(remote),batch_no=1,
                    approved_digest=batch["queue_digest"],send=True,
                    receipt_path=str(receipt),executor=executor,
                    proof_secret="k"*40)
        self.assertEqual(len(calls),1)


if __name__=="__main__":
    unittest.main()
