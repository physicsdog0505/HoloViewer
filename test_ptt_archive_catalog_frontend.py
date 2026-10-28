from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent


class PttArchiveCatalogFrontendTests(unittest.TestCase):
    def test_config_exposes_stable_monthly_catalog_without_removing_legacy(self):
        config=(ROOT/"site/assets/config.js").read_text(encoding="utf-8")
        self.assertIn('pttArchiveCatalogBase: "https://holoviewer-ptt-static-assets.singlebagel.workers.dev"',config)
        self.assertIn('pttArchiveMonths: Object.freeze({',config)
        self.assertIn('static-assets-full-2026-10.json',config)

    def test_shared_reader_supports_composite_legacy_and_daily_sources(self):
        core=(ROOT/"site/assets/ptt-archive-catalog-core.js").read_text(encoding="utf-8")
        for token in (
            "holoviewer-ptt-monthly-catalog-v1",
            "holoviewer-ptt-daily-static-package-v1",
            "ptt-r2-archive-v1",
            "holoviewer-ptt-history-day-v1",
            "holoviewer-ptt-history-day-v2",
            "duplicate source_record_key",
            "SHA 不符",
            "push count 不符",
            "partition range",
            "coverageStatus:'MISSING'",
        ):
            self.assertIn(token,core)

    def test_viewer_and_watchalong_load_reader_before_page_runtime(self):
        cases=(
            ("site/viewer/index.html","/assets/viewer-standalone.js"),
            ("site/watchalong-viewer/index.html","/assets/watchalong-standalone.js"),
        )
        for html_path,runtime in cases:
            html=(ROOT/html_path).read_text(encoding="utf-8")
            shared='/assets/ptt-archive-catalog-core.js'
            self.assertIn(shared,html)
            self.assertLess(html.index(shared),html.index(runtime))

    def test_both_vod_readers_prefer_shared_catalog_and_keep_d1_fallback(self):
        for path in ("site/assets/viewer-standalone.js","site/assets/watchalong-standalone.js"):
            js=(ROOT/path).read_text(encoding="utf-8")
            self.assertIn("window.HoloViewerPttArchive?.resolveDaySlice",js)
            self.assertIn("pttArchiveCatalogBase",js)
            self.assertIn("/v1/ptt/history?day=",js)
            self.assertIn("coverageStatus!=='COMPLETE'",js)

    def test_csp_allows_dedicated_ptt_archive_origin(self):
        headers=(ROOT/"site/_headers").read_text(encoding="utf-8")
        self.assertIn("connect-src",headers)
        self.assertIn("https://holoviewer-ptt-static-assets.singlebagel.workers.dev",headers)


if __name__=="__main__":
    unittest.main()
