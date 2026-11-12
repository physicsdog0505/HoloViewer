from __future__ import annotations

import unittest

from ptt_offline.pr147_monitor_adapter import (
    build_pr147_sync_monitor_evidence,
    build_pr147_system_health_evidence,
)


class Pr147MonitorAdapterTests(unittest.TestCase):
    def test_sync_projection_preserves_nulls_and_sanitizes_checkpoint(self):
        body=build_pr147_sync_monitor_evidence(
            publisher_checkpoint={
                "schema_version":"fixture",
                "job_id":"job-1",
                "state":"complete",
                "day":"2026-10-20",
                "source_identity":"source-1",
                "accepted":{"secret":"must-not-leak"},
            },
            job_telemetry={
                "schema_version":"holoviewer-sync-job-evidence-v1",
                "components":{"Publisher":{"job_id":"job-1","status":"completed"}},
            },
            publisher_observed_at="2026-10-20T06:00:00Z",
            publisher_last_progress_at="2026-10-20T06:00:00Z",
        )
        self.assertTrue(body["sanitized"])
        self.assertEqual(body["publisher_checkpoint"]["job_id"],"job-1")
        self.assertNotIn("accepted",body["publisher_checkpoint"])
        self.assertIsNone(body["r2_manifest"])
        self.assertIsNone(body["d1_snapshot"])
        self.assertIn("r2-manifest-unavailable",body["contract_gaps"])
        self.assertIn("sanitized-d1-snapshot-unavailable",body["contract_gaps"])

    def test_sync_projection_without_checkpoint_does_not_promote_telemetry(self):
        body=build_pr147_sync_monitor_evidence(
            publisher_checkpoint=None,
            job_telemetry={
                "schema_version":"holoviewer-sync-job-evidence-v1",
                "components":{"Publisher":{"status":"completed"}},
            },
        )
        self.assertIsNone(body["publisher_checkpoint"])
        self.assertIn("publisher-checkpoint-unavailable",body["contract_gaps"])

    def test_health_projection_keeps_missing_components_absent(self):
        collector={
            "observed_at":"2026-10-20T06:00:00Z",
            "semantic_check":{"status":"healthy"},
        }
        body=build_pr147_system_health_evidence(collector=collector)
        self.assertEqual(body["components"]["Collector"],collector)
        self.assertNotIn("Publisher",body["components"])
        self.assertIn("publisher-health-evidence-unavailable",body["contract_gaps"])
        self.assertIn("archive-health-evidence-unavailable",body["contract_gaps"])
        self.assertIn("production-api-health-evidence-unavailable",body["contract_gaps"])


if __name__=="__main__":
    unittest.main()
