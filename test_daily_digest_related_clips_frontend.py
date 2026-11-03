from pathlib import Path
import unittest


ROOT = Path(__file__).parent
JS = ROOT / "site" / "assets" / "daily-digest.js"
CSS = ROOT / "site" / "assets" / "daily-digest.css"
CONFIG = ROOT / "site" / "assets" / "config.js"


class DailyDigestRelatedClipsFrontendTests(unittest.TestCase):
    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        self.config = CONFIG.read_text(encoding="utf-8")

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

    def test_related_clip_styles_exist(self):
        self.assertIn(".daily-related-clips{", self.css)
        self.assertIn("repeat(auto-fit,minmax(min(280px,100%),1fr))", self.css)
        self.assertIn(".daily-related-clip{", self.css)
        self.assertIn("-webkit-line-clamp:3", self.css)
        self.assertIn("flex-wrap:nowrap", self.css)


if __name__ == "__main__":
    unittest.main()
