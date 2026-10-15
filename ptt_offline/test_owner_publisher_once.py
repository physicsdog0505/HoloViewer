import json
import tempfile
import unittest
from pathlib import Path
from ptt_offline.owner_publisher_once import load_manual_evidence,row_fingerprint
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
            self.assertFalse(check({**row,"content":"changed"}))
            self.assertFalse(check({**row,"source_line":2}))
if __name__=="__main__": unittest.main()
