from pathlib import Path
import unittest


ROOT = Path(__file__).parent
JS = ROOT / "site" / "assets" / "daily-digest.js"
CSS = ROOT / "site" / "assets" / "daily-digest.css"
CONFIG = ROOT / "site" / "assets" / "config.js"
HOME_HTML = ROOT / "site" / "index.html"
DAILY_HTML = ROOT / "site" / "daily" / "index.html"
PTT_HTML = ROOT / "site" / "ptt-today" / "index.html"
VIEWER_HTML = ROOT / "site" / "viewer" / "index.html"


class DailyDigestRelatedClipsFrontendTests(unittest.TestCase):
    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        self.config = CONFIG.read_text(encoding="utf-8")
        self.home_html = HOME_HTML.read_text(encoding="utf-8")
        self.daily_html = DAILY_HTML.read_text(encoding="utf-8")
        self.ptt_html = PTT_HTML.read_text(encoding="utf-8")
        self.viewer_html = VIEWER_HTML.read_text(encoding="utf-8")

    def test_sidecar_path_contract_is_configured(self):
        self.assertIn(
            'relatedClipsPathTemplate: "/data/daily-digest/{month}/{date}-related-clips.json"',
            self.config,
        )
        self.assertIn("function relatedClipsUrl(day)", self.js)

    def test_related_clips_are_best_effort_after_digest_render(self):
        render_pos = self.js.index("const rendered=renderArtifact(content,result.artifact);")
        fetch_pos = self.js.index("void fetchRelatedClips(day).then")
        self.assertLess(render_pos, fetch_pos)
        self.assertIn("if(!response.ok)return null;", self.js)
        self.assertIn("catch{\n    return null;", self.js)

    def test_default_surface_is_top_three_and_expands_rest(self):
        self.assertIn("clips.slice(0,3)", self.js)
        self.assertIn("clips.slice(3)", self.js)
        self.assertIn("'查看全部 '+String(clips.length)+' 支'", self.js)
        self.assertIn("'精華剪輯'", self.js)
        self.assertNotIn("'相關烤肉'", self.js)

    def test_external_clip_links_are_isolated(self):
        self.assertIn("link.target='_blank';", self.js)
        self.assertIn("link.rel='noopener noreferrer';", self.js)

    def test_story_matching_uses_sidecar_story_index(self):
        self.assertIn("card.dataset.storyIndex=String(index);", self.js)
        self.assertIn("row?.story_index", self.js)
        self.assertIn('.daily-story-card[data-story-index="', self.js)

    def test_livestream_details_are_hidden_and_toggle_from_story_image(self):
        self.assertIn("shell.hidden=true;", self.js)
        self.assertIn("shell.toggleVideo=(id)=>", self.js)
        self.assertIn("if(!shell.hidden&&activeVideoId===videoId)", self.js)
        self.assertIn("shell.hidden=false;", self.js)
        self.assertIn("setGroupOpen(true);", self.js)
        self.assertIn("rail.selectVideo(videoId,{open:true});", self.js)
        self.assertIn("shell.hidden=true;", self.js)
        self.assertIn("activeVideoId='';", self.js)
        self.assertIn("return detailRail.toggleVideo(videoId);", self.js)
        self.assertIn("figure.setAttribute('aria-expanded','false');", self.js)
        self.assertIn(".daily-story-detail-shell[hidden]{", self.css)

    def test_daily_digest_header_preserves_split_branded_title(self):
        self.assertIn(".daily-digest-title-row{", self.css)
        self.assertIn("linear-gradient(110deg", self.css)
        self.assertIn("#daily-digest-date-label{", self.css)
        self.assertIn(".daily-digest-title-meta{", self.css)
        self.assertIn("justify-content:space-between;", self.css)
        self.assertIn("node.textContent=siteDateLabel(day);", self.js)
        self.assertNotIn("daily-digest-title-name", self.js)

    def test_daily_calendar_marker_is_bounded(self):
        self.assertIn(".daily-date-hub-day-mark{", self.css)
        self.assertIn("width:34px;", self.css)
        self.assertIn(".daily-date-hub-day-mark img{", self.css)
        self.assertIn("object-fit:contain;", self.css)

    def test_mobile_dock_uses_daily_digest_instead_of_multi(self):
        for html in (self.home_html, self.daily_html, self.ptt_html, self.viewer_html):
            daily_dock_links = [
                line for line in html.splitlines()
                if 'href="/daily/"' in line and 'aria-label="Docchi News 日報"' in line
            ]
            self.assertTrue(daily_dock_links)
            self.assertNotIn('data-mobile-dock-route="multi"', html)
        self.assertIn('href="/daily/" class="active" aria-current="page"', self.daily_html)

    def test_ptt_and_viewer_sidebars_include_daily_digest(self):
        daily_link = '<a href="/daily/"><span class="rail-icon">報</span><span class="rail-label">Docchi News</span></a>'
        self.assertIn(daily_link, self.ptt_html)
        self.assertIn(daily_link, self.viewer_html)
        self.assertIn('<a href="/daily/">Docchi News</a>', self.ptt_html)

    def test_related_clip_styles_exist(self):
        self.assertIn(".daily-related-clips{", self.css)
        self.assertIn("repeat(auto-fit,minmax(min(280px,100%),1fr))", self.css)
        self.assertIn(".daily-related-clip{", self.css)
        self.assertIn("-webkit-line-clamp:3", self.css)
        self.assertIn("flex-wrap:nowrap", self.css)


if __name__ == "__main__":
    unittest.main()
