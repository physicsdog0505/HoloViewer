"""Guard against accidental redesign while migrating accepted local 4174 UI.

Only tests the frozen shared-sidebar contract, NOT full parity.
"""
from html.parser import HTMLParser
import re
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

    def test_watchalong_builder_matches_4174_source_and_mode_controls(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for part in ('id="watchalongBuilder"', 'class="manual-grid"', 'id="youtubePanel"',
                     'id="externalPanel"', 'id="singleFields"', 'id="playlistFields"',
                     'name="view_mode"', 'name="source_kind"', 'id="youtubeMode"'):
            self.assertIn(part, html)
        self.assertIn('.source-choice{display:grid', css)
        self.assertIn('.manual-shell{padding:20px}', css)
        self.assertIn("const youtubePanel=document.getElementById('youtubePanel')", js)
        self.assertIn("4174 同時視聽播放器的同步與對齊引擎尚未移植完成", js)
        self.assertNotIn("watch-add').onclick", js)

    def test_original_4174_collab_hub_structure(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        for name in ('collab-live','collab-upcoming','collab-ended'):
            self.assertIn('id="'+name+'"', html)
        self.assertNotIn('id="multi-url"', html)
        self.assertIn('function loadCollab()', js)

    def test_original_4174_home_highlights_have_verified_rules(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('id="home-highlights"',html)
        self.assertIn('id="home-announcements"',html)
        for name in ('三期生告知','重大告知','初配信','周年','新衣裝','生日','3D LIVE','大型聯動','歌回','新造型'):
            self.assertIn(name,js)
        self.assertIn('renderHomeHighlights(rows)',js)
        self.assertNotIn('setInterval(',js)

    def test_stream_id_validator_keeps_ascii_ids(self):
        js=(ROOT/"site/assets/app.js").read_text(encoding="utf-8")
        self.assertNotIn("[\\\\w-]", js, "Double escaped regex rejects real YouTube IDs")
        self.assertGreaterEqual(js.count("[A-Za-z0-9_-]{11}"), 3)

    def test_4174_channel_identity_fallback_and_safe_avatars(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('HOME_CHANNEL_ACCENTS',js)
        self.assertIn('NAKIRI AYAME',js)
        self.assertIn('TOKOYAMI TOWA',js)
        self.assertIn('ROBOCO',js)
        self.assertIn('yt3.ggpht.com',js)
        self.assertIn('homeAvatarChild(item,name)',js)
        self.assertIn("style.setProperty('--member-accent',accent)",js)

    def test_live_channel_rail_uses_original_4174_position_and_expansion(self):
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIn("Verbatim accepted 4174 LIVE_RAIL_CSS", css)
        self.assertIn("position:fixed;left:2px;top:270px;z-index:65;width:64px", css)
        self.assertIn(".live-channel-rail:hover,.live-channel-rail:focus-within{width:222px", css)
        self.assertIn("body:has(.client-rail:hover) .live-channel-rail", css)
        self.assertIn("@media(max-width:760px){.live-channel-rail{display:none}}", css)
        self.assertIn(".live-channel-rail[hidden]{display:none!important}", css)
        self.assertIn('id="live-channel-rail"', html)

    def test_4174_topbar_uses_date_not_invented_page_title(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('clientTopbarDate(',js)
        self.assertIn("updateClientTopbar(r)",js)
        self.assertIn("updateClientTopbar('history')",js)
        self.assertNotIn("$('page-title').textContent=names[r]",js)
        self.assertIn("/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/",js)

    def test_accepted_full_viewer_css_and_immersive_lifecycle(self):
        css=(ROOT/'site/assets/viewer-4174.css').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertGreater(len(css),100000)
        self.assertIn('body.custom-immersive',css)
        self.assertIn('body.custom-session-watching',css)
        self.assertNotIn('@import',css)
        self.assertNotIn('url(',css)
        self.assertIn('id="viewer-4174-css"',html)
        self.assertIn('id="customImmerse"',html)
        self.assertIn('requestFullscreen()',js)
        self.assertIn('fullscreenchange',js)
        self.assertIn("viewerActive?'all':'not all'",js)

    def test_4174_viewer_ptt_panel_is_not_a_fake_feed(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('id="customContentGrid"',html)
        self.assertIn('id="custom-session-ptt-panel"',html)
        self.assertIn('PTT 尚未對齊',html)
        self.assertIn('viewerPttPanel.remove()',js)
        self.assertIn("classList.toggle('video-only',!showPtt)",js)
        self.assertIn('目前沒有足夠的專串來源與影片時間證據。',js)

    def test_shared_shell_has_no_invented_footer_or_dead_id_bindings(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertNotIn('<footer',html)
        element_ids=set(re.findall(r'\bid="([^"]+)"',html))
        required_ids=set(re.findall(r"\$\('([^']+)'\)",js))
        self.assertEqual(required_ids-element_ids,set(),"JS required ID missing in Public HTML")

    def test_4174_watching_controls_and_no_iframe_remount_on_mode_toggle(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        for name in ('watchSingleMode','watchMultiMode','watchModeToggle','globalVolume','watchSettings','watchImmersive','focusChoices','playAll','pauseAll'):
            self.assertIn('id="'+name+'"',html)
        self.assertIn('function refreshWatchMode()',js)
        self.assertIn('function renderFocusChoices()',js)
        self.assertIn("youtubeCommand(iframe,'setVolume'",js)
        self.assertIn("youtubeCommand(iframe,'playVideo'",js)
        self.assertIn("youtubeCommand(iframe,'pauseVideo'",js)
        self.assertNotIn("renderMulti();route('multi')",js)

    def test_4174_live_rail_replaces_only_target_and_appends_in_multi(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('function selectWatchRailVideo(id,title)',js)
        self.assertIn('function makeWatchCard(id,index)',js)
        self.assertIn("watchMode==='multi'",js)
        self.assertIn("viewing.ids.push(id)",js)
        self.assertIn("box.append(makeWatchCard(id,i))",js)
        self.assertIn("link.dataset.liveVideoId=id",js)
        self.assertIn("iframe.src=youtubeEmbedUrl(id)",js)
        self.assertNotIn("route('multi')",js)

    def test_no_public_only_multiview_limit(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertNotIn('state.multi.length<12',js)
        self.assertNotIn('.slice(0,12)',js)
        self.assertIn('viewing.ids.push(id)',js)

    def test_focus_selects_single_mode_replacement_target(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('function setViewerPrimary(index,fromCarousel=false)',js)
        self.assertIn('replacementTarget=index;',js)
        self.assertIn('button.onclick=()=>setViewerPrimary(index)',js)
        self.assertIn('primary.onclick=()=>setViewerPrimary(index)',js)
        self.assertIn("el.classList.toggle('replacement-target',i===replacementTarget)",js)

    def test_linked_playback_has_explicit_toggle_and_origin_guard(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("function linkedPlayPause(event)",js)
        self.assertIn("if(!$('syncPlayback').checked",js)
        self.assertIn("ytOrigins.has(event.origin)",js)
        self.assertIn("iframe.contentWindow===event.source",js)
        self.assertIn("linkedEchoUntil.set(iframe",js)
        self.assertIn("registerViewerPlayer(player)",js)
        self.assertNotIn("setInterval(",js)

    def test_session_url_encodes_and_restores_explicit_stream_ids(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("'#custom-session?'+new URLSearchParams([",js)
        self.assertIn("...viewing.ids.map(id=>['stream',id])",js)
        self.assertIn("params.getAll('stream')",js)
        self.assertIn("const recovered=urls.length?ids:",js)
        self.assertIn("route(location.hash.substring(1).split('?')[0]||'home')",js)

    def test_custom_session_restores_on_reload_without_blank_shell(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("sessionStorage.setItem('hvCustomViewing'",js)
        self.assertIn('function restoreCustomSession()',js)
        self.assertIn("if(!recovered.length){route('single');return;}",js)
        self.assertIn('window.hvOpenCustomSession(ids,',js)

    def test_immersive_overrides_watch_shell_and_has_exit(self):
        css=(ROOT/'site/assets/viewer-4174.css').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('body.custom-session-watching.custom-immersive .client-main',css)
        self.assertIn('body.custom-session-watching.custom-immersive .client-rail',css)
        self.assertIn('id="immersiveExit"',html)
        self.assertIn("$('immersiveExit').onclick=()=>$('customImmerse').click()",js)

    def test_custom_url_entry_reports_add_and_start_failures(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertIn('id="custom-selection-status"',html)
        self.assertIn('aria-live="polite"',html)
        self.assertIn('已加入 ',js)
        self.assertIn("typeof window.hvOpenCustomSession!=='function'",js)
        self.assertIn("document.querySelectorAll('#stage .player-card iframe').length!==items.length",js)
        self.assertIn('觀看尚未開始，已保留所選影片。',js)

    def test_verified_timeline_engine_is_fail_closed_and_uses_4174_offset_formula(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('let verifiedTimelineStarts=new Map();',js)
        self.assertIn('function verifiedTimelineComplete()',js)
        self.assertIn("const timeline=opts.verifiedTimelineStarts;",js)
        self.assertIn("typeof value==='number'&&Number.isFinite(value)",js)
        self.assertIn('verifiedTimelineStarts.get(viewing.ids[masterIndex])+masterNow-verifiedTimelineStarts.get(viewing.ids[followerIndex])',js)
        self.assertIn("youtubeCommand(iframe,'seekTo',[expected,true])",js)
        self.assertIn('if(expected<0)return false;',js)
        self.assertIn('expected>=duration)return false;',js)
        self.assertIn("data?.event==='infoDelivery'",js)
        self.assertNotIn('start_at',js)

    def test_live_rail_preserves_group_and_selection_filter(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("function refreshWatchRail()",js)
        self.assertIn("homeFilter()!=='all'&&link.dataset.group!==homeFilter()",js)
        self.assertIn("watchMode==='multi'&&ids.has(link.dataset.liveVideoId)",js)
        self.assertIn("watchMode==='multi'&&viewing.ids.includes(card.dataset.liveVideoId)",js)

    def test_live_channel_rail_survives_asynchronous_home_refresh_in_viewer(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("(!$('home').classList.contains('active')&&!$('custom-session').classList.contains('active'))",js)
        self.assertIn("applyHomeFilter();refreshWatchRail();",js)
        self.assertIn("selectWatchRailVideo(id,name)",js)

    def test_youtube_embed_origin_matches_current_host(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('function youtubeEmbedUrl(id)',js)
        self.assertIn("url.searchParams.set('enablejsapi','1')",js)
        self.assertIn("url.searchParams.set('origin',window.location.origin)",js)
        self.assertIn("f.src=youtubeEmbedUrl(id)",js)
        self.assertIn("iframe.src=youtubeEmbedUrl(id)",js)

    def test_original_home_typography_not_overridden_by_public_globals(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertNotIn('button:not(.rail-nav button):not(#menu)',css)
        self.assertEqual(css.count('.page-head h1{margin:0 0 8px;font-size:34px'),1)
        self.assertIn('body.home-wide .page-head h1{font-size:30px;margin-bottom:0}',css)
        self.assertIn('.entry > button,.actions > button{',css)

    def test_home_typography_uses_exact_4174_sizing(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        for rule in (
            '#home .page-head h1{font-size:30px;',
            '#home .stream-filter-button{font-size:12px;font-weight:750;padding:8px 14px}',
            '#home .section-head h2{font-size:22px}',
            '#home .feature-card strong{font-size:18px}',
            '#home .eyebrow{font-size:11px}',
        ):
            self.assertIn(rule, css)

    def test_focus_sets_accepted_primary_layout(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        start=js.index('function setViewerPrimary(index,fromCarousel=false){')
        end=js.index('function renderFocusChoices()',start)
        focus=js[start:end]
        self.assertIn("viewing.layout='primary';",focus)
        self.assertIn('sessionLayout();',focus)

    def test_focus_carousel_matches_accepted_4174_controls(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        for value in ('id="focusCarousel"', 'id="focusCarouselInterval"', 'id="focusCarouselIntervalOutput"'):
            self.assertIn(value,html)
        for value in ('function startFocusCarousel()', 'function stopFocusCarousel()', "setViewerPrimary((viewing.primary+1)%viewing.ids.length,true)", "if(!fromCarousel)stopFocusCarousel();", "if(!viewerActive)window.hvStopFocusCarousel?.();"):
            self.assertIn(value,js)
        self.assertIn("document.addEventListener('visibilitychange'",js)

    def test_history_label_agrees_with_navigation_js(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("history:'歷史直播'", js)

if __name__ == "__main__":
    unittest.main()
