import unittest

from ptt_offline.public_today_contract import ContractError
from ptt_offline.resumable_publisher import new_checkpoint, make_batch, apply_ack


class ResumablePublisherTests(unittest.TestCase):
    def setUp(self):
        self.cp=new_checkpoint(source_identity="fixture-db-sha256",
                               day="2026-10-15",aids=["A1","A2"])

    def test_bounded_batch_and_replay_skip(self):
        rows=[
            {"aid":"A1","day":"2026-10-15","source_line":n,"push_id":f"p{n}"}
            for n in range(1,8)
        ]
        batch=make_batch(checkpoint=self.cp,rows=rows,batch_cap=5)
        self.assertEqual(len(batch["rows"]),5)
        self.assertEqual(batch["request_cap"],1)
        self.assertEqual(batch["write_cap"],5)
        self.assertEqual(batch["retry_cap"],0)
        ack={"batch_id":batch["batch_id"],"digest":batch["digest"],
             "rows_acked":5,"status":"ACK"}
        cp2=apply_ack(checkpoint=self.cp,batch=batch,ack=ack)
        self.assertEqual(cp2["aids"]["A1"],5)
        replay=make_batch(checkpoint=cp2,rows=rows,batch_cap=5)
        self.assertEqual([r["source_line"] for r in replay["rows"]],[6,7])

    def test_bad_ack_never_advances_checkpoint(self):
        batch=make_batch(checkpoint=self.cp,rows=[
            {"aid":"A1","day":"2026-10-15","source_line":1,"push_id":"p1"}])
        before=dict(self.cp["aids"])
        with self.assertRaises(ContractError):
            apply_ack(checkpoint=self.cp,batch=batch,ack={
                "batch_id":batch["batch_id"],"digest":"wrong",
                "rows_acked":1,"status":"ACK"})
        self.assertEqual(self.cp["aids"],before)
        self.assertIsNone(self.cp["last_batch_id"])

    def test_scope_and_caps_fail_closed(self):
        bad_rows=[
            {"aid":"A3","day":"2026-10-15","source_line":1},
            {"aid":"A1","day":"2026-10-16","source_line":1},
        ]
        for row in bad_rows:
            with self.subTest(row=row), self.assertRaises(ContractError):
                make_batch(checkpoint=self.cp,rows=[row])
        with self.assertRaises(ContractError):
            make_batch(checkpoint=self.cp,rows=[],batch_cap=6)

if __name__=="__main__":
    unittest.main()
