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

    def test_external_clip_links_are_isolated(self):
        self.assertIn("link.target='_blank';", self.js)
        self.assertIn("link.rel='noopener noreferrer';", self.js)

    def test_story_matching_uses_sidecar_story_index(self):
        self.assertIn("card.dataset.storyIndex=String(index);", self.js)
        self.assertIn("row?.story_index", self.js)
        self.assertIn('.daily-story-card[data-story-index="', self.js)

    def test_related_clip_styles_exist(self):
        self.assertIn(".daily-related-clips{", self.css)
        self.assertIn(".daily-related-clips-grid{", self.css)
        self.assertIn(".daily-related-clip{", self.css)


if __name__ == "__main__":
    unittest.main()
