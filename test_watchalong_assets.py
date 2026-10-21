"""Offline integrity checks for the three approved static Watchalong events."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "site/data/watchalong"
MASTERS = ("eFYByyw5AJc", "U2o13h1Oib4", "8pF4qHcshDc")


class WatchalongAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_exports_exactly_three_intended_sessions(self):
        self.assertEqual(self.manifest["schema_version"], "holoviewer-watchalong-manifest-v1")
        self.assertEqual(self.manifest["event_count"], 3)
        self.assertEqual(tuple(row["event_id"] for row in self.manifest["events"]), MASTERS)
        self.assertEqual({path.stem for path in (DATA / "events").glob("*.json")}, set(MASTERS))

    def test_manifest_hashes_and_complete_coverage(self):
        for entry in self.manifest["events"]:
            path = ROOT / "site" / entry["path"].lstrip("/")
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
            event = json.loads(raw)
            self.assertEqual(event["schema_version"], "holoviewer-watchalong-event-v1")
            self.assertEqual(event["event_id"], entry["event_id"])
            self.assertEqual(event["master_video_id"], entry["master_video_id"])
            self.assertEqual(event["subtitle_timeline"], "host")
            self.assertEqual(len(event["segments"]), entry["source_count"])
            self.assertEqual(len(event["subtitles"]), entry["cue_count"])
            self.assertEqual(event["artifacts"]["transcript"]["cue_count"], entry["cue_count"])
            self.assertEqual(event["artifacts"]["transcript"]["content_hash"], entry["transcript_hash"])
            self.assertEqual(event["artifacts"]["translation"]["transcript_hash"], entry["transcript_hash"])
            self.assertEqual(event["artifacts"]["translation"]["artifact_id"], entry["translation_artifact_id"])
            self.assertEqual(event["artifacts"]["translation"]["translated_cues"], entry["cue_count"])
            self.assertEqual(event["artifacts"]["translation"]["coverage"], "COMPLETE")
            cue_ids = [cue["cue_id"] for cue in event["subtitles"]]
            self.assertEqual(len(cue_ids), len(set(cue_ids)))
            self.assertEqual([cue["start_ms"] for cue in event["subtitles"]], sorted(cue["start_ms"] for cue in event["subtitles"]))
            self.assertTrue(all(cue["end_ms"] > cue["start_ms"] for cue in event["subtitles"]))
            self.assertTrue(all(cue["original"].strip() and cue["translation"].strip() for cue in event["subtitles"]))
            self.assertNotIn("/Users/", raw.decode("utf-8"))

    def test_sync_segments_preserve_order_and_zero_source_anchor(self):
        for master in MASTERS:
            event = json.loads((DATA / "events" / f"{master}.json").read_text(encoding="utf-8"))
            starts = [row["host_start_ms"] for row in event["segments"]]
            self.assertEqual(starts, sorted(starts))
            self.assertTrue(all(row["source_start_ms"] == 0 for row in event["segments"]))
            self.assertEqual([row["source_video_id"] for row in event["segments"]], event["source_video_ids"])

    def test_october_15_is_complete_not_missing(self):
        event = json.loads((DATA / "events/8pF4qHcshDc.json").read_text(encoding="utf-8"))
        self.assertEqual(event["session_day"], "2026-10-15")
        self.assertEqual(event["artifacts"]["transcript"]["content_hash"], "c7a36360c63c0fb9122bbb12a9684f90cf018682dfd0df89771e8c859ce049d0")
        self.assertEqual(event["artifacts"]["translation"]["artifact_id"], "5084c85ae7ab6ff37a9e586252f8efc365be85bf723c5fb5d6a3ddb3b01a112f")
        self.assertEqual(event["completeness"], {"sync": "PRESENT", "transcript": "COMPLETE", "translation": "COMPLETE"})

    def test_first_session_repairs_only_source_boundary(self):
        event = json.loads((DATA / "events/eFYByyw5AJc.json").read_text(encoding="utf-8"))
        self.assertEqual(len(event["segments"]), 6)
        self.assertNotIn("Vr0pc63j7jw", event["source_video_ids"])
        self.assertEqual(event["artifacts"]["sync"]["status"], "REPAIRED")
        self.assertEqual(event["artifacts"]["translation"]["artifact_id"], "62b0a69f53a7e754b424b1ce298566d0f8e733414fe1dbea9bbda9e009f4e8ca")

    def test_integrated_release_uses_existing_static_watchalong_assets(self):
        player = ROOT / "site/assets/watchalong-standalone.js"
        viewer = ROOT / "site/watchalong-viewer/index.html"
        self.assertTrue(player.exists())
        self.assertTrue(viewer.exists())
        source = player.read_text(encoding="utf-8")
        self.assertIn("const WATCHALONG_MANIFEST_PATH='/data/watchalong/manifest.json';", source)
        self.assertIn("STATIC_EVENT_MODE", source)

    def test_exporter_has_no_network_or_provider_write_path(self):
        source = (ROOT / "scripts/export_watchalong_assets.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "google.genai", "GeminiTranslationProvider", "INSERT ", "UPDATE ", "DELETE "):
            self.assertNotIn(forbidden, source)
        self.assertIn("mode=ro&immutable=1", source)


if __name__ == "__main__":
    unittest.main()
