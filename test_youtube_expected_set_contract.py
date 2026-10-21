from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from data_lifecycle.youtube_expected_set import audit_recent, validate_expected_set

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures/data-lifecycle/youtube-expected-set-v1.sanitized.json"


class YouTubeExpectedSetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        assert payload["sanitized"] is True
        cls.documents = payload["documents"]

    def test_fixture_keeps_history66_and_today85_as_distinct_authorities(self):
        history = validate_expected_set(self.documents[0])
        today = validate_expected_set(self.documents[1])
        self.assertEqual((history["scope_kind"], self.documents[0]["scope"]["channel_count"]),
                         ("history-review-66", 66))
        self.assertEqual((today["scope_kind"], self.documents[1]["scope"]["channel_count"]),
                         ("today-approved-85", 85))
        self.assertNotEqual(history["scope_version"], today["scope_version"])
        self.assertNotEqual(history["expected_video_ids"], today["expected_video_ids"])

    def test_scope_count_cannot_be_cross_used(self):
        bad = copy.deepcopy(self.documents[0])
        bad["scope"]["channel_count"] = 85
        with self.assertRaisesRegex(ValueError, "scope channel_count mismatch"):
            validate_expected_set(bad)

    def test_actual_start_defines_asia_taipei_day(self):
        item = validate_expected_set(self.documents[1])
        self.assertEqual(item["day"], "2026-10-15")
        bad = copy.deepcopy(self.documents[1])
        bad["videos"][0]["actual_start"] = "2026-10-14T15:59:59Z"
        with self.assertRaisesRegex(ValueError, "outside Asia/Taipei day"):
            validate_expected_set(bad)

    def test_scheduled_start_never_substitutes_for_verified_actual_start(self):
        bad = copy.deepcopy(self.documents[1])
        row = bad["videos"][0]
        row["scheduled_start"] = row.pop("actual_start")
        with self.assertRaises((ValueError, TypeError)):
            validate_expected_set(bad)

    def test_actual_start_authority_is_exact_youtube_live_streaming_details(self):
        bad = copy.deepcopy(self.documents[1])
        bad["videos"][0]["actual_start_source"] = "scheduledStartTime"
        with self.assertRaisesRegex(ValueError, "actual_start authority mismatch"):
            validate_expected_set(bad)

    def test_revision_and_hash_are_required(self):
        bad = copy.deepcopy(self.documents[1])
        bad["source"]["hash"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "source.hash"):
            validate_expected_set(bad)
        bad = copy.deepcopy(self.documents[1])
        bad["videos"][0]["revision"] = ""
        with self.assertRaisesRegex(ValueError, "video revision required"):
            validate_expected_set(bad)

    def test_verified_requires_late_metadata_watermark_and_no_unknowns(self):
        pending = validate_expected_set(self.documents[2])
        self.assertEqual(pending["completeness_authority"], "UNKNOWN")
        self.assertEqual(pending["late_metadata_status"], "PENDING")
        bad = copy.deepcopy(self.documents[2])
        bad["completeness_authority"] = "VERIFIED"
        with self.assertRaisesRegex(ValueError, "VERIFIED set cannot contain UNKNOWN"):
            validate_expected_set(bad)

    def test_empty_verified_set_is_allowed_only_with_closed_authority(self):
        empty = copy.deepcopy(self.documents[0])
        empty["videos"] = []
        empty["expected_video_ids"] = []
        self.assertEqual(validate_expected_set(empty)["completeness_authority"], "VERIFIED")
        empty["late_metadata_watermark"]["status"] = "PENDING"
        with self.assertRaisesRegex(ValueError, "VERIFIED set requires satisfied"):
            validate_expected_set(empty)

    def test_expected_ids_exactly_match_verified_rows(self):
        bad = copy.deepcopy(self.documents[0])
        bad["expected_video_ids"] = ["other000001"]
        with self.assertRaisesRegex(ValueError, "exactly match"):
            validate_expected_set(bad)

    def test_recent_audit_is_bounded_offline_and_never_merges_scopes(self):
        result = audit_recent(self.documents, as_of_day="2026-10-20", window_days=30)
        self.assertEqual(result["window"], {
            "start_day": "2026-09-21", "end_day": "2026-10-20", "days": 30})
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["external_writes"], 0)
        self.assertTrue(result["scope_merge_forbidden"])
        scopes = {(row["day"], row["scope_kind"]) for row in result["rows"]}
        self.assertIn(("2026-10-15", "history-review-66"), scopes)
        self.assertIn(("2026-10-15", "today-approved-85"), scopes)

    def test_recent_audit_rejects_unbounded_or_out_of_window_input(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 31"):
            audit_recent(self.documents, as_of_day="2026-10-20", window_days=32)
        old = copy.deepcopy(self.documents[0])
        old["day"] = "2026-08-01"
        old["videos"][0]["actual_start"] = "2026-08-01T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "outside bounded audit window"):
            audit_recent([old], as_of_day="2026-10-20", window_days=30)

    def test_duplicate_day_scope_version_evidence_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate day/scope/version"):
            audit_recent([self.documents[0], copy.deepcopy(self.documents[0])],
                         as_of_day="2026-10-20", window_days=30)


if __name__ == "__main__":
    unittest.main()
