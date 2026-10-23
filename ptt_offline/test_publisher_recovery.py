import json
import tempfile
import unittest
from pathlib import Path

from ptt_offline.publisher_recovery import recover_pending_state
from ptt_offline.owner_http_transport import RemoteOutcomeUnknown, ReconcileUnavailable

def batch():
    rows=[
        {"push_id":"ptt:v1:"+"a"*64,"aid":"1abc","day":"2026-10-23",
         "source_line":10,"kind":"推","author":"u","content":"x",
         "occurred_at":"2026-10-23T12:00:00Z","floor":None,
         "source_url":"https://www.ptt.cc/bbs/C_Chat/M.1792753209.A.FD7.html",
         "source_record_key":"1abc:10","time_proof":"proof"}
    ]
    return {"batch_id":"ptt48:test","digest":"digest","source_identity":"s"*64,
            "day":"2026-10-23","rows":rows,"request_cap":1,"write_cap":1,"retry_cap":0}

class RecoveryTests(unittest.TestCase):
    def state(self,path):
        b=batch()
        Path(path).write_text(json.dumps({
            "status":"REMOTE_UNCERTAIN","source_identity":"s"*64,
            "accepted":{"1abc:9":"old"},"pending_batch_id":b["batch_id"],
            "pending_batch":b,"pending_accepted_updates":{"1abc:10":"new"},
            "pending_aid":"1abc","baseline_source_line":9,
            "legacy_backlog_fence_v2":True,"recovery_attempts":0
        }),encoding="utf-8")
        return b

    def test_all_present_advances_local_checkpoint_without_replay(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; b=self.state(p)
            called=[]
            result=recover_pending_state(p,
                reconcile_executor=lambda _:{"status":"RECONCILE","outcome":"ALL_PRESENT",
                    "batch_id":b["batch_id"],"digest":b["digest"],"rows_checked":1,"present":1,"mismatched":0},
                publish_executor=lambda _:called.append(1),clock=lambda:100)
            self.assertEqual(result["status"],"RECOVERED_REMOTE_COMMIT")
            self.assertEqual(result["budget_batches"],1)
            self.assertEqual(result["budget_rows"],1)
            self.assertEqual(result["budget_modeled_writes"],4)
            self.assertEqual(result["budget_modeled_queries"],7)
            self.assertEqual(called,[])
            saved=json.loads(p.read_text())
            self.assertEqual(saved["status"],"ACKED")
            self.assertEqual(saved["accepted"]["1abc:10"],"new")
            self.assertTrue(saved["reconciled_from_remote_commit"])

    def test_none_present_replays_exact_batch_once(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; b=self.state(p)
            seen=[]
            def publish(got):
                seen.append(got)
                return {"status":"ACK","batch_id":b["batch_id"],"digest":b["digest"],
                        "logical_rows_acked":1,"d1_rows_written":0,
                        "d1_query_count":7,"http_requests":1}
            result=recover_pending_state(p,
                reconcile_executor=lambda _:{"status":"RECONCILE","outcome":"NONE_PRESENT",
                    "batch_id":b["batch_id"],"digest":b["digest"],"rows_checked":1,"present":0,"mismatched":0},
                publish_executor=publish,clock=lambda:100)
            self.assertEqual(result["status"],"ACK")
            self.assertEqual(result["recovery_status"],"RECOVERED_REPLAY")
            self.assertEqual(result["budget_batches"],1)
            self.assertEqual(result["budget_modeled_writes"],4)
            self.assertEqual(result["budget_modeled_queries"],7)
            self.assertEqual(seen,[b])
            self.assertEqual(json.loads(p.read_text())["status"],"ACKED")

    def test_none_present_reconcile_can_wait_without_replay_when_budget_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; b=self.state(p)
            called=[]
            result=recover_pending_state(p,
                reconcile_executor=lambda _:{"status":"RECONCILE","outcome":"NONE_PRESENT",
                    "batch_id":b["batch_id"],"digest":b["digest"],"rows_checked":1,"present":0,"mismatched":0},
                publish_executor=lambda _:called.append(1),clock=lambda:100,allow_replay=False)
            self.assertEqual(result["status"],"RECOVERY_WAIT")
            self.assertTrue(result["budget_blocked"])
            self.assertEqual(result["reconcile_reads"],1)
            self.assertEqual(called,[])
            saved=json.loads(p.read_text())
            self.assertEqual(saved["status"],"REMOTE_UNCERTAIN")
            self.assertEqual(saved["last_recovery_error"],"DAILY_BUDGET_BLOCKED")

    def test_partial_commit_quarantines_source(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; b=self.state(p)
            result=recover_pending_state(p,
                reconcile_executor=lambda _:{"status":"RECONCILE","outcome":"PARTIAL_OR_MISMATCH",
                    "batch_id":b["batch_id"],"digest":b["digest"],"rows_checked":1,"present":0,"mismatched":1},
                publish_executor=lambda _:self.fail("must not replay"),clock=lambda:100)
            self.assertEqual(result["status"],"RECOVERY_QUARANTINED")
            saved=json.loads(p.read_text())
            self.assertEqual(saved["status"],"STOP_MANUAL")
            self.assertEqual(saved["recovery_reason"],"PARTIAL_OR_MISMATCH")

    def test_reconcile_unavailable_uses_persisted_backoff(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; self.state(p)
            def unavailable(_): raise ReconcileUnavailable("down")
            first=recover_pending_state(p,reconcile_executor=unavailable,
                publish_executor=lambda _:None,clock=lambda:100)
            self.assertEqual(first["status"],"RECOVERY_WAIT")
            self.assertEqual(first["retry_after_seconds"],30)
            second=recover_pending_state(p,reconcile_executor=unavailable,
                publish_executor=lambda _:None,clock=lambda:110)
            self.assertEqual(second["status"],"RECOVERY_WAIT")
            self.assertGreaterEqual(second["retry_after_seconds"],20)

    def test_replay_ambiguous_returns_to_backoff(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"state.json"; b=self.state(p)
            def ambiguous(_): raise RemoteOutcomeUnknown("disconnect")
            result=recover_pending_state(p,
                reconcile_executor=lambda _:{"status":"RECONCILE","outcome":"NONE_PRESENT",
                    "batch_id":b["batch_id"],"digest":b["digest"],"rows_checked":1,"present":0,"mismatched":0},
                publish_executor=ambiguous,clock=lambda:100)
            self.assertEqual(result["status"],"RECOVERY_WAIT")
            saved=json.loads(p.read_text())
            self.assertEqual(saved["status"],"REMOTE_UNCERTAIN")
            self.assertEqual(saved["recovery_attempts"],1)

if __name__=="__main__":
    unittest.main()
