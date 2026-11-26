from __future__ import annotations

import json
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
MODULE = ROOT / "site/assets/digest-collab.js"


class DigestCollabFrontendTests(unittest.TestCase):
    def run_case(self, digest, metadata):
        script = r"""
const mod=require(process.argv[1]);
const digest=JSON.parse(process.argv[2]);
const metadata=JSON.parse(process.argv[3]);
process.stdout.write(JSON.stringify(mod.deriveDigestCollabEvents(digest,metadata)));
"""
        result = subprocess.run(
            ["node", "-e", script, str(MODULE), json.dumps(digest), json.dumps(metadata)],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def base_digest(self, video_ids):
        return {
            "schema_version": 1,
            "kind": "holodocchi.daily_digest",
            "timezone": "Asia/Taipei",
            "target_day": "2026-11-25",
            "stories": [{"title": "多人連動測試", "video_ids": video_ids}],
            "overview": {"highlights": []},
        }

    def test_two_videos_two_channels_overlap_yields_event(self):
        digest = self.base_digest(["AAAAAAAAAAA", "BBBBBBBBBBB"])
        metadata = [
            {"video_id": "AAAAAAAAAAA", "channel_id": "channel-a", "channel_name": "A", "lifecycle_state": "ended",
             "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T12:00:00Z"},
            {"video_id": "BBBBBBBBBBB", "channel_id": "channel-b", "channel_name": "B", "lifecycle_state": "ended",
             "actual_start": "2026-11-25T10:10:00Z", "actual_end": "2026-11-25T11:40:00Z"},
        ]
        events = self.run_case(digest, metadata)
        self.assertEqual(len(events), 1)
        self.assertEqual({row["channel_id"] for row in events[0]["streams"]}, {"channel-a", "channel-b"})

    def test_same_channel_multi_video_is_skipped(self):
        digest = self.base_digest(["AAAAAAAAAAA", "BBBBBBBBBBB"])
        metadata = [
            {"video_id": "AAAAAAAAAAA", "channel_id": "same", "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T12:00:00Z"},
            {"video_id": "BBBBBBBBBBB", "channel_id": "same", "actual_start": "2026-11-25T10:05:00Z", "actual_end": "2026-11-25T11:00:00Z"},
        ]
        self.assertEqual(self.run_case(digest, metadata), [])

    def test_non_overlapping_complete_windows_are_skipped(self):
        digest = self.base_digest(["AAAAAAAAAAA", "BBBBBBBBBBB"])
        metadata = [
            {"video_id": "AAAAAAAAAAA", "channel_id": "channel-a", "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T11:00:00Z"},
            {"video_id": "BBBBBBBBBBB", "channel_id": "channel-b", "actual_start": "2026-11-25T12:00:00Z", "actual_end": "2026-11-25T13:00:00Z"},
        ]
        self.assertEqual(self.run_case(digest, metadata), [])

    def test_invalid_video_id_is_skipped(self):
        digest = self.base_digest(["bad", "BBBBBBBBBBB"])
        metadata = [
            {"video_id": "bad", "channel_id": "channel-a", "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T11:00:00Z"},
            {"video_id": "BBBBBBBBBBB", "channel_id": "channel-b", "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T11:00:00Z"},
        ]
        self.assertEqual(self.run_case(digest, metadata), [])

    def test_event_id_is_deterministic_across_input_order(self):
        first = self.base_digest(["AAAAAAAAAAA", "BBBBBBBBBBB"])
        second = self.base_digest(["BBBBBBBBBBB", "AAAAAAAAAAA"])
        metadata = [
            {"video_id": "AAAAAAAAAAA", "channel_id": "channel-a", "actual_start": "2026-11-25T10:00:00Z", "actual_end": "2026-11-25T11:00:00Z"},
            {"video_id": "BBBBBBBBBBB", "channel_id": "channel-b", "actual_start": "2026-11-25T10:05:00Z", "actual_end": "2026-11-25T10:55:00Z"},
        ]
        a = self.run_case(first, metadata)
        b = self.run_case(second, metadata)
        self.assertEqual(a[0]["event_id"], b[0]["event_id"])


if __name__ == "__main__":
    unittest.main()
