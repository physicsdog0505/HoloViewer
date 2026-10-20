from __future__ import annotations

import unittest
from admin_dashboard.coverage import project_coverage
from admin_dashboard.render import render_dashboard


class OfflineAdminAcceptance(unittest.TestCase):
    def test_missing_date_is_visible_and_unknown(self):
        data = project_coverage([{"date": "2026-10-01", "sources": [{
            "source": "ptt", "completeness_status": "COMPLETE",
            "expected_set": ["day-AID"], "actual_set": ["day-AID"]
        }]}], start_day="2026-10-01", end_day="2026-10-03")
        self.assertEqual([x["date"] for x in data["days"]],
                         ["2026-10-01", "2026-10-02", "2026-10-03"])
        self.assertTrue(all(x["status"] == "UNKNOWN" for x in data["days"]))
        self.assertTrue(data["read_only"])

    def test_expected_aid_gaps_and_target_state_are_distinct(self):
        rows = [
            {"date": "2026-10-01", "sources": [{"source": "ptt", "completeness_status": "REPAIR_NEEDED",
             "expected_set": ["day", "night"], "actual_set": ["day"], "missing_ids": ["night"]}]},
            {"date": "2026-10-02", "sources": [{"source": "ptt", "completeness_status": "REPAIR_NEEDED",
             "expected_set": ["day"], "actual_set": ["day"], "source_line_gaps": {"day": [4, 5]}}]},
            {"date": "2026-10-03", "sources": [{"source": "ptt", "completeness_status": "COMPLETE",
             "expected_set": ["day"], "actual_set": ["day"],
             "target_evidence": {"verified": True, "all_expected_present": False}}]},
            {"date": "2026-10-04", "sources": [{"source": "ptt", "completeness_status": "COMPLETE",
             "expected_set": ["day"], "actual_set": ["day"],
             "target_evidence": {"verified": True, "all_expected_present": True}}]},
        ]
        data = project_coverage(rows, start_day="2026-10-01", end_day="2026-10-04")
        self.assertEqual([x["status"] for x in data["days"]],
                         ["LOCAL_MISSING", "PARTIAL", "PENDING_SYNC", "COMPLETE"])
        self.assertEqual(data["days"][1]["source_line_gaps"], {"day": [4, 5]})

    def test_duplicate_day_or_excess_range_rejected(self):
        with self.assertRaises(ValueError):
            project_coverage([{"date": "2026-10-01"}]*2, start_day="2026-10-01", end_day="2026-10-01")
        with self.assertRaises(ValueError):
            project_coverage([], start_day="2025-01-01", end_day="2026-10-20")

    def test_render_has_structured_controls_and_no_write_call(self):
        html = render_dashboard()
        for marker in ('id="coverage-rows"', 'id="sync-rows"', 'id="health-rows"',
                       'id="coverage-search"', 'id="from-day"', 'id="through-day"',
                       'id="coverage-sort"', 'id="refresh-all"', 'data-refresh="sync_monitor"',
                       'id="clear-filters"', "contract_gaps", "UNKNOWN"):
            self.assertIn(marker, html)
        self.assertIn("document.createElement", html)
        self.assertIn("textContent", html)
        self.assertNotIn("method:'POST'", html)
        self.assertNotIn("innerHTML", html)


if __name__ == "__main__":
    unittest.main()
