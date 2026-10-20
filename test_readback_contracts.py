import copy
import json
import unittest
from pathlib import Path

from data_lifecycle.readback_contracts import (
    canonical_sha256,
    validate_api_semantic_health,
    validate_d1_snapshot,
)

ROOT = Path(__file__).parent / "fixtures" / "data-lifecycle"


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


class ReadbackContractTests(unittest.TestCase):
    def test_d1_fixture_is_sanitized_bounded_and_digest_bound(self):
        value = validate_d1_snapshot(load("d1-job-readback.sanitized.json"))
        self.assertEqual(value["verification"]["mode"], "bounded_sample")
        self.assertFalse(value["verification"]["job_verified"])
        self.assertEqual(value["query_budget"]["max_queries"], 3)
        self.assertGreaterEqual(value["query_budget"]["cache_ttl_seconds"], 60)

    def test_snapshot_id_binds_the_complete_sanitized_observation(self):
        value = load("d1-job-readback.sanitized.json")
        changed = copy.deepcopy(value)
        changed["query_budget"]["rows_returned"] = 2
        material = copy.deepcopy(changed)
        material.pop("snapshot_id")
        self.assertNotEqual(changed["snapshot_id"], canonical_sha256(material))
        with self.assertRaisesRegex(ValueError, "snapshot_id digest mismatch"):
            validate_d1_snapshot(changed)

    def test_bounded_sample_can_never_claim_job_verified(self):
        value = load("d1-job-readback.sanitized.json")
        value["verification"]["job_verified"] = True
        material = copy.deepcopy(value)
        material.pop("snapshot_id")
        value["snapshot_id"] = canonical_sha256(material)
        with self.assertRaisesRegex(ValueError, "bounded sample"):
            validate_d1_snapshot(value)

    def test_dashboard_query_budget_is_hard_bounded(self):
        value = load("d1-job-readback.sanitized.json")
        value["query_budget"]["max_rows_returned"] = 501
        material = copy.deepcopy(value)
        material.pop("snapshot_id")
        value["snapshot_id"] = canonical_sha256(material)
        with self.assertRaisesRegex(ValueError, "max_rows_returned"):
            validate_d1_snapshot(value)

    def test_d1_fixture_contains_no_raw_content_or_credentials(self):
        raw = (ROOT / "d1-job-readback.sanitized.json").read_text(encoding="utf-8").lower()
        for forbidden in ("password", "authorization", "cookie", "api_key", "raw_error"):
            self.assertNotIn(forbidden, raw)

    def test_api_semantic_fixture_distinguishes_200_from_health(self):
        value = validate_api_semantic_health(load("api-semantic-health.sanitized.json"))
        health = next(x for x in value["probes"] if x["name"] == "health")
        ptt = next(x for x in value["probes"] if x["name"] == "ptt_today")
        self.assertEqual(health["http_status"], 200)
        self.assertEqual(health["semantic_status"], "unknown")
        self.assertEqual(ptt["semantic_status"], "degraded")

    def test_health_200_cannot_self_certify_semantic_health(self):
        value = load("api-semantic-health.sanitized.json")
        health = next(x for x in value["probes"] if x["name"] == "health")
        health["semantic_status"] = "healthy"
        with self.assertRaisesRegex(ValueError, "cannot self-certify"):
            validate_api_semantic_health(value)


if __name__ == "__main__":
    unittest.main()
