from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from data_lifecycle.youtube_semantic_health import (
    build_semantic_health,
    expected_set_authority_envelope,
)

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "fixtures/data-lifecycle/youtube-api-semantic-health.sanitized.json"
EXPECTED = ROOT / "fixtures/data-lifecycle/youtube-expected-set-v1.sanitized.json"


class YouTubeSemanticHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.expected = json.loads(EXPECTED.read_text(encoding="utf-8"))["documents"]

    def test_health_200_without_semantic_watermark_stays_unknown(self):
        out = build_semantic_health(self.fixture)
        health = next(x for x in out["probes"] if x["name"] == "health")
        self.assertEqual(health["http_status"], 200)
        self.assertEqual(health["semantic_status"], "unknown")
        self.assertEqual(health["reason"], "reachability-only")

    def test_stale_today_watermark_is_degraded(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["semantic_watermark"] = "2026-10-20T11:50:00Z"
        raw["probes"]["today"]["source_freshness"] = "stale"
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["semantic_status"], "degraded")
        self.assertEqual(out["overall_status"], "degraded")

    def test_schema_mismatch_is_never_healthy(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["schema_version"] = "wrong-schema"
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["semantic_status"], "unhealthy")
        self.assertNotEqual(out["overall_status"], "healthy")

    def test_gap_or_partial_evidence_is_degraded(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["gap"] = True
        raw["probes"]["today"]["coverage_status"] = "partial"
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["semantic_status"], "degraded")

    def test_fresh_schema_watermark_no_gap_is_healthy(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"].pop("history")
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["semantic_status"], "healthy")
        self.assertEqual(out["overall_status"], "healthy")

    def test_unknown_authority_is_unknown(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["authority"] = "unknown"
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["semantic_status"], "unknown")

    def test_sanitized_fixture_contains_no_sensitive_or_content_fields(self):
        lowered = FIXTURE.read_text(encoding="utf-8").lower()
        for forbidden in (
            '"title"', '"body"', '"content"', '"author"', '"cookie"',
            '"authorization"', '"headers"', '"secret"', '"password"',
            '"api_key"', '"token"',
        ):
            self.assertNotIn(forbidden, lowered)

    def test_producer_is_offline_and_zero_request_budget(self):
        out = build_semantic_health(self.fixture)
        self.assertEqual(out["query_budget"]["http_requests_used"], 0)
        self.assertEqual(out["query_budget"]["http_requests_max"], 0)
        self.assertEqual(out["producer_mode"], "offline-sanitized-projection")

    def test_expected_set_maps_explicitly_into_pr147_authority_envelope(self):
        out = expected_set_authority_envelope(self.expected[0])
        self.assertEqual(out["day"], "2026-10-15")
        self.assertIn("+", out["version"])
        self.assertEqual(out["scope"]["kind"], "history-review-66")
        self.assertEqual(out["completeness_authority"], "VERIFIED")
        self.assertEqual(out["unknown_cases"], [])
        self.assertEqual(out["late_metadata_watermark"]["status"], "SATISFIED")

    def test_expected_set_66_and_85_scopes_remain_non_interchangeable(self):
        history = expected_set_authority_envelope(self.expected[0])
        today = expected_set_authority_envelope(self.expected[1])
        self.assertEqual(history["scope"]["kind"], "history-review-66")
        self.assertEqual(today["scope"]["kind"], "today-approved-85")
        self.assertNotEqual(history["scope"]["version"], today["scope"]["version"])
        self.assertNotEqual(history["scope"]["hash"], today["scope"]["hash"])

    def test_pending_expected_set_maps_to_unverified_authority(self):
        out = expected_set_authority_envelope(self.expected[2])
        self.assertFalse(out["verified"])
        self.assertEqual(out["completeness_authority"], "UNKNOWN")
        self.assertTrue(out["unknown_cases"])

    def test_forbidden_field_is_rejected(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["title"] = "must not export"
        with self.assertRaisesRegex(ValueError, "forbidden sensitive/content field"):
            build_semantic_health(raw)

    def test_sensitive_key_patterns_are_rejected(self):
        for key in ("hmac_secret", "client_secret", "access_token", "wrangler_credential", "x_api_key"):
            with self.subTest(key=key):
                raw = copy.deepcopy(self.fixture)
                raw["probes"]["today"][key] = "sensitive"
                with self.assertRaisesRegex(ValueError, "forbidden sensitive/content field"):
                    build_semantic_health(raw)

    def test_base_url_rejects_userinfo_query_fragment_and_unapproved_host(self):
        bad_values = (
            "https://user:pass@holoviewer-public-api.singlebagel.workers.dev",
            "https://holoviewer-public-api.singlebagel.workers.dev?token=abc",
            "https://holoviewer-public-api.singlebagel.workers.dev/#frag",
            "https://example.com",
        )
        for value in bad_values:
            with self.subTest(value=value):
                raw = copy.deepcopy(self.fixture)
                raw["base_url"] = value
                with self.assertRaises(ValueError):
                    build_semantic_health(raw)

    def test_probe_path_rejects_full_url_and_sensitive_query(self):
        bad_values = (
            "https://example.com/health",
            "//example.com/health",
            "/v1/catalog/today?token=abc",
            "/v1/catalog/today?access_token=abc",
            "/v1/catalog/today?api-key=abc",
        )
        for value in bad_values:
            with self.subTest(value=value):
                raw = copy.deepcopy(self.fixture)
                raw["probes"]["today"]["path"] = value
                with self.assertRaises(ValueError):
                    build_semantic_health(raw)

    def test_probe_path_allows_non_sensitive_query_parameters(self):
        raw = copy.deepcopy(self.fixture)
        raw["probes"]["today"]["path"] = "/v1/catalog/today?limit=10"
        out = build_semantic_health(raw)
        today = next(x for x in out["probes"] if x["name"] == "today")
        self.assertEqual(today["path"], "/v1/catalog/today?limit=10")


if __name__ == "__main__":
    unittest.main()
