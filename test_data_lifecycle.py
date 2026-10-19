import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_lifecycle.checkpoint import acknowledge, fail, new_checkpoint, reserve
from data_lifecycle.cli import main
from data_lifecycle.inventory import build_inventory
from data_lifecycle.planner import build_sync_plan


class LifecycleTests(unittest.TestCase):
    def test_repeat_sync_is_noop(self):
        row = {"video_id": "abcdefghijk", "revision": 1, "content": {"x": 1}}
        self.assertEqual(build_sync_plan("youtube", [row], [row])["actions"][0]["action"], "NOOP")

    def test_older_source_cannot_overwrite_target(self):
        source = {"video_id": "abcdefghijk", "revision": 1, "content": "old"}
        target = {"video_id": "abcdefghijk", "revision": 2, "content": "new"}
        self.assertEqual(build_sync_plan("youtube", [source], [target])["actions"][0]["action"], "CONFLICT")

    def test_checkpoint_resumes_after_partial_failure(self):
        cp = new_checkpoint("job", ["a", "b"], traffic_budget=5)
        cp = acknowledge(reserve(cp, "a"), "a")
        cp = fail(cp, "b", "temporary", now="2026-10-20T00:00:00Z")
        self.assertEqual(cp["completed"], ["a"])
        self.assertEqual(cp["pending"], ["b"])
        self.assertEqual(cp["state"], "retry_pending")

    def test_youtube_cross_midnight_belongs_to_start_day(self):
        snapshot = {"youtube": {"available": True, "expected_ids": ["v"], "rows": [{
            "video_id": "v", "actual_start": "2026-10-19T15:30:00Z", "actual_end": "2026-10-20T18:00:00Z",
            "lifecycle_state": "ended"}]}, "ptt": {"available": False}}
        item = build_inventory("2026-10-19", snapshot)["sources"][0]
        self.assertEqual(item["actual_set"], ["v"])

    def test_delayed_youtube_metadata_is_repair_needed(self):
        snap = {"youtube": {"available": True, "expected_ids": ["v"], "rows": [{"video_id": "v",
            "actual_start": "2026-10-19T01:00:00Z", "lifecycle_state": "ended", "actual_end": None}]}, "ptt": {}}
        item = build_inventory("2026-10-19", snap)["sources"][0]
        self.assertEqual(item["metadata_delayed_ids"], ["v"])
        self.assertEqual(item["completeness_status"], "REPAIR_NEEDED")

    def test_ptt_middle_source_line_gap_is_not_complete(self):
        snap = {"youtube": {}, "ptt": {"available": True, "expected_aids": ["aid"],
            "rows": [{"day": "2026-10-19", "aid": "aid", "source_line": 1},
                     {"day": "2026-10-19", "aid": "aid", "source_line": 3}],
            "coverage": {"aid": {"complete": True, "start_line": 1, "end_line": 3}}}}
        item = build_inventory("2026-10-19", snap)["sources"][1]
        self.assertEqual(item["source_line_gaps"], {"aid": [2]})
        self.assertNotEqual(item["completeness_status"], "COMPLETE")

    def test_different_aids_never_mix(self):
        rows = [{"day": "2026-10-19", "aid": "a", "source_line": 1, "revision": 1, "content": "x"},
                {"day": "2026-10-19", "aid": "b", "source_line": 1, "revision": 1, "content": "y"}]
        actions = build_sync_plan("ptt", rows, [rows[0]])["actions"]
        self.assertEqual([a["action"] for a in actions], ["NOOP", "INSERT"])

    def test_empty_push_content_is_valid(self):
        row = {"day": "2026-10-19", "aid": "a", "source_line": 1, "revision": 1, "content": ""}
        self.assertEqual(build_sync_plan("ptt", [row], [])["actions"][0]["action"], "INSERT")

    def test_empty_target_gets_explicit_insert_plan(self):
        row = {"video_id": "abcdefghijk", "revision": 1, "content": "x"}
        self.assertEqual(build_sync_plan("youtube", [row], [])["actions"][0]["reason"], "target-missing")

    def test_unavailable_upstream_never_claims_complete(self):
        inventory = build_inventory("2026-10-19", {"youtube": {"available": False}, "ptt": {"available": False}})
        self.assertTrue(all(x["completeness_status"] == "UNKNOWN" for x in inventory["sources"]))
        self.assertEqual(build_sync_plan("youtube", [], [], upstream_available=False)["status"], "UPSTREAM_UNAVAILABLE")

    def test_budget_exhaustion_stops_before_reservation(self):
        cp = new_checkpoint("job", ["a"], traffic_budget=0)
        with self.assertRaisesRegex(RuntimeError, "TRAFFIC_BUDGET_EXCEEDED"):
            reserve(cp, "a")
        self.assertEqual(cp["traffic_used"], 0)

    def test_dry_run_cli_has_no_network_or_production_writer(self):
        snapshot = {"youtube": {"available": True, "expected_ids": [], "rows": [], "target_rows": []},
                    "ptt": {"available": True, "expected_aids": [], "rows": [], "target_rows": []}}
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "input.json").write_text(json.dumps(snapshot))
            argv = ["cli", "--date", "2026-10-19", "--snapshot", str(base / "input.json"),
                    "--json-out", str(base / "out.json"), "--markdown-out", str(base / "out.md")]
            with patch("sys.argv", argv), patch("socket.create_connection", side_effect=AssertionError("network attempted")):
                self.assertEqual(main(), 0)
            payload = json.loads((base / "out.json").read_text())
            self.assertTrue(all(plan["dry_run"] and plan["external_writes"] == 0 for plan in payload["plans"]))

    def test_equal_revision_different_content_is_conflict(self):
        a = {"video_id": "abcdefghijk", "revision": 1, "content": "a"}
        b = {"video_id": "abcdefghijk", "revision": 1, "content": "b"}
        self.assertEqual(build_sync_plan("youtube", [a], [b])["actions"][0]["action"], "CONFLICT")


if __name__ == "__main__":
    unittest.main()
