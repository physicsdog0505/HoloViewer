"""Guard against accidental redesign while migrating accepted local 4174 UI.

Only tests the frozen shared-sidebar contract, NOT full parity.
"""
from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
EXPECTED = [
    ("home", "今", "今日直播"),
    ("history", "史", "歷史直播"),
    ("watchalong", "視", "同時視聽"),
    ("single", "自", "自訂觀看"),
    ("multi", "👥", "多人連動"),
    ("ptt", "PTT", "PTT 今日專串"),
]

class SidebarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.route = None
        self.icon = ""
        self.label = ""
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "data-route" in attrs:
            self.route = attrs["data-route"]
            self.icon = self.label = ""
        elif tag == "span" and self.route and "rail-icon" in attrs.get("class", ""):
            self.capture = "icon"
        elif tag == "span" and self.route and "rail-label" in attrs.get("class", ""):
            self.capture = "label"

    def handle_data(self, data):
        if self.route and self.capture:
            if self.capture == "icon":
                self.icon += data
            else:
                self.label += data

    def handle_endtag(self, tag):
        if tag == "span":
            self.capture = None
        if tag == "a" and self.route:
            self.items.append((self.route, self.icon.strip(), self.label.strip()))
            self.route = None

class ParityContract(unittest.TestCase):
    def test_4174_sidebar_exact_order_and_labels(self):
        parser = SidebarParser()
        parser.feed((ROOT / "site/index.html").read_text(encoding="utf-8"))
        self.assertEqual(parser.items, EXPECTED)

    def test_4174_shell_css_is_pinned(self):
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        self.assertIn("Verbatim accepted 4174 CLIENT_CSS", css)
        self.assertIn("body:has(.client-rail:hover) .client-topbar", css)
        self.assertIn(".mobile-nav[hidden]{display:none}", css)

    def test_no_unapproved_english_page_eyebrows(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertNotIn('class="eyebrow"', html)
        self.assertNotIn("<h1>History</h1>", html)

    def test_history_label_agrees_with_navigation_js(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("history:'歷史直播'", js)

if __name__ == "__main__":
    unittest.main()
