import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ptt_offline.canonical_remap_repair import build_batches,execute_batch
from ptt_offline.public_today_contract import canonical_id,ContractError


class CanonicalRemapRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/'collector.sqlite3'
        with sqlite3.connect(self.db) as con:
            con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY,board TEXT,aid TEXT)")
            con.execute("INSERT INTO articles VALUES(72,'C_Chat','#1gwHM4TF')")
        self.old={"push_id":"ptt:v1:"+"a"*64,"aid":"1gwHM4TF","day":"2026-11-03",
            "source_line":383,"kind":"推","author":"old","content":"provisional",
            "occurred_at":"2026-11-03T10:00:00Z","floor":1,
            "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1793660292.A.74F.html",
            "source_priority":10,"source_record_key":"1gwHM4TF:383"}
        snapshot={"ptt_pushes":[self.old],"ptt_source_evidence":[{
            "day":self.old["day"],"aid":self.old["aid"],
            "source_record_key":self.old["source_record_key"],
            "push_id":self.old["push_id"],"source_line":self.old["source_line"]}]}
        self.remote=self.root/'remote.json'
        self.remote.write_text(json.dumps(snapshot),encoding='utf-8')
        raw={"aid":"1gwHM4TF","source_line":383,"kind":"推","author":"canonical",
            "content":"from Collector only","occurred_at":"2026-11-03T10:00:01Z","floor":None,
            "source_url":self.old["source_url"],"source_record_key":"1gwHM4TF:383"}
        raw["push_id"]=canonical_id(raw)
        self.plan={"status":"READY","aid":"1gwHM4TF","source_identity":"d"*64,
            "candidate_rows":[raw],"floor_authoritative":True,
            "floor_by_source_line":{383:1}}

    def candidate(self):
        with patch('ptt_offline.canonical_remap_repair.inspect_latest_article',return_value=self.plan):
            return build_batches(source=self.db,remote_json=self.remote,aid='1gwHM4TF',
                source_lines=(383,),proof_secret='p'*40)

    def test_replacement_is_reloaded_from_collector_not_remote_or_caller(self):
        candidate=self.candidate()
        pair=candidate['batches'][0]['rows'][0]
        self.assertEqual(pair['old']['content'],'provisional')
        self.assertEqual(pair['new']['content'],'from Collector only')
        self.assertEqual(pair['new']['floor'],1)
        self.assertEqual(len(pair['new']['canonical_proof']),64)
        self.assertEqual(candidate['live_checkpoint_mutations'],0)

    def test_scope_mismatch_rejected(self):
        with patch('ptt_offline.canonical_remap_repair.inspect_latest_article',return_value=self.plan):
            with self.assertRaisesRegex(ContractError,'allowlist'):
                build_batches(source=self.db,remote_json=self.remote,aid='1gwHM4TF',
                    source_lines=(382,),proof_secret='p'*40)

    def test_durable_receipt_latches_uncertain_and_exact_ack(self):
        candidate=self.candidate();receipt=self.root/'receipt.json'
        batch=candidate['batches'][0]
        ack={"status":"ACK","batch_id":batch['batch_id'],"digest":batch['digest'],
            "rows_verified":1,"logical_rows_repaired":1,"d1_rows_written":2,
            "d1_query_count":6,"http_requests":1,"live_checkpoint_mutations":0}
        got=execute_batch(candidate=candidate,batch_number=1,receipt_path=receipt,
                          executor=lambda value:ack)
        self.assertEqual(got['status'],'ACK')
        self.assertEqual(json.loads(receipt.read_text())['live_checkpoint_mutations'],0)
        with self.assertRaisesRegex(ContractError,'already completed'):
            execute_batch(candidate=candidate,batch_number=1,receipt_path=receipt,
                          executor=lambda value:ack)

    def test_remote_error_leaves_durable_uncertain_receipt_and_no_retry(self):
        candidate=self.candidate();receipt=self.root/'receipt.json';calls=[]
        def fail(value):
            calls.append(value);raise RuntimeError('network')
        with self.assertRaisesRegex(RuntimeError,'network'):
            execute_batch(candidate=candidate,batch_number=1,receipt_path=receipt,executor=fail)
        self.assertEqual(len(calls),1)
        saved=json.loads(receipt.read_text())
        self.assertEqual(saved['status'],'REMOTE_UNCERTAIN')
        self.assertEqual(saved['retry_cap'],0)
        self.assertEqual(saved['live_checkpoint_mutations'],0)


if __name__=='__main__':
    unittest.main()
