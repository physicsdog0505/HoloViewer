import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_lifecycle.checkpoint import acknowledge, fail, new_checkpoint, reserve
from data_lifecycle.adapters import adapt_contract_snapshot, adapt_target_snapshot
from data_lifecycle.cli import main
from data_lifecycle.inventory import build_inventory
from data_lifecycle.planner import build_sync_plan


class LifecycleTests(unittest.TestCase):
    PAYLOAD_HASH = "a" * 64
    @staticmethod
    def authority(day):
        return {"verified": True, "day": day, "version": "contract-test-authority-v1"}

    @staticmethod
    def ack(cp, identity):
        return {"status": "ACK", "identity": identity,
                "reservation_digest": cp["in_flight"]["digest"]}

    def test_repeat_sync_is_noop(self):
        row = {"video_id": "abcdefghijk", "revision": 1, "content": {"x": 1}}
        self.assertEqual(build_sync_plan("youtube", [row], [row])["actions"][0]["action"], "NOOP")

    def test_older_source_cannot_overwrite_target(self):
        source = {"video_id": "abcdefghijk", "revision": 1, "content": "old"}
        target = {"video_id": "abcdefghijk", "revision": 2, "content": "new"}
        self.assertEqual(build_sync_plan("youtube", [source], [target])["actions"][0]["action"], "CONFLICT")

    def test_checkpoint_resumes_after_partial_failure(self):
        cp = new_checkpoint("job", ["a", "b"], traffic_budget=5)
        cp = reserve(cp, "a", payload_hash=self.PAYLOAD_HASH)
        cp = acknowledge(cp, "a", self.ack(cp, "a"))
        cp = reserve(cp, "b", payload_hash=self.PAYLOAD_HASH)
        cp = fail(cp, "b", "temporary", now="2026-10-20T00:00:00Z")
        self.assertEqual(cp["completed"], ["a"])
        self.assertEqual(cp["pending"], ["b"])
        self.assertEqual(cp["state"], "retry_pending")

    def test_youtube_cross_midnight_belongs_to_start_day(self):
        snapshot = {"youtube": {"available": True, "expected_ids": ["v"],
            "expected_authority": self.authority("2026-10-19"), "rows": [{
            "video_id": "v", "actual_start": "2026-10-19T15:30:00Z", "actual_end": "2026-10-20T18:00:00Z",
            "lifecycle_state": "ended"}]}, "ptt": {"available": False}}
        item = build_inventory("2026-10-19", snapshot)["sources"][0]
        self.assertEqual(item["actual_set"], ["v"])

    def test_delayed_youtube_metadata_is_repair_needed(self):
        snap = {"youtube": {"available": True, "expected_ids": ["v"],
            "expected_authority": self.authority("2026-10-19"), "rows": [{"video_id": "v",
            "actual_start": "2026-10-19T01:00:00Z", "lifecycle_state": "ended", "actual_end": None}]}, "ptt": {}}
        item = build_inventory("2026-10-19", snap)["sources"][0]
        self.assertEqual(item["metadata_delayed_ids"], ["v"])
        self.assertEqual(item["completeness_status"], "REPAIR_NEEDED")

    def test_ptt_middle_source_line_gap_is_not_complete(self):
        snap = {"youtube": {}, "ptt": {"available": True, "expected_aids": ["aid"],
            "expected_authority": self.authority("2026-10-19"),
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
            reserve(cp, "a", payload_hash=self.PAYLOAD_HASH)
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

    def test_empty_expected_set_without_authority_is_unknown(self):
        inventory = build_inventory("2026-10-19", {"youtube": {"available": True, "expected_ids": [], "rows": []},
            "ptt": {"available": True, "expected_aids": [], "rows": []}})
        self.assertTrue(all(item["completeness_status"] == "UNKNOWN" for item in inventory["sources"]))

    def test_wrong_day_authority_is_unknown(self):
        item = build_inventory("2026-10-19", {"youtube": {"available": True, "expected_ids": [],
            "expected_authority": self.authority("2026-10-18")}, "ptt": {}})["sources"][0]
        self.assertEqual(item["completeness_status"], "UNKNOWN")

    def test_duplicate_target_identity_is_conflict(self):
        source = {"video_id": "abcdefghijk", "revision": 1, "content": "x"}
        targets = [dict(source), dict(source)]
        action = build_sync_plan("youtube", [source], targets)["actions"][0]
        self.assertEqual((action["action"], action["reason"]), ("CONFLICT", "duplicate-target-identity"))

    def test_revision_timestamp_is_chronological_not_lexical(self):
        source = {"video_id": "abcdefghijk", "revision": 1, "observed_at": "2026-10-20T08:00:00+08:00", "content": "new"}
        target = {"video_id": "abcdefghijk", "revision": 1, "observed_at": "2026-10-20T00:30:00Z", "content": "old"}
        self.assertEqual(build_sync_plan("youtube", [source], [target])["actions"][0]["action"], "CONFLICT")

    def test_ptt_identity_and_record_key_conflicts_fail_closed(self):
        source = {"day": "2026-10-19", "aid": "a", "source_line": 1, "revision": 1,
                  "push_id": "p1", "source_record_key": "a:1", "content": "x"}
        target = {**source, "push_id": "p2"}
        action = build_sync_plan("ptt", [source], [target])["actions"][0]
        self.assertEqual((action["action"], action["reason"]), ("CONFLICT", "push_id-mismatch"))
        with self.assertRaises(ValueError):
            build_sync_plan("ptt", [{**source, "day": None}], [])

    def test_checkpoint_requires_exact_ack_and_reservation_is_idempotent(self):
        cp = reserve(new_checkpoint("job", ["a"], traffic_budget=2), "a", payload_hash=self.PAYLOAD_HASH)
        replay = reserve(cp, "a", payload_hash=self.PAYLOAD_HASH)
        self.assertEqual(replay["traffic_used"], 1)
        with self.assertRaisesRegex(ValueError, "exact reservation ACK"):
            acknowledge(cp, "a", {"status": "ACK", "identity": "a", "reservation_digest": "wrong"})
        self.assertEqual(cp["pending"], ["a"])
        with self.assertRaisesRegex(RuntimeError, "IN_FLIGHT"):
            reserve(cp, "a", payload_hash="b" * 64)

    def test_adapters_strip_target_and_preserve_contract_gaps(self):
        day = "2026-10-15"
        raw = {
            "youtube": {"available": True, "exported_at": "2026-10-20T00:00:00Z",
                "roster": {"version": "legacy-66-test", "channels": [{"id": "UC" + "A" * 22}]},
                "today": {"schema_version": "public-consumer-v1", "as_of": "2026-10-15T13:00:00Z",
                          "completeness": {"status": "partial"}, "streams": []},
                "history": {"schema_version": "public-history-import-preview-v1",
                            "source_revision": "stream-catalog-v1:youtube-liveStreamingDetails", "rows": []},
                "target": {"sanitized": True, "rows": [{"video_id": "abcdefghijk", "content": "secret",
                                                          "revision": 1, "extra": "drop"}] }},
            "ptt": {"available": True, "exported_at": "2026-10-20T00:00:00Z",
                    "day_stage": {"day": day, "rows": []}, "manifest": None,
                    "target": {"sanitized": True, "rows": []}}
        }
        adapted = adapt_contract_snapshot(day, raw)
        self.assertEqual(adapted["youtube"]["target_rows"], [{"video_id": "abcdefghijk", "revision": 1}])
        self.assertIn("#47-does-not-prove-complete-daily-video-expected-set", adapted["youtube"]["contract_gaps"])
        inventory = build_inventory(day, adapted)
        self.assertTrue(all(item["completeness_status"] == "UNKNOWN" for item in inventory["sources"]))

    def test_adapter_cannot_self_assert_authority(self):
        day = "2026-10-15"
        raw = {"youtube": {"available": True, "roster": {"version": "v1", "channels": []},
                           "expected_video_ids": [], "expected_authority": self.authority(day),
                           "target": {"sanitized": True, "rows": []}},
               "ptt": {"available": False, "day_stage": {"day": day, "rows": []},
                       "target": {"sanitized": True, "rows": []}}}
        adapted = adapt_contract_snapshot(day, raw)
        self.assertIsNone(adapted["youtube"]["expected_authority"])
        self.assertEqual(build_inventory(day, adapted)["sources"][0]["completeness_status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
