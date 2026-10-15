import json
import tempfile
import unittest
from contextlib import nullcontext,redirect_stdout
from unittest.mock import patch
from io import StringIO
from ptt_offline.owner_publisher_once import main
from pathlib import Path
from ptt_offline.owner_publisher_once import load_manual_evidence,row_fingerprint,sign_time_proof
from ptt_offline.public_today_contract import ContractError

class OwnerPublisherOnceTests(unittest.TestCase):
    def test_manual_evidence_requires_exact_source_and_row_fingerprint(self):
        row={"aid":"1gepPtNy","source_line":1,"source_record_key":"1gepPtNy:1",
             "occurred_at":"2026-10-15T10:00:00Z","kind":"推","author":"tester",
             "content":"真實樣本型態","source_url":"https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html"}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"approval.json"
            data={"source_identity":"source-sha","day":"2026-10-15","aid":"1gepPtNy",
                  "authority":"PENDING_REVIEW","approved_rows":[{"source_line":1,
                  "row_sha256":row_fingerprint(row)}]}
            path.write_text(json.dumps(data),encoding="utf-8")
            with self.assertRaises(ContractError):
                load_manual_evidence(path,source_identity="source-sha",day="2026-10-15",aid="1gepPtNy")
            data["authority"]="OWNER_REVIEWED_EXTERNAL"
            path.write_text(json.dumps(data),encoding="utf-8")
            check=load_manual_evidence(path,source_identity="source-sha",day="2026-10-15",aid="1gepPtNy")
            self.assertTrue(check(row))
            signed=load_manual_evidence(path,source_identity="source-sha",day="2026-10-15",
                aid="1gepPtNy",proof_secret="x"*40)(row)
            self.assertEqual(len(signed),64)
            self.assertEqual(signed,sign_time_proof(row,"x"*40))
            self.assertFalse(check({**row,"content":"changed"}))
            self.assertFalse(check({**row,"source_line":2}))
    def test_readonly_inspect_never_stages_send_or_requires_year(self):
        receipt={"identity":{"aid":"1gepPtNy"},"aid":"1gepPtNy","source_rows_examined":6,
                 "inferred_day":[],"pending":[{"source_line":1}],"coverage":{"complete":False}}
        output=StringIO()
        with (patch("ptt_offline.owner_publisher_once.open_source",return_value=nullcontext(object())),
             patch("ptt_offline.owner_publisher_once.audit_source_day",return_value=receipt),
             patch("ptt_offline.owner_publisher_once.stage_verified_day",
                   side_effect=AssertionError("strict stage cannot run for inspect")),
             redirect_stdout(output)):
            main(["--source","ignored","--day","2026-10-15","--aid","1gepPtNy",
                  "--checkpoint","/not/used","--inspect"])
        data=json.loads(output.getvalue())
        self.assertEqual(data["pending_rows"],1)
        self.assertEqual(data["d1_requests"],0)

if __name__=="__main__": unittest.main()
