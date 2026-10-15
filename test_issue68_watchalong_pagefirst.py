from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "4174-a144bb3"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from platform_adapter.page_fallbacks import render_page_fallback


class WatchalongPageFirstTests(unittest.TestCase):
    def test_watchalong_landing_renders_without_local_home_runtime(self):
        import client_home

        def explode(*args, **kwargs):
            raise AssertionError("local Home runtime must not be used")

        with patch.object(client_home, "load_home_streams", side_effect=explode):
            result = render_page_fallback("/watchalong")

        self.assertIsNotNone(result)
        status, html = result
        self.assertEqual(status, 200)
        self.assertIn("同時視聽", html)
        self.assertIn('action="/watchalong/session"', html)
        self.assertIn("Hololive 主直播", html)

    def test_watchalong_session_falls_back_to_builder_and_preserves_inputs(self):
        result = render_page_fallback(
            "/watchalong/session?master=dQw4w9WgXcQ&source=abcdefghijk"
        )
        self.assertIsNotNone(result)
        status, html = result
        self.assertEqual(status, 200)
        self.assertIn("同時視聽", html)
        self.assertIn("dQw4w9WgXcQ", html)
        self.assertIn("abcdefghijk", html)


if __name__ == "__main__":
    unittest.main()
