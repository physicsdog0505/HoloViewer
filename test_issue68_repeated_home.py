from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "4174-a144bb3"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from platform_adapter.public_api import preloaded_public_reads
from platform_adapter.home_lightweight import dispatch_lightweight_home


def today_payload(count: int = 40) -> dict:
    rows = []
    for index in range(count):
        rows.append({
            "video_id": f"A{index:010d}"[-11:],
            "title": f"stream {index}",
            "channel_id": f"UC{index:022d}"[-24:],
            "channel_name": f"channel {index}",
            "group": "hololive",
            "lifecycle_state": "upcoming",
            "start_at": "2026-10-16T01:00:00Z",
            "avatar_url": "",
            "source_label": "",
            "member_accent": "#112233",
            "member_accent_dual": None,
            "support_mode": "solid",
            "support_color_source": "verified",
        })
    return {
        "freshness": {"status": "fresh"},
        "streams": rows,
    }


class RepeatedHomeRenderTests(unittest.TestCase):
    def test_repeated_root_render_uses_preloaded_today_without_client_app(self):
        sys.modules.pop("client_app", None)
        key = ("/v1/catalog/today", ())
        payload = today_payload(80)
        with preloaded_public_reads({key: payload}):
            for _ in range(8):
                result = dispatch_lightweight_home("/")
                self.assertEqual(result.status, 200)
                self.assertIn(b"Today", result.body)
        self.assertNotIn("client_app", sys.modules)

    def test_repeated_api_home_render_uses_preloaded_today_without_client_app(self):
        sys.modules.pop("client_app", None)
        key = ("/v1/catalog/today", ())
        payload = today_payload(80)
        with preloaded_public_reads({key: payload}):
            for _ in range(8):
                result = dispatch_lightweight_home("/api/home")
                self.assertEqual(result.status, 200)
                self.assertIn(b'"html"', result.body)
        self.assertNotIn("client_app", sys.modules)


if __name__ == "__main__":
    unittest.main()
