from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
VIEWER = (ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
CSS = (ROOT / "site/assets/viewer-standalone.css").read_text(encoding="utf-8")
HTML = (ROOT / "site/index.html").read_text(encoding="utf-8")
DATA = ROOT / "site/data/watchalong"


class WatchalongViewerAdapterTests(unittest.TestCase):
    def test_landing_reads_verified_manifest_and_opens_existing_viewer(self):
        self.assertIn("const WATCHALONG_MANIFEST_PATH='/data/watchalong/manifest.json';", APP)
        self.assertIn("manifest?.event_count!==3", APP)
        self.assertIn("q.set('watchalong',String(row.event_id));", APP)
        self.assertIn("location.href='/viewer/?'+q.toString();", APP)
        self.assertNotIn("/watchalong-viewer/", APP)
        for value in ('id="recent-watchalong"', 'id="recentWatchGrid"', 'id="recentWatchSearch"'):
            self.assertIn(value, HTML)

    def test_manifest_and_three_event_blobs_are_still_exact(self):
        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "holoviewer-watchalong-manifest-v1")
        self.assertEqual(manifest["event_count"], 3)
        self.assertEqual(len(manifest["events"]), 3)
        for entry in manifest["events"]:
            path = ROOT / "site" / entry["path"].lstrip("/")
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"])
            event = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(event["event_id"], entry["event_id"])
            self.assertEqual(event["master_video_id"], entry["master_video_id"])
            self.assertEqual(len(event["segments"]), 6)
            self.assertEqual(len(event["source_video_ids"]), 6)
            self.assertEqual(event["subtitle_timeline"], "host")
            self.assertEqual(event["artifacts"]["translation"]["coverage"], "COMPLETE")

    def test_viewer_hash_and_identity_fail_closed_without_api_fallback(self):
        for token in (
            "crypto.subtle.digest('SHA-256',buffer)",
            "Watchalong artifact SHA-256 mismatch",
            "Watchalong artifact identity mismatch",
            "Watchalong segment contract mismatch",
            "Watchalong subtitle contract mismatch",
            "return failWatchalong()",
        ):
            self.assertIn(token, VIEWER)
        start = VIEWER.index("async function initWatchalongManager(){")
        end = VIEWER.index("function supportStyle", start)
        adapter = VIEWER[start:end]
        self.assertIn("fetch(WATCHALONG_MANIFEST_PATH", adapter)
        self.assertIn("fetch(entry.path", adapter)
        self.assertNotIn("api(", adapter)
        self.assertNotIn("/v1/watchalong", adapter)

    def test_host_clock_offset_formula_and_segment_transition(self):
        self.assertIn(
            "return Number(segment.source_start_seconds)+(Number(hostSeconds)-Number(segment.host_start_seconds));",
            VIEWER,
        )
        self.assertIn("const segmentIndex=watchalongSegmentIndex(hostSeconds);", VIEWER)
        self.assertIn("const expected=Math.max(0,watchalongSourceTime(segment,hostSeconds));", VIEWER)
        self.assertIn("if(current)removeWatchalongSource();", VIEWER)
        self.assertIn("removeMultiStreamInternal(index,{allowEmpty:false})", VIEWER)
        self.assertIn("if(watchalongManaged&&index!==0)return;", VIEWER)
        # Generic equal-time multi-player synchronization must not override offset sync.
        self.assertIn("function syncPlayers(state,sourceIndex){\n if(watchalongManaged)return;", VIEWER)

    def test_subtitles_are_host_clock_and_attached_to_master_card(self):
        self.assertIn("event.subtitle_timeline!=='host'", VIEWER)
        self.assertIn("const card=playerCards[0];", VIEWER)
        self.assertIn("renderWatchalongSubtitle(hostSeconds);", VIEWER)
        self.assertIn("watchalong-subtitle-original", VIEWER)
        self.assertIn("watchalong-subtitle-translation", VIEWER)
        self.assertIn(".watchalong-subtitles{", CSS)
        self.assertIn(".watchalong-subtitles[hidden]{display:none}", CSS)

    def test_watchalong_mode_locks_master_and_does_not_reenable_generic_sync(self):
        self.assertIn("multiModeSwitch.disabled=watchalongManaged;", VIEWER)
        self.assertIn("syncPlayback.checked=false;", VIEWER)
        self.assertIn("syncPlayback.disabled=true;", VIEWER)
        self.assertIn("q.set('watchalong',watchalongEventId);", VIEWER)
        self.assertIn("watchalongTimer=setInterval(()=>{if(!document.hidden)syncWatchalong()},250);", VIEWER)

    def test_known_manual_master_uses_verified_event_unknown_stays_fail_closed(self):
        self.assertIn("manifest.events.find(item=>item?.event_id===master&&watchalongEntryValid(item))", APP)
        self.assertIn("if(row){error.hidden=true;openVerifiedWatchalong(row);return}", APP)
        self.assertIn("這組主影片沒有已驗證的同時視聽資料，因此不會啟動未驗證同步。", APP)


if __name__ == "__main__":
    unittest.main()
