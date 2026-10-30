"""Offline integrity checks for the approved static Watchalong events."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "site/data/watchalong"
OLD_MASTERS = ("eFYByyw5AJc", "U2o13h1Oib4", "8pF4qHcshDc", "t8q3XEmK0aM")
NEW_MASTERS = ("jqJb0qnueDo", "x7bMoyNWaEE")
MASTERS = OLD_MASTERS + NEW_MASTERS
OLD_EVENT_HASHES = {
    "eFYByyw5AJc": "3d591074387770afcff50265220ff89fd25f0467582c686867eff71d071cee43",
    "U2o13h1Oib4": "874f6a3a722a2af5cd21ba6d1dc4a13147de35470445122291e5dc134c091ba4",
    "8pF4qHcshDc": "f92fc25f2935fbd2cc1291431bea2f84c3e557c046d05492322efdb10efa9d83",
    "t8q3XEmK0aM": "895f9150c2c292da3f1c1269b3dc6a6d417bd165c10f1d2c107f0d6e0e38c230",
}


class WatchalongAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    def test_manifest_exports_exactly_six_intended_sessions(self):
        self.assertEqual(self.manifest["schema_version"], "holoviewer-watchalong-manifest-v1")
        self.assertEqual(self.manifest["event_count"], 6)
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

    def test_old_four_events_are_byte_for_byte_preserved(self):
        for master, expected_hash in OLD_EVENT_HASHES.items():
            raw = (DATA / "events" / f"{master}.json").read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected_hash)

    def test_new_quality_v2_identities_are_exact(self):
        expected = {
            "jqJb0qnueDo": {
                "transcript_id": "800774361d14746957549eb2d885fe1eee6f40b15e467307b6f0aea852be25dd",
                "content_hash": "d4321ddc1bcac20aa8c6bc04759c8ca461ffc0ac05dbee26ea88496365e0dae6",
                "artifact_id": "141898ea22cd37595160c64d3899f8202916e1126f066c5193b8dd0681e7b6c5",
                "cue_count": 449,
            },
            "x7bMoyNWaEE": {
                "transcript_id": "8bef48719c6fdeb9fda78bed0a56f58a6dc4fd7d144c40f1fea010d758488e17",
                "content_hash": "450573590110d9563829c85cc04fa0b488c71c5ee2969c48982f293fbad1c2dd",
                "artifact_id": "9868c1c078edecd96e487fd914fb8e7842de38838dc2000ebee8e16f13741360",
                "cue_count": 888,
            },
        }
        for master, identity in expected.items():
            event = json.loads((DATA / "events" / f"{master}.json").read_text(encoding="utf-8"))
            transcript = event["artifacts"]["transcript"]
            translation = event["artifacts"]["translation"]
            self.assertEqual(event["event_id"], master)
            self.assertEqual(event["master_video_id"], master)
            self.assertEqual(transcript["transcript_id"], identity["transcript_id"])
            self.assertEqual(transcript["content_hash"], identity["content_hash"])
            self.assertEqual(transcript["cue_count"], identity["cue_count"])
            self.assertEqual(translation["artifact_id"], identity["artifact_id"])
            self.assertEqual(translation["transcript_hash"], identity["content_hash"])
            self.assertEqual(translation["translated_cues"], identity["cue_count"])
            self.assertEqual(len(event["subtitles"]), identity["cue_count"])

        wrong_local_consumers_identity = "0badbda"
        jq = (DATA / "events/jqJb0qnueDo.json").read_text(encoding="utf-8")
        self.assertNotIn(wrong_local_consumers_identity, jq)
        self.assertNotEqual(len(json.loads(jq)["subtitles"]), 437)

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
        self.assertEqual(event["artifacts"]["transcript"]["transcript_id"], "5b5424cd70f9cc99561e768222fe501b746d7f0572765eba5b958f02583d298d")
        self.assertEqual(event["artifacts"]["transcript"]["content_hash"], "f67ce6dd021ed9bddd9af2fcadddddab029dbafdb9d3763e4abeb71d8aded456")
        self.assertEqual(event["artifacts"]["transcript"]["cue_count"], 1568)
        self.assertEqual(event["artifacts"]["translation"]["artifact_id"], "db98d96002931734b6336c01732b6d981fbee3ed71a5304352c37f7ec4a92168")
        self.assertEqual(event["artifacts"]["translation"]["quality"], "quality-v2-complete")

    def test_october_22_owner_completed_artifact_identity_is_exact(self):
        event = json.loads((DATA / "events/t8q3XEmK0aM.json").read_text(encoding="utf-8"))
        self.assertEqual(event["session_day"], "2026-10-22")
        self.assertEqual(event["playlist_start_index"], 19)
        self.assertEqual(event["source_video_ids"], [
            "O4V1jClR7PY", "ybW0na9NNms", "aFmPLs4JkbQ",
            "sD2ql0Nfptg", "v_9mDEhKv1g", "1PRbROChRAw",
        ])
        self.assertEqual(
            [row["host_start_ms"] for row in event["segments"]],
            [727000, 2195000, 3683000, 5170000, 6691000, 8233000],
        )
        self.assertNotIn(8610000, [row["host_start_ms"] for row in event["segments"]])
        self.assertEqual(event["artifacts"]["transcript"], {
            "transcript_id": "178aae1474d868fb3800c451eb75ce29de0b26dd8d7f32bf66a62c99f59b108a",
            "content_hash": "c71004b6d0d4b888b841f97862d5e0856035c7c09fe039ac4c0844109c72f06d",
            "cue_count": 1367,
            "source": "TranscriptCorpus/youtube/t8q3XEmK0aM/178aae1474d868fb3800c451eb75ce29de0b26dd8d7f32bf66a62c99f59b108a",
        })
        self.assertEqual(
            event["artifacts"]["translation"]["artifact_id"],
            "a9376309a49b753a1d57326b818d9ec13e12ab3caaf57aaf3d63b4005676b2c6",
        )
        self.assertEqual(event["artifacts"]["translation"]["translated_cues"], 1367)
        self.assertEqual(event["completeness"], {
            "sync": "PRESENT", "transcript": "COMPLETE", "translation": "COMPLETE",
        })


    def test_inter_segment_gap_helper_latches_until_next_host_start(self):
        script = r"""
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync('site/assets/watchalong-static-core.js','utf8');
vm.runInThisContext(source);
const core=globalThis.HoloViewerWatchalongStatic;
const segments=[
 {host_start_ms:1000},
 {host_start_ms:5000},
 {host_start_ms:9000},
];
assert.equal(core.interSegmentGapUntil(segments,0,3.0,true),5);
assert.equal(core.interSegmentGapUntil(segments,0,4.999,true),5);
assert.equal(core.interSegmentGapUntil(segments,0,5.0,true),null);
assert.equal(core.interSegmentGapUntil(segments,0,3.0,false),null);
assert.equal(core.interSegmentGapUntil(segments,2,10.0,true),null);
"""
        result = subprocess.run(
            ["node", "-e", textwrap.dedent(script)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            self.fail(result.stdout + result.stderr)

    def test_watchalong_runtime_holds_source_during_inter_segment_gap(self):
        source = (ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let sourceGapUntilHostSeconds=null;", source)
        self.assertIn("function maybeLatchSourceGap(hostSeconds,sourceState)", source)
        self.assertIn("sourceState===YT.PlayerState.ENDED", source)
        self.assertIn("setSourceStandby(true,{rewind:false});", source)
        self.assertIn("if(sourceGapActive(host)){setSourceStandby(true,{rewind:false});return}", source)
        self.assertIn("if(maybeLatchSourceGap(host,sourceState))return;", source)
        self.assertIn("function clearSourceGap()", source)
        self.assertIn("clearSourceGap();\n setSourceStandby(false);\n activeSegmentIndex=index;", source)

        sync_start = source.index("function startSyncLoop(){")
        sync_end = source.index("function subtitleCueAt", sync_start)
        sync_body = source[sync_start:sync_end]
        gap_guard = sync_body.index("if(sourceGapActive(host)){setSourceStandby(true,{rewind:false});return}")
        source_play = sync_body.index("sourcePlayer.playVideo()", gap_guard)
        self.assertLess(gap_guard, source_play)

        standby_start = source.index("function setSourceStandby(active){")
        standby_end = source.index("function onHostStateChange", standby_start)
        standby_body = source[standby_start:standby_end]
        self.assertIn("if(rewind){", standby_body)
        self.assertIn("sourcePlayer.seekTo(0,true)", standby_body)

    def test_source_ended_event_latches_gap_without_waiting_for_poll(self):
        source = (ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        self.assertIn("function onSourceStateChange(event)", source)
        self.assertIn("if(event?.data!==YT.PlayerState.ENDED)return;", source)
        self.assertIn("maybeLatchSourceGap(host,YT.PlayerState.ENDED);", source)
        self.assertIn("onStateChange:onSourceStateChange", source)

        handler_start = source.index("function onSourceStateChange(event)")
        handler_end = source.index("function youtubePlayerErrorLabel", handler_start)
        handler = source[handler_start:handler_end]
        self.assertNotIn("setInterval", handler)
        self.assertNotIn("playVideo()", handler)
        self.assertNotIn("seekTo(", handler)

    def test_subtitle_and_danmaku_layers_are_independent(self):
        html = (ROOT / "site/watchalong-viewer/index.html").read_text(encoding="utf-8")
        source = (ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/watchalong-standalone.css").read_text(encoding="utf-8")

        self.assertIn('id="subtitleOverlay"', html)
        self.assertIn('id="sourceSubtitleOverlay"', html)
        self.assertIn('id="danmakuLayer"', html)
        self.assertIn("const sourceSubtitleOverlay=document.getElementById('sourceSubtitleOverlay');", source)
        self.assertIn("const sourceSubtitleTranslation=document.getElementById('sourceSubtitleTranslation');", source)
        self.assertIn("sourceSubtitleOverlay.hidden=danmakuEnabled||!text;", source)
        self.assertIn("if(!subtitleEnabled||danmakuEnabled)sourceSubtitleOverlay.hidden=true;", source)
        self.assertIn("subtitleOverlay.hidden=!text;", source)
        self.assertIn("if(danmakuEnabled){", source)
        self.assertIn(".source-subtitle-overlay{", css)
        self.assertIn(".source-subtitle-overlay[hidden]{display:none}", css)

    def test_integrated_release_uses_existing_static_watchalong_assets(self):
        player = ROOT / "site/assets/watchalong-standalone.js"
        viewer = ROOT / "site/watchalong-viewer/index.html"
        self.assertTrue(player.exists())
        self.assertTrue(viewer.exists())
        source = player.read_text(encoding="utf-8")
        self.assertIn("const WATCHALONG_MANIFEST_PATH='/data/watchalong/manifest.json';", source)
        self.assertIn("STATIC_EVENT_MODE", source)

    def test_owner_local_deploy_packet_targets_both_new_events(self):
        source = (ROOT / "scripts/deploy_watchalong_event_owner_local.sh").read_text(encoding="utf-8")
        self.assertIn('VIDEO_ONE_ID="jqJb0qnueDo"', source)
        self.assertIn('VIDEO_TWO_ID="x7bMoyNWaEE"', source)
        self.assertIn('.event_count == 6', source)
        self.assertIn('(.subtitles | length) == 449', source)
        self.assertIn('(.subtitles | length) == 888', source)
        self.assertIn('npx --yes wrangler deploy --config cloudflare/wrangler.json --name holoviewer-public', source)

    def test_exporter_has_no_network_or_provider_write_path(self):
        source = (ROOT / "scripts/export_watchalong_assets.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "urllib", "google.genai", "GeminiTranslationProvider", "INSERT ", "UPDATE ", "DELETE "):
            self.assertNotIn(forbidden, source)
        self.assertIn("mode=ro&immutable=1", source)


if __name__ == "__main__":
    unittest.main()
