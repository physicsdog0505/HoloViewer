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
        self.assertNotIn('<span class="eyebrow">HOME</span>', html)
        self.assertNotIn('<span class="eyebrow">COLLAB</span>', html)
        self.assertIn('<span class="eyebrow">WATCHALONG</span>', html)
        self.assertIn('<span class="eyebrow">CUSTOM</span>', html)
        self.assertNotIn("<h1>History</h1>", html)

    def test_history_matches_accepted_4174_date_and_paging_contract(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        for snippet in ('id="history-picker"', 'id="historyDate"', 'id="history-shortcuts"',
                        'id="history-pagination"', 'id="historyMultiSelectBar"',
                        '依直播開始日期瀏覽最近 30 天的已結束影片。'):
            self.assertIn(snippet, html)
        for snippet in ('shiftDay(today,-30)', 'shiftDay(today,-1)', 'limit=50&offset=',
                        "['昨天',b.latest]", "['前天',shiftDay(b.latest,-1)]",
                        "['7 天前',shiftDay(b.latest,-6)]", "['← 前一天',shiftDay(selected,-1)]",
                        "['後一天 →',shiftDay(selected,1)]"):
            self.assertIn(snippet, js)
        self.assertIn('.history-picker,.history-shortcuts', css)
        self.assertNotIn('id="history-prev"', html)
        self.assertNotIn('id="history-next"', html)

    def test_custom_builder_matches_accepted_4174_controls(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        for part in ('class="custom-layout"', 'class="selection-panel"', 'id="liveLibrary"',
                     'id="historyLibrary"', 'id="layout"', 'id="primary"', 'id="audio"',
                     'id="pttMode"', 'id="selectedCount"', 'id="custom-session"'):
            self.assertIn(part, html)
        for part in ('moveStream(from,to)', "className='drag-handle'",
                     "radio.name='mainVideo'", "window.hvCustomCatalog=function(rows)",
                     'window.hvOpenCustomSession=function(ids,opts={})'):
            self.assertIn(part, js)
        self.assertIn('.selected-item{display:grid', css)
        self.assertIn('.live-picker-list{display:grid', css)

    def test_route_handlers_are_not_registered_on_every_navigation(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        route_body = js.split('function route(r){', 1)[1].split('async function api(', 1)[0]
        self.assertNotIn('addEventListener', route_body)
        self.assertNotIn("multiWatch').onclick", route_body)

    def test_ptt_reader_preserves_4174_shell_without_fake_data(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for item in ('class="ptt-shell"', 'class="ptt-toolbar"', 'class="ptt-reader"',
                     'id="ptt-today-meta"', 'id="ptt-refresh"', 'id="ptt-focus"'):
            self.assertIn(item, html)
        self.assertIn('.ptt-reader{border:1px solid var(--line)', css)
        self.assertIn('ptt-focus-mode', css)
        self.assertIn('document.body.classList.toggle(\'ptt-focus-mode\'', js)
        self.assertIn('目前尚未接通經過驗證的公開 PTT 專串資料。', js)
        self.assertNotIn("message('ptt-status'", js)

    def test_history_label_agrees_with_navigation_js(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("history:'歷史直播'", js)

if __name__ == "__main__":
    unittest.main()
