from pathlib import Path
import unittest


ROOT = Path(__file__).parent


class YouTubeStaticTargetConfigTests(unittest.TestCase):
    def test_frontend_points_to_dedicated_youtube_static_target(self):
        config = (ROOT / "site/assets/config.js").read_text()
        self.assertIn(
            'youtubeStaticBase: "https://holoviewer-youtube-static-assets.singlebagel.workers.dev"',
            config,
        )

    def test_csp_allows_dedicated_youtube_static_target(self):
        headers = (ROOT / "site/_headers").read_text()
        self.assertIn(
            "https://holoviewer-youtube-static-assets.singlebagel.workers.dev",
            headers,
        )

    def test_shared_frontend_gate4_deployer_is_absent(self):
        self.assertFalse(
            (ROOT / "scripts/run_youtube_static_assets_gate4_production.sh").exists()
        )


if __name__ == "__main__":
    unittest.main()
