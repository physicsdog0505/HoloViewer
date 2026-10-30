from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent


class VodSubtitleAssetsTests(unittest.TestCase):
    def test_independent_static_target_and_namespace(self):
        config = json.loads(
            (ROOT / "cloudflare/vod-subtitle-static-assets.wrangler.json").read_text()
        )
        self.assertEqual(config["name"], "holoviewer-vod-subtitles-static-assets")
        self.assertEqual(config["assets"], {"directory": "../vod-subtitles-static"})
        self.assertNotIn("routes", config)
        self.assertNotEqual(config["name"], "holoviewer-watchalong-static-assets")
        root = ROOT / "vod-subtitles-static"
        self.assertTrue((root / "data/subtitles/manifests").is_dir())
        self.assertTrue((root / "data/subtitles/videos").is_dir())
        self.assertFalse((root / "data/watchalong").exists())

    def test_viewer_reader_load_order_lookup_and_missing_fallback(self):
        html = (ROOT / "site/viewer/index.html").read_text()
        js = (ROOT / "site/assets/viewer-standalone.js").read_text()
        config = (ROOT / "site/assets/config.js").read_text()
        self.assertLess(
            html.index('/assets/vod-subtitle-core.js'),
            html.index('/assets/viewer-standalone.js'),
        )
        self.assertIn("vodSubtitleStaticBase", config)
        self.assertIn("function loadViewerVodSubtitle(videoId)", js)
        self.assertIn("void loadViewerVodSubtitle(id);", js)
        self.assertIn("viewerLocalSubtitleMode==='holodocchi'?viewerVodSubtitle", js)
        self.assertIn("catch{", js)
        self.assertIn("return null;", js)

    def test_javascript_contract(self):
        result = subprocess.run(
            ["node", "test_vod_subtitle_core.js"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("VOD_SUBTITLE_CORE=PASS", result.stdout)

    def test_watchalong_authority_files_are_not_referenced_by_export_target(self):
        docs = (ROOT / "docs/VOD_SUBTITLE_STATIC_ASSETS.md").read_text()
        deploy = (ROOT / "scripts/deploy_vod_subtitle_static_assets_owner_local.sh").read_text()
        self.assertIn("This is not Watchalong", docs)
        self.assertNotIn("deploy_watchalong", deploy)
        self.assertNotIn("holoviewer-watchalong-static-assets", deploy)


if __name__ == "__main__":
    unittest.main()
