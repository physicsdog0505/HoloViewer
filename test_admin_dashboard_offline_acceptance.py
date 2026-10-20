from __future__ import annotations

import unittest
from admin_dashboard.coverage import project_coverage
from admin_dashboard.render import render_dashboard


def full_target_evidence(*, day, aids, missing=0, verified=True):
    return {
        "schema_version": "holoviewer-d1-sanitized-snapshot-v1",
        "sanitized": True,
        "job_binding": {
            "job_id": "job-1",
            "manifest_digest": "sha256:" + "a" * 64,
            "source_revision": "fixture-r1",
            "scope": {"day": day, "aids": aids},
        },
        "coverage": {
            "complete_partition_proven": True,
            "missing_identities": missing,
        },
        "verification": {
            "mode": "full_partition",
            "job_verified": verified,
            "manifest_digest_match": True,
            "identity_match": True,
            "count_match": missing == 0,
        },
    }


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
             "target_evidence": full_target_evidence(day="2026-10-03", aids=["day"], missing=1, verified=False)}]},
            {"date": "2026-10-04", "sources": [{"source": "ptt", "completeness_status": "COMPLETE",
             "expected_set": ["day"], "actual_set": ["day"],
             "target_evidence": full_target_evidence(day="2026-10-04", aids=["day"])}]},
        ]
        data = project_coverage(rows, start_day="2026-10-01", end_day="2026-10-04")
        self.assertEqual([x["status"] for x in data["days"]],
                         ["LOCAL_MISSING", "PARTIAL", "PENDING_SYNC", "COMPLETE"])
        self.assertEqual(data["days"][1]["source_line_gaps"], {"day": [4, 5]})


    def test_full_readback_for_wrong_day_or_aid_never_promotes_complete(self):
        rows = [{"date": "2026-10-04", "sources": [{"source": "ptt",
            "completeness_status": "COMPLETE", "expected_set": ["day"], "actual_set": ["day"],
            "target_evidence": full_target_evidence(day="2026-10-03", aids=["day"])}]}]
        result = project_coverage(rows, start_day="2026-10-04", end_day="2026-10-04")
        self.assertEqual(result["days"][0]["status"], "UNKNOWN")
        rows[0]["sources"][0]["target_evidence"] = full_target_evidence(day="2026-10-04", aids=["night"])
        result = project_coverage(rows, start_day="2026-10-04", end_day="2026-10-04")
        self.assertEqual(result["days"][0]["status"], "UNKNOWN")

    def test_bounded_sample_never_promotes_complete(self):
        rows = [{"date": "2026-10-01", "sources": [{
            "source": "ptt", "completeness_status": "COMPLETE",
            "expected_set": ["day"], "actual_set": ["day"],
            "target_evidence": {
                "schema_version": "holoviewer-d1-sanitized-snapshot-v1",
                "sanitized": True,
                "job_binding": {
                    "job_id": "job-1",
                    "manifest_digest": "sha256:" + "a" * 64,
                    "source_revision": "fixture-r1",
                },
                "coverage": {"complete_partition_proven": False, "missing_identities": 0},
                "verification": {
                    "mode": "bounded_sample",
                    "job_verified": False,
                    "manifest_digest_match": True,
                    "identity_match": True,
                    "count_match": True,
                },
            },
        }]}]
        data = project_coverage(rows, start_day="2026-10-01", end_day="2026-10-01")
        self.assertEqual(data["days"][0]["status"], "UNKNOWN")

    def test_legacy_self_asserted_verified_target_is_not_authority(self):
        rows = [{"date": "2026-10-01", "sources": [{
            "source": "ptt", "completeness_status": "COMPLETE",
            "expected_set": ["day"], "actual_set": ["day"],
            "target_evidence": {"verified": True, "all_expected_present": True},
        }]}]
        data = project_coverage(rows, start_day="2026-10-01", end_day="2026-10-01")
        self.assertEqual(data["days"][0]["status"], "UNKNOWN")

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
