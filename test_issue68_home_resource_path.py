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


class LightweightHomeImportTests(unittest.TestCase):
    def test_home_lightweight_module_does_not_import_client_app(self):
        sys.modules.pop("client_app", None)
        sys.modules.pop("platform_adapter.home_lightweight", None)
        __import__("platform_adapter.home_lightweight")
        self.assertNotIn("client_app", sys.modules)


if __name__ == "__main__":
    unittest.main()
