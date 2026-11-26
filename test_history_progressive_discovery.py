import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class HistoryProgressiveDiscoveryTests(unittest.TestCase):
    def test_history_subtitle_discovery_ui_contract(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn('id="historySubtitleDiscovery"', html)
        self.assertIn('>中文字幕</button>', html)
        self.assertNotIn('id="historySubtitleFilter"', html)
        self.assertIn(".history-subtitle-discovery{", css)
        self.assertIn("linear-gradient", css)
        self.assertIn('-webkit-background-clip:text', css)
        self.assertIn('.history-subtitle-discovery[aria-pressed="true"]', css)
        self.assertIn("renderHistorySubtitleControls()", js)
        self.assertIn("HISTORY_SUBTITLE_DISCOVERY_PARAM='view'", js)
        self.assertIn("HISTORY_SUBTITLE_DISCOVERY_VALUE='subtitles'", js)

    def test_history_search_progressively_expands_months(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn("const HISTORY_DISCOVERY_BATCH_SIZE=30;", js)
        self.assertIn("async function loadYoutubeHistoryDiscovery", js)
        self.assertIn("historyPublishedMonths(manifest).slice().sort().reverse()", js)
        self.assertIn("if(collected.length>=target)break", js)
        self.assertIn("historyDiscoveryTarget+=HISTORY_DISCOVERY_BATCH_SIZE", js)
        self.assertIn("historySearchSourceHasMore=Boolean(discoverySource&&data.has_more===true)", js)
        self.assertIn("new IntersectionObserver", js)
        self.assertIn("rootMargin:'600px 0px'", js)

    def test_subtitle_discovery_uses_vod_month_index_before_history_month(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn("/data/subtitles/manifests/by-vod-month/", js)
        self.assertIn("async function loadVodSubtitleMonthIds(month)", js)
        self.assertIn("monthIds=await loadVodSubtitleMonthIds(month)", js)
        self.assertIn("if(!monthIds.size){scanned+=1;continue}", js)
        self.assertIn("rows=rows.filter(row=>monthIds.has(String(row?.video_id||'')))", js)

    def test_subtitle_filter_is_contextual_to_search_intent(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        start = js.index("function renderHistorySearchIntent")
        end = js.index("\nfunction historyChrome", start)
        block = js[start:end]
        self.assertIn("history-subtitle-filter", block)
        self.assertIn("historySubtitleConstraintEnabled()", block)
        self.assertIn("historySubtitleFilterEnabled=!historySubtitleFilterEnabled", block)
        self.assertIn("box.append(subtitle)", block)


    def test_subtitle_discovery_renders_channel_facets(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn("if(searchQuery||historySubtitleDiscoveryEnabled)", js)
        self.assertIn("if(query||historySubtitleDiscoveryEnabled)", js)
        self.assertIn("if(historySubtitleDiscoveryEnabled){\n       renderHistoryChannelFacets(historyChannelFacetRows);", js)
        self.assertIn("if(historySubtitleDiscoveryEnabled){\n    renderHistoryChannelFacets(historyChannelFacetRows);", js)

    def test_progressive_discovery_keeps_existing_cards_and_shows_spinner(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn('id="history-loading"', html)
        self.assertIn(".history-loading-spinner", css)
        self.assertIn("const historyRenderedVideoIds=new Set();", js)
        self.assertIn("function setHistoryLoading(active)", js)
        self.assertIn("loadHistory({append:true})", js)
        self.assertIn("renderHistoryFacetCards({append:true})", js)
        self.assertIn("if(!append){list.replaceChildren();historyVodWindows.clear();historyRenderedVideoIds.clear()}", js)
        self.assertIn("if(append&&historyRenderedVideoIds.has(id))continue;", js)
        self.assertIn("await onProgress", js)
        self.assertIn("historySearchRenderLimit=historyDiscoveryTarget", js)

if __name__ == "__main__":
    unittest.main()
