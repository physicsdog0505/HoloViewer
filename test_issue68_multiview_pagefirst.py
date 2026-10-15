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


class MultiviewPageFirstTests(unittest.TestCase):
    def _assert_session(self, target: str):
        import client_home

        def explode(*args, **kwargs):
            raise AssertionError("local Home runtime must not be used")

        with patch.object(client_home, "load_home_streams", side_effect=explode):
            result = render_page_fallback(target)

        self.assertIsNotNone(result)
        status, html = result
        self.assertEqual(status, 200)
        for video_id in ("dQw4w9WgXcQ", "abcdefghijk", "29K6Lixabcd"):
            self.assertIn(video_id, html)

    def test_custom_view_session_is_page_first_and_preserves_streams(self):
        self._assert_session(
            "/custom-view/session?stream=dQw4w9WgXcQ&stream=abcdefghijk&stream=29K6Lixabcd"
        )

    def test_collab_session_is_page_first_and_preserves_streams(self):
        self._assert_session(
            "/collab/session?collab=shared-topic&stream=dQw4w9WgXcQ&stream=abcdefghijk&stream=29K6Lixabcd"
        )


if __name__ == "__main__":
    unittest.main()
