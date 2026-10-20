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


    def test_archive_projection_keeps_job_coverage_and_aid_authority_separate(self):
        from admin_dashboard.contracts import build_sync_monitor
        projection = {
            "job_id": "archive-job-1",
            "component": "Archive",
            "source": "PTT Archive",
            "target": "workers-static-assets",
            "last_attempted_at": "2026-10-20T10:00:00Z",
            "last_successful_at": "2026-10-20T10:01:00Z",
            "status": "completed",
            "attempt_count": 1,
            "retry_after": None,
            "backoff_seconds": None,
            "input_count": 10,
            "published_count": 10,
            "verified_count": 10,
            "error_code": None,
            "error_message": None,
            "last_progress_at": "2026-10-20T10:02:00Z",
            "evidence_source": "#48 archive delivery evidence",
            "evidence_observed_at": "2026-10-20T10:02:00Z",
            "contract_gaps": [],
            "evidence_source_fields": {
                "source_revision": "fixture-r1",
                "source_hash": "sha256:" + "c" * 64,
                "manifest_digest": "sha256:" + "d" * 64,
                "snapshot_id": "sha256:" + "e" * 64,
                "readback_observed_at": "2026-10-20T10:02:00Z",
                "verification_mode": "full_partition",
                "job_verified": True,
                "coverage_summary": {"status": "COMPLETE"},
                "expected_aid_completeness": {"status": "VERIFIED"},
            },
        }
        monitor = build_sync_monitor({"archive_sync_job": projection})
        archive = next(x for x in monitor["jobs"] if x["component"] == "Archive")
        self.assertEqual(archive["target_kind"], "workers-static-assets")
        self.assertEqual(archive["status"], "completed")
        self.assertEqual(archive["archive_coverage_status"], "COMPLETE")
        self.assertEqual(archive["expected_aid_status"], "VERIFIED")
        self.assertTrue(archive["job_verified"])
        self.assertEqual(archive["evidence_source_fields"]["coverage_summary"]["status"], "COMPLETE")

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
                       'id="clear-filters"', 'id="coverage-cards"', 'id="sync-cards"',
                       'id="health-cards"', "contract_gaps", "UNKNOWN", "View raw evidence"):
            self.assertIn(marker, html)
        self.assertIn("document.createElement", html)
        self.assertIn("textContent", html)
        self.assertNotIn("method:'POST'", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("@media(max-width:760px)", html)
        self.assertIn("table-wrap", html)
        for forbidden in ("重新同步", "重新執行", "Retry Publisher", "Replay", "Upload", "Deploy",
                          "Restart Collector", "Restart Publisher", "R2 upload", "D1 write"):
            self.assertNotIn(forbidden, html)


if __name__ == "__main__":
    unittest.main()
