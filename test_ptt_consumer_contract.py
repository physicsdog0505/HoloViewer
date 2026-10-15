"""#48 reviewed PTT consumer-envelope boundary tests (no backend/router)."""
import unittest

from platform_adapter.ptt_consumer_contract import (
    PUBLIC_PUSH_FIELDS, validate_ptt_consumer_envelope,
)
from platform_adapter.public_api import PublicAPIUnavailable


def fixture():
    return {
        "schema_version": "public-consumer-v1",
        "day": "2026-10-15",
        "as_of": "2026-10-15T08:00:00Z",
        "freshness": {"status": "fresh", "last_success_at": "2026-10-15T07:59:00Z"},
        "completeness": {"status": "partial", "gap": True},
        "checkpoint": "opaque:checkpoint",
        "pushes": [{
            "push_id": "ptt:v1:" + "a" * 64,
            "aid": "M.1234567890.A.ABC",
            "source_line": 123,
            "kind": "推",
            "author": "viewer",
            "content": "fixture",
            "occurred_at": "2026-10-15T08:00:00Z",
            "floor": 5,
            "source_url": "https://www.ptt.cc/bbs/C_Chat/M.1234567890.A.ABC.html",
        }],
        "page": {"limit": 50, "has_more": False, "next_checkpoint": None},
    }


class PttReadBoundaryTest(unittest.TestCase):
    def test_today_uses_exact_reviewed_public_fields(self):
        payload = fixture()
        self.assertEqual(set(payload["pushes"][0]), PUBLIC_PUSH_FIELDS)
        self.assertIs(validate_ptt_consumer_envelope(
            payload, day="2026-10-15"
        ), payload)

    def test_history_opaque_pagination_is_recognized(self):
        payload = fixture()
        payload["page"]["limit"] = 200
        self.assertIs(validate_ptt_consumer_envelope(
            payload, day="2026-10-15", history=True
        ), payload)

    def test_never_marks_unknown_day_or_internals_complete(self):
        samples = []
        obj = fixture(); obj["day"] = "2026-10-14"; samples.append(obj)
        obj = fixture(); obj["pushes"][0]["origin"] = "collector"; samples.append(obj)
        obj = fixture(); obj["pushes"][0]["cursor"] = 5; samples.append(obj)
        obj = fixture(); obj["freshness"] = {"state": "fresh"}; samples.append(obj)
        obj = fixture(); obj["completeness"] = {"status": "complete"}; samples.append(obj)
        obj = fixture(); obj["page"]["limit"] = 999999; samples.append(obj)
        obj = fixture(); obj["pushes"][0]["kind"] = "invented"; samples.append(obj)
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(PublicAPIUnavailable):
                validate_ptt_consumer_envelope(sample, day="2026-10-15")

    def test_unavailable_is_not_treated_as_empty(self):
        for value in ({}, None, {"pushes": []}):
            with self.subTest(value=value), self.assertRaises(PublicAPIUnavailable):
                validate_ptt_consumer_envelope(value, day="2026-10-15")


if __name__ == "__main__":
    unittest.main()
