import json
import tempfile
import unittest
from pathlib import Path
from ptt_offline.publisher_session import run_synthetic_one, load_checkpoint
from ptt_offline.public_today_contract import ContractError

class PublisherSessionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=str(Path(tmp.name)/"receipt.json")
        self.kw={"checkpoint_path":self.path,
                 "source_identity":"approved-fixture-digest",
                 "day":"2026-10-15","aids":["A1"]}
        self.rows=[{"aid":"A1","day":"2026-10-15",
                    "source_line":n,"push_id":f"p{n}",
                    "content":"MUST-NOT-APPEAR"} for n in range(1,7)]

    def executor(self,batch):
        return {"status":"ACK","batch_id":batch["batch_id"],
                "digest":batch["digest"],"http_requests":1,
                "d1_query_count":15,"d1_rows_written":12,
                "logical_rows_acked":len(batch["rows"])}

    def test_failure_before_ack_never_persists(self):
        attempts=[]
        def fail(batch):
            attempts.append(1)
            raise ContractError("synthetic remote failure")
        with self.assertRaises(ContractError):
            run_synthetic_one(**self.kw,rows=self.rows,executor=fail)
        self.assertEqual(len(attempts),1)
        self.assertFalse(Path(self.path).exists())

    def test_resume_and_idempotent_replay(self):
        first=run_synthetic_one(**self.kw,rows=self.rows,executor=self.executor)
        self.assertEqual(first["logical_rows_acked"],5)
        self.assertEqual(first["d1_rows_written"],12)
        self.assertEqual(first["checkpoint"]["aids"]["A1"],5)
        second=run_synthetic_one(**self.kw,rows=self.rows,executor=self.executor)
        self.assertEqual(second["logical_rows_acked"],1)
        self.assertEqual(second["checkpoint"]["aids"]["A1"],6)
        executed=[]
        third=run_synthetic_one(**self.kw,rows=self.rows,
                                executor=lambda b:executed.append(b))
        self.assertEqual(third["status"],"NO_NEW_ROWS")
        self.assertEqual(executed,[])
        self.assertNotIn("MUST-NOT-APPEAR",Path(self.path).read_text())

    def test_changed_source_identity_is_rejected(self):
        run_synthetic_one(**self.kw,rows=self.rows,executor=self.executor)
        with self.assertRaises(ContractError):
            load_checkpoint(Path(self.path),source_identity="other",
                            day="2026-10-15",aids=["A1"])

if __name__=="__main__":
    unittest.main()
