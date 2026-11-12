import unittest

from ptt_offline.d1_transport_contract import execute_once
from ptt_offline.public_today_contract import ContractError
from ptt_offline.resumable_publisher import new_checkpoint, make_batch, apply_ack


class D1TransportContractTests(unittest.TestCase):
    def setUp(self):
        cp=new_checkpoint(source_identity="fixture",day="2026-10-15",aids=["A1"])
        self.batch=make_batch(checkpoint=cp,rows=[
            {"aid":"A1","day":"2026-10-15","source_line":1,"push_id":"p1"},
            {"aid":"A1","day":"2026-10-15","source_line":2,"push_id":"p2"},
        ])
        self.cp=cp

    def test_single_attempt_ack_can_advance_checkpoint(self):
        calls=[]
        def executor(batch):
            calls.append(batch["batch_id"])
            return {"status":"ACK","batch_id":batch["batch_id"],
                    "digest":batch["digest"],"http_requests":1,
                    "d1_query_count":6,"d1_rows_written":5,"logical_rows_acked":2}
        ack=execute_once(batch=self.batch,executor=executor)
        self.assertEqual(len(calls),1)
        cp2=apply_ack(checkpoint=self.cp,batch=self.batch,ack=ack)
        self.assertEqual(cp2["aids"]["A1"],2)

    def test_five_pushes_with_write_amplification_within_budget(self):
        rows=[{"aid":"A1","day":"2026-10-15","source_line":n,
               "push_id":f"p{n}","source_record_key":f"src:{n}"}
              for n in range(1,6)]
        batch=make_batch(checkpoint=self.cp,rows=rows)
        ack=execute_once(batch=batch,executor=lambda b:{
            "status":"ACK","batch_id":b["batch_id"],"digest":b["digest"],
            "http_requests":1,"d1_query_count":16,"d1_rows_written":12,
            "logical_rows_acked":5})
        self.assertEqual(ack["rows_acked"],5)
        self.assertEqual(ack["d1_rows_written"],12)

    def test_failure_is_not_retried(self):
        calls=[]
        def executor(batch):
            calls.append(1)
            return {"status":"FAIL","batch_id":batch["batch_id"],
                    "digest":batch["digest"],"http_requests":1,
                    "d1_query_count":1,"d1_rows_written":0,"logical_rows_acked":0}
        with self.assertRaises(ContractError):
            execute_once(batch=self.batch,executor=executor)
        self.assertEqual(len(calls),1)

    def test_partial_or_over_budget_ack_rejected(self):
        for response in (
            {"status":"ACK","batch_id":self.batch["batch_id"],"digest":self.batch["digest"],
             "http_requests":1,"d1_query_count":6,"d1_rows_written":5,"logical_rows_acked":1},
            {"status":"ACK","batch_id":self.batch["batch_id"],"digest":self.batch["digest"],
             "http_requests":2,"d1_query_count":6,"d1_rows_written":5,"logical_rows_acked":2},
            {"status":"ACK","batch_id":self.batch["batch_id"],"digest":self.batch["digest"],
             "http_requests":1,"d1_query_count":31,"d1_rows_written":5,"logical_rows_acked":2},
            {"status":"ACK","batch_id":self.batch["batch_id"],"digest":self.batch["digest"],
             "http_requests":1,"d1_query_count":6,"d1_rows_written":21,
             "logical_rows_acked":2},
        ):
            with self.subTest(response=response), self.assertRaises(ContractError):
                execute_once(batch=self.batch,executor=lambda _:response)

if __name__=="__main__":
    unittest.main()
