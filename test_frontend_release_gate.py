from __future__ import annotations

import unittest

from scripts.frontend_release_gate import (
    ReleaseGateError,
    bounded_retry,
    validate_site_delta,
    validate_watchalong_addition,
    verify_lineage,
)


def manifest(rows):
    return {"event_count": len(rows), "events": rows}


class FrontendReleaseGateTests(unittest.TestCase):
    def test_stale_main_fails_closed(self):
        with self.assertRaises(ReleaseGateError):
            verify_lineage("head-a", "main-b", "head-a")

    def test_missing_old_entry_fails_closed(self):
        prod = manifest([
            {"event_id": "old-a", "sha256": "aaa"},
            {"event_id": "old-b", "sha256": "bbb"},
        ])
        cand = manifest([
            {"event_id": "old-a", "sha256": "aaa"},
            {"event_id": "new", "sha256": "ccc"},
        ])
        with self.assertRaises(ReleaseGateError):
            validate_watchalong_addition(prod, cand, "new")

    def test_changed_old_hash_fails_closed(self):
        prod = manifest([{"event_id": "old", "sha256": "aaa"}])
        cand = manifest([
            {"event_id": "old", "sha256": "changed"},
            {"event_id": "new", "sha256": "bbb"},
        ])
        with self.assertRaises(ReleaseGateError):
            validate_watchalong_addition(prod, cand, "new")

    def test_changed_old_manifest_identity_fails_closed(self):
        prod = manifest([{"event_id": "old", "sha256": "aaa", "title": "original"}])
        cand = manifest([
            {"event_id": "old", "sha256": "aaa", "title": "changed"},
            {"event_id": "new", "sha256": "bbb"},
        ])
        with self.assertRaises(ReleaseGateError):
            validate_watchalong_addition(prod, cand, "new")

    def test_unexpected_site_file_fails_closed(self):
        rows = [
            "M\tsite/data/watchalong/manifest.json",
            "A\tsite/data/watchalong/events/new.json",
            "M\tsite/assets/app.js",
        ]
        with self.assertRaises(ReleaseGateError):
            validate_site_delta(rows, "new")

    def test_additive_watchalong_release_passes(self):
        prod = manifest([{"event_id": "old", "sha256": "aaa"}])
        cand = manifest([
            {"event_id": "old", "sha256": "aaa"},
            {"event_id": "new", "sha256": "bbb"},
        ])
        result = validate_watchalong_addition(prod, cand, "new")
        self.assertTrue(result["old_entries_preserved"])
        self.assertFalse(result["existing_event_changed"])

    def test_transient_readback_retries_without_mutation(self):
        observations = iter([False, False, True])
        slept = []
        attempt = bounded_retry(
            lambda: next(observations),
            delays=(0, 0.01, 0.02),
            sleeper=slept.append,
        )
        self.assertEqual(attempt, 3)
        self.assertEqual(slept, [0.01, 0.02])


if __name__ == "__main__":
    unittest.main()
