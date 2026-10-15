import sys
import unittest

from platform_adapter.support_style_binding import extract_support_styles


class SupportStyleBindingTests(unittest.TestCase):
    def test_today_support_colors_preserve_solid_dual_and_neutral(self):
        payload = {"streams": [
            {"channel_id": "UCsolid", "support_mode": "solid", "member_accent": "#a1b2c3", "member_accent_dual": None},
            {"channel_id": "UCdual", "support_mode": "dual_color", "member_accent": "#112233", "member_accent_dual": ["#112233", "#AABBCC"]},
            {"channel_id": "UCneutral", "support_mode": "neutral", "member_accent": None, "member_accent_dual": None},
        ]}
        styles = extract_support_styles(payload)
        self.assertEqual(styles["UCsolid"], {"mode": "solid", "hexes": ("#A1B2C3",)})
        self.assertEqual(styles["UCdual"], {"mode": "dual_color", "hexes": ("#112233", "#AABBCC")})
        self.assertEqual(styles["UCneutral"], {"mode": "neutral", "hexes": ()})

    def test_missing_or_malformed_color_is_neutral_not_guessed(self):
        payload = {"streams": [
            {"channel_id": "UCbad", "support_mode": "solid", "member_accent": "red"},
        ]}
        self.assertEqual(
            extract_support_styles(payload)["UCbad"],
            {"mode": "neutral", "hexes": ()},
        )


class SupportStyleRuntimeIsolationTests(unittest.TestCase):
    def test_api_context_never_calls_runtime_fallback(self):
        from platform_adapter.support_style_binding import install_support_style_adapter, using_support_styles

        class Item:
            channel_id = "UCmissing"

        class FakeHome:
            _holoviewer_api_style_installed = False
            fallback_calls = 0

            @staticmethod
            def _channel_style(item):
                FakeHome.fallback_calls += 1
                return "runtime-fallback"

        install_support_style_adapter(FakeHome)
        with using_support_styles({}):
            self.assertEqual(FakeHome._channel_style(Item()), "")
        self.assertEqual(FakeHome.fallback_calls, 0)


class PublicAPIPreloadIsolationTests(unittest.TestCase):
    def test_preloaded_today_does_not_import_urllib_request(self):
        from platform_adapter.public_api import PublicAPI, preloaded_public_reads
        sys.modules.pop("urllib.request", None)
        payload = {"streams": []}
        with preloaded_public_reads({("/v1/catalog/today", ()): payload}):
            self.assertIs(PublicAPI().read_today(), payload)
        self.assertNotIn("urllib.request", sys.modules)


class CanonicalLifecycleTests(unittest.TestCase):
    def test_live_row_stays_live_even_when_envelope_is_stale(self):
        from platform_adapter.product_bindings import home_groups_from_payload
        from dataclasses import dataclass
        from datetime import datetime

        @dataclass
        class HomeStream:
            video_id: str
            title: str
            channel_title: str
            start_label: str
            state: str
            source_label: str = ""
            channel_id: str = ""
            avatar_url: str = ""
            group: str = "hololive"
            start_at: datetime | None = None

        payload = {
            "freshness": {"status": "stale"},
            "streams": [{
                "video_id": "abcdefghijk",
                "title": "live",
                "channel_id": "UC0000000000000000000000",
                "channel_name": "channel",
                "group": "hololive",
                "lifecycle_state": "live",
                "start_at": "2026-10-16T01:00:00Z",
            }],
        }
        live, upcoming, ended, unknown = home_groups_from_payload(payload, HomeStream)
        self.assertEqual([x.video_id for x in live], ["abcdefghijk"])
        self.assertEqual(upcoming, [])
        self.assertEqual(ended, [])
        self.assertEqual(unknown, [])


class LightweightHomeImportTests(unittest.TestCase):
    def test_home_lightweight_module_does_not_import_client_app(self):
        sys.modules.pop("client_app", None)
        sys.modules.pop("platform_adapter.home_lightweight", None)
        __import__("platform_adapter.home_lightweight")
        self.assertNotIn("client_app", sys.modules)


if __name__ == "__main__":
    unittest.main()
