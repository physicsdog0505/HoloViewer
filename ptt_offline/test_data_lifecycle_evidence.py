from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ptt_offline.data_lifecycle_evidence import (
    build_collector_semantic_evidence,
    build_expected_aid_contract,
    build_source_coverage,
    expected_aids_for_pr147,
)
from ptt_offline.publisher_telemetry import update_publisher_telemetry


FIXTURE=Path(__file__).parent/"fixtures"/"data_lifecycle"/"ptt_complete_day.json"


class DataLifecyclePttEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_expected_aids_require_day_and_night_authority(self):
        src=self.fixture["expected_aids"]
        body=build_expected_aid_contract(
            day=src["day"],entries=src["entries"],authority=src["authority"])
        self.assertEqual(body["status"],"COMPLETE")
        self.assertEqual([x["period"] for x in body["expected"]],["day","night"])
        self.assertEqual(body["planning_key"],["day","aid","source_line"])
        self.assertEqual(body["contract_gaps"],[])
        self.assertEqual(body["conflicts"],[])

        projected=expected_aids_for_pr147(body)
        self.assertEqual(projected["expected_aids"],["1grg4Pag","1grNight"])
        self.assertEqual(projected["expected_authority"]["day"],src["day"])
        self.assertEqual(projected["expected_authority"]["version"],"fixture-v1")
        self.assertEqual(projected["contract_gaps"],[])

    def test_expected_aids_partial_and_contradictory_fail_closed(self):
        src=self.fixture["expected_aids"]
        partial=build_expected_aid_contract(
            day=src["day"],entries=src["entries"][:1],
            authority={"verified":False})
        self.assertEqual(partial["status"],"UNKNOWN")
        self.assertIn("expected-night-aid-missing",partial["contract_gaps"])

        projected=expected_aids_for_pr147(partial)
        self.assertIsNone(projected["expected_aids"])
        self.assertEqual(projected["contract_gaps"],
                         ["expected-AID-contract-not-complete-for-pr147"])
        duplicate=build_expected_aid_contract(
            day=src["day"],
            entries=[src["entries"][0],{**src["entries"][0],"aid":"1dupAid","part":1},
                     src["entries"][1]],
            authority=src["authority"])
        self.assertEqual(duplicate["status"],"CONFLICT")
        self.assertIn("duplicate-day-part",duplicate["conflicts"])

    def test_expected_aids_support_contiguous_split_parts(self):
        src=self.fixture["expected_aids"]
        entries=[
            {**src["entries"][0],"part":1},
            {**src["entries"][0],"part":2,"aid":"1dayPart2",
             "authority_record_id":"fixture-day-2"},
            {**src["entries"][1],"part":1},
        ]
        body=build_expected_aid_contract(
            day=src["day"],entries=entries,authority=src["authority"])
        self.assertEqual(body["status"],"COMPLETE")
        self.assertEqual(
            [(x["period"],x["part"]) for x in body["expected"]],
            [("day",1),("day",2),("night",1)],
        )

    def test_coverage_preserves_non_push_and_legal_empty_push(self):
        src=self.fixture["coverage"]
        body=build_source_coverage(**src)
        self.assertEqual(body["status"],"COMPLETE")
        self.assertEqual(body["line_counts"],{
            "total":6,"push":3,"non_push":3,"legal_empty_push":1})
        self.assertEqual(body["legal_empty_push_source_lines"],[4])
        self.assertEqual(body["non_push_source_lines"],[1,2,5])
        self.assertEqual(body["missing_source_lines"],[])

    def test_coverage_detects_gap_duplicate_conflict_and_bad_empty_push(self):
        src=self.fixture["coverage"]
        gap=build_source_coverage(
            day=src["day"],aid=src["aid"],article_start_line=1,
            final_source_line=6,lines=[x for x in src["lines"] if x["source_line"]!=5])
        self.assertEqual(gap["status"],"REPAIR_NEEDED")
        self.assertEqual(gap["missing_source_lines"],[5])
        bad=[*src["lines"],{**src["lines"][2],"record_type":"non_push"}]
        duplicate=build_source_coverage(
            day=src["day"],aid=src["aid"],article_start_line=1,
            final_source_line=6,lines=bad)
        self.assertEqual(duplicate["status"],"CONFLICT")
        self.assertIn("conflicting-duplicate-source-line",duplicate["conflicts"])
        empty=[dict(x) for x in src["lines"]]
        empty[2]={"source_line":3,"record_type":"push","content_empty":True}
        bad_empty=build_source_coverage(
            day=src["day"],aid=src["aid"],article_start_line=1,
            final_source_line=6,lines=empty)
        self.assertEqual(bad_empty["status"],"CONFLICT")
        self.assertIn("unclassified-empty-push",bad_empty["conflicts"])

    def test_collector_semantic_health_requires_watermark_and_gap_evidence(self):
        src=self.fixture["collector"]
        healthy=build_collector_semantic_evidence(**src)
        self.assertEqual(healthy["semantic_check"]["status"],"healthy")
        self.assertEqual(healthy["contract_gaps"],[])
        partial=build_collector_semantic_evidence(
            observed_at=None,active_aid=None,watermark_source_line=None,
            final_source_line=None,source_line_gaps=None,scan_truncated=None,
            process_alive=True)
        self.assertEqual(partial["semantic_check"]["status"],"unknown")
        self.assertGreaterEqual(len(partial["contract_gaps"]),5)

    def test_publisher_job_id_is_immutable_and_contract_gaps_are_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"publisher-telemetry.json"
            fixture=self.fixture["publisher"]
            first=update_publisher_telemetry(path,fixture)
            second=update_publisher_telemetry(path,{
                "status":"NO_NEW_ROWS",
                "observed_at":"2026-10-20T05:24:00+00:00",
                "sent":0,"http_posts":0,
            })
        a=first["components"]["Publisher"]
        b=second["components"]["Publisher"]
        self.assertEqual(a["job_id"],b["job_id"])
        self.assertEqual(a["source_identity"],"fixture-source-identity")
        self.assertEqual(a["target_identity"],"d1:holoviewer-public-v1")
        self.assertEqual(a["readback_evidence"]["verified_count"],1)
        self.assertIn("publisher-source-identity-unavailable",b["contract_gaps"])
        self.assertIn("publisher-target-identity-unavailable",b["contract_gaps"])
        self.assertIn("publisher-independent-readback-unavailable",b["contract_gaps"])
        self.assertIsNone(b["retry_after"])
        self.assertIsNone(b["backoff_seconds"])


if __name__=="__main__":
    unittest.main()
