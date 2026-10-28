from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.daily_history_runtime import _downstream_authorization


class DailyHistoryMonthlyGateTests(unittest.TestCase):
    def test_missing_authorization_receipt_holds_monthly_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            result=_downstream_authorization(config={},state_root=root,day="2026-10-25")
            self.assertFalse(result["authorized"])
            self.assertEqual(result["reason"],"authorization-receipt-unavailable")

    def test_health_pass_without_downstream_authorization_still_holds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            path=root/"collector-health/2026-10-25.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "day":"2026-10-25",
                "health_gate_passed":True,
                "downstream_authorized":False,
                "downstream_status":"HOLD_FINALIZATION",
            }),encoding="utf-8")
            result=_downstream_authorization(config={},state_root=root,day="2026-10-25")
            self.assertFalse(result["authorized"])
            self.assertEqual(result["reason"],"HOLD_FINALIZATION")

    def test_explicit_verified_health_authorization_allows_monthly_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            path=root/"gate.json"
            path.write_text(json.dumps({
                "day":"2026-10-25",
                "health_gate_passed":True,
                "downstream_authorized":True,
            }),encoding="utf-8")
            result=_downstream_authorization(
                config={"downstream_authorization_path":str(path)},
                state_root=root,day="2026-10-25",
            )
            self.assertTrue(result["authorized"])
            self.assertIsNone(result["reason"])


if __name__=="__main__":
    unittest.main()
