from __future__ import annotations

import unittest

from ptt_offline.expected_aid_discovery_adapter import expected_aids_from_discovery
from ptt_offline.data_lifecycle_evidence import expected_aids_for_pr147


AUTH={
    "kind":"collector-discovery-receipt",
    "evidence_id":"fixture-discovery-20261020",
    "observed_at":"2026-10-20T00:10:00Z",
    "verified":True,
    "version":"fixture-v1",
    "issuer":"collector-discovery",
}


class ExpectedAidDiscoveryAdapterTests(unittest.TestCase):
    def test_maps_day_night_and_assigns_split_parts_by_timestamp(self):
        body=expected_aids_from_discovery(
            day="2026-10-20",
            authority=AUTH,
            targets=[
                {"aid":"#1night01","url":"https://x/night","period":"晚間","timestamp":30},
                {"aid":"#1day002","url":"https://x/day2","period":"日間","timestamp":20},
                {"aid":"#1day001","url":"https://x/day1","period":"日間","timestamp":10},
            ],
        )
        self.assertEqual(body["status"],"COMPLETE")
        self.assertEqual(
            [(x["period"],x["part"],x["aid"]) for x in body["expected"]],
            [("day",1,"#1day001"),("day",2,"#1day002"),("night",1,"#1night01")],
        )
        projected=expected_aids_for_pr147(body)
        self.assertEqual(projected["expected_aids"],["#1day001","#1day002","#1night01"])

    def test_all_day_is_complete_without_synthetic_day_night(self):
        body=expected_aids_from_discovery(
            day="2026-10-20",
            authority=AUTH,
            targets=[
                {"aid":"#1allDay1","url":"https://x/all","period":"本日","timestamp":10},
            ],
        )
        self.assertEqual(body["status"],"COMPLETE")
        self.assertEqual(body["expected"][0]["period"],"all_day")
        self.assertEqual(body["contract_gaps"],[])

    def test_unsupported_period_is_conflict(self):
        body=expected_aids_from_discovery(
            day="2026-10-20",
            authority=AUTH,
            targets=[
                {"aid":"#1weird1","url":"https://x/weird","period":"未知","timestamp":10},
            ],
        )
        self.assertEqual(body["status"],"CONFLICT")
        self.assertIn("unsupported-discovery-target",body["conflicts"])


if __name__=="__main__":
    unittest.main()
