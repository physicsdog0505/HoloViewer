import json
import tempfile
import unittest
from pathlib import Path

from ptt_offline.publisher_admission import allows_batch,record,snapshot
from ptt_offline.public_today_contract import ContractError

class AdmissionTests(unittest.TestCase):
    def test_six_batches_block_seventh_across_reload(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"admission.json"
            for i in range(6):
                totals=record(p,batches=1,rows=10,modeled_queries=25,modeled_writes=22,now=100+i)
            self.assertEqual(totals["batches"],6)
            self.assertFalse(allows_batch(p,now=110))
            # Simulate process restart: state comes only from disk.
            self.assertEqual(snapshot(p,now=110)["batches"],6)
            self.assertFalse(allows_batch(p,now=110))

    def test_old_entries_expire_after_sixty_seconds(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"admission.json"
            record(p,batches=1,rows=10,modeled_queries=25,modeled_writes=22,now=100)
            self.assertFalse(snapshot(p,now=159)["batches"]==0)
            self.assertEqual(snapshot(p,now=161)["batches"],0)
            self.assertTrue(allows_batch(p,now=161))

    def test_future_or_corrupt_ledger_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"admission.json"
            p.write_text(json.dumps({"version":1,"entries":[{"at":999,"batches":1}]}))
            with self.assertRaises(ContractError):
                snapshot(p,now=100)
            p.write_text("{bad")
            with self.assertRaises(ContractError):
                snapshot(p,now=100)

if __name__=="__main__":
    unittest.main()
