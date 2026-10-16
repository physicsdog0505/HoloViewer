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
    def test_4174_spa_runtime_is_torn_down_on_route_exit(self):
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        self.assertIn("if(currentRoute==='custom-session'&&r!=='custom-session')",app)
        self.assertIn("window.hvDestroy4174SharedViewer?.();",app)
        self.assertIn("window.hvDestroy4174SharedViewer=function hvDestroy4174SharedViewer()",viewer)
        for name in ("watch-multi","watch-grid","layout-auto","layout-equal","layout-primary","single-ptt","single-live","single-vod","collab-live-session","settings-open","custom-immersive"):
            self.assertIn("'"+name+"'",viewer)
        self.assertIn("clearInterval(translationRefreshTimer)",viewer)
        self.assertIn("clearInterval(verifiedSyncTimer)",viewer)
        self.assertIn(".custom-content-grid.video-only",css)
        self.assertIn("flex:1 1 auto!important;height:auto!important",css)

    def test_4174_home_selection_is_page_transient(self):
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("let currentRoute='home';",app)
        self.assertIn("selectedHomeVideos.clear();",app)
        self.assertNotIn("sessionStorage.setItem('selectedHomeVideos'",app)
        self.assertNotIn("localStorage.setItem('selectedHomeVideos'",app)

    def test_video_only_viewer_keeps_visible_16_9_player_geometry(self):
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        self.assertIn("body.custom-session-watching .custom-content-grid.video-only #stage > .player-card .video-wrap",css)
        self.assertIn("aspect-ratio:16 / 9!important",css)
        self.assertIn("grid-auto-rows:auto!important",css)
        self.assertIn("height:auto!important",css)
        self.assertIn("overflow:visible!important",css)

    def test_document_navigation_matches_4174_page_lifecycle(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        # Main navigation stays native: no SPA preventDefault/route interception.
        self.assertNotIn("querySelectorAll('[data-route]').forEach(link=>link.addEventListener('click'",js)
        self.assertNotIn("querySelectorAll('[data-mobile-route]').forEach(link=>link.addEventListener('click'",js)
        self.assertNotIn("querySelectorAll('[data-page-link]').forEach(link=>link.addEventListener('click'",js)
        # The URL is the viewer session source of truth, as in 4174's separate page.
        self.assertIn("return '/custom-view/session?'+q.toString()",js)
        self.assertIn("location.href=viewingSessionUrl(ids,opts)",js)
        self.assertIn("location.pathname==='/custom-view/session'?'custom-session'",js)
        self.assertIn("if(location.pathname!=='/custom-view/session')return;",js)
        self.assertIn("const params=new URLSearchParams(location.search)",js)
        self.assertNotIn("sessionStorage.setItem('hvCustomViewing'",js)
        self.assertNotIn("sessionStorage.getItem('hvCustomViewing'",js)
        self.assertNotIn("sessionStorage.setItem('hvMulti'",js)
        self.assertNotIn("location.hash.substring",js)
        # Home and History selections navigate to a new document.
        self.assertIn("$('multiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openViewingDocument(ids",js)
        self.assertIn("$('historyMultiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openViewingDocument(ids",js)
        # Custom builder and PTT focus/refresh also use real URLs.
        self.assertIn("location.href='/custom-view/session?'+q.toString()",js)
        self.assertIn("location.href='/ptt-today'",js)
        self.assertIn("'/ptt-today?focus=1'",js)
        # Static SPA fallback still exposes canonical routes for full reloads.
        for href in ('href="/"','href="/history"','href="/watchalong"','href="/custom-view"','href="/collab"','href="/ptt-today"'):
            self.assertIn(href,html)

    def test_collab_document_session_rehydrates_context_from_event_url(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn("eventId:String(event.event_id||'')",js)
        self.assertIn("const eventId=String(params.get('event')||'')",js)
        self.assertIn("api('/v1/collab/events/'+encodeURIComponent(eventId))",js)
        self.assertIn("opts.collabPollUrl=config.apiBase.replace",js)
        self.assertIn("opts.streamMetadata=streams.map",js)
        self.assertIn("opts.verifiedTimelineStarts={}",js)
        self.assertIn("collabPollUrl:typeof opts.collabPollUrl==='string'?opts.collabPollUrl:''",js)
        self.assertIn("Array.isArray(payload.event?.streams)?payload.event.streams:[]",viewer)
        self.assertIn("appendWatchStream(id,String(item.label||item.title||item.channel_name||id)",viewer)

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

    def test_viewer_ptt_iframe_controls_have_same_origin_receiver(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertIn("event.origin!==location.origin",js)
        self.assertIn("event.source!==window.parent",js)
        self.assertIn("data.type==='holoviewer:ptt-show-floor'",js)
        self.assertIn("data.type==='holoviewer:ptt-font-size'",js)
        self.assertIn("postMessage({type:'holoviewer:ptt-show-floor'",viewer)
        self.assertIn("postMessage({type:'holoviewer:ptt-font-size'",viewer)
        self.assertIn("font-size:var(--ptt-font-size,16px)",css)

    def test_ptt_reader_preserves_4174_shell_without_fake_data(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for item in ('class="ptt-shell"', 'class="ptt-toolbar"', 'class="ptt-reader"',
                     'id="ptt-today-meta"', 'id="ptt-refresh"', 'id="ptt-focus"'):
            self.assertIn(item, html)
        self.assertIn('.ptt-reader{position:relative;border:1px solid var(--line)', css)
        self.assertIn('ptt-focus-mode', css)
        self.assertIn('document.body.classList.toggle(\'ptt-focus-mode\'', js)
        self.assertIn("/v1/ptt/today?day=", js)
        self.assertIn("public-consumer-v1", js)
        self.assertIn("pttLastGoodCount", js)
        self.assertIn("pttLastGoodDay", js)
        self.assertIn("pttLoadInFlight", js)
        self.assertIn("homeLoadInFlight", js)
        self.assertIn("pttLastGoodDay&&pttLastGoodDay!==today", js)
        self.assertIn("10 秒後重試", js)
        self.assertIn('id="ptt-newest"', html)
        self.assertIn('id="ptt-show-floor"', html)
        self.assertIn("function pttAtBottom()", js)
        self.assertIn("function pttToLatest(force=false)", js)
        self.assertIn("pttFollowing", js)
        self.assertIn("list.addEventListener('wheel'", js)
        self.assertIn("list.addEventListener('scroll'", js)
        self.assertIn("while(list.children.length>300)", js)
        self.assertIn("row.floor+'樓'", js)
        self.assertIn(".ptt-reader .pushes{height:100%;overflow-y:auto", css)
        self.assertIn("font-family:Menlo,Monaco", css)
        self.assertIn(".ptt-push-author{color:#ffff00", css)
        self.assertIn(".ptt-push-content{color:#a9a900", css)
        self.assertNotIn("message('ptt-status'", js)

    def test_watchalong_builder_and_session_match_4174_public_boundary(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for part in ('id="watchalongBuilder"', 'class="manual-grid"', 'id="youtubePanel"',
                     'id="externalPanel"', 'id="singleFields"', 'id="playlistFields"',
                     'name="view_mode"', 'name="source_kind"', 'id="youtubeMode"',
                     'id="recentWatchGrid"', 'id="watchalong-session"'):
            self.assertIn(part, html)
        self.assertIn('.source-choice{display:grid', css)
        self.assertIn('.manual-shell{padding:20px}', css)
        self.assertIn('.watchalong-player-grid{display:grid', css)
        self.assertIn("const youtubePanel=document.getElementById('youtubePanel')", js)
        self.assertIn("api('/v1/watchalong/recent?days=30&limit=60')", js)
        self.assertIn("if(location.pathname!=='/watchalong/session')return;", js)
        self.assertIn("ensureWatchalongYoutubeApi", js)
        self.assertIn("watchalong-companion-card", js)
        self.assertNotIn("4174 同時視聽播放器的同步與對齊引擎尚未移植完成", js)
        self.assertNotIn("watch-add').onclick", js)

    def test_original_4174_collab_hub_structure(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        for name in ('collab-live','collab-upcoming','collab-ended'):
            self.assertIn('id="'+name+'"', html)
        self.assertNotIn('id="multi-url"', html)
        self.assertIn('function loadCollab()', js)
        self.assertIn("api('/v1/collab/live')", js)
        self.assertIn("function collabEntry(event)", js)
        self.assertIn("'stream-collab-entry'", js)
        self.assertIn("'👥'", js)
        self.assertIn("'多人'", js)
        self.assertIn("function openCollabEvent(event)", js)
        self.assertIn("location.href=viewingSessionUrl(ids", js)
        self.assertIn("eventId:String(event.event_id||'')", js)
        self.assertIn("api('/v1/collab/events/'+encodeURIComponent(eventId))", js)
        self.assertIn("opts.streamMetadata=streams.map(x=>", js)
        self.assertIn("const collabMetadata=new Map(", js)
        self.assertIn("collabMetadata.get(id)||streamMetadata.get(id)", js)
        self.assertIn("collabLabel:typeof opts.collabLabel==='string'?opts.collabLabel:''", js)
        self.assertIn("if(event.target.closest('.stream-collab-entry'))return", js)

    def test_original_4174_home_highlights_have_verified_rules(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('id="home-highlights"',html)
        self.assertIn('id="home-announcements"',html)
        for name in ('三期生告知','重大告知','初配信','周年','新衣裝','生日','3D LIVE','大型聯動','歌回','新造型'):
            self.assertIn(name,js)
        self.assertIn('renderHomeHighlights(rows)',js)
        self.assertIn("const homePollTimer=setInterval(",js)
        self.assertIn("$('custom-session').classList.contains('active')",js)
        self.assertIn("},30000);",js)

    def test_stream_id_validator_keeps_ascii_ids(self):
        js=(ROOT/"site/assets/app.js").read_text(encoding="utf-8")
        self.assertNotIn("[\\\\w-]", js, "Double escaped regex rejects real YouTube IDs")
        self.assertGreaterEqual(js.count("[A-Za-z0-9_-]{11}"), 3)

    def test_public_support_color_and_time_projection(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertIn('function applyHomeSupportStyle(el,item)',js)
        self.assertIn("item?.member_accent_dual",js)
        self.assertIn("el.dataset.supportMode='dual_color'",js)
        self.assertIn("function homeStartLabel(item)",js)
        self.assertIn("item?.start_at",js)
        self.assertIn("timeZone:'Asia/Taipei'",js)
        self.assertIn("hourCycle:'h23'",js)
        self.assertIn("if(mode==='neutral'||mode==='solid'||mode==='dual_color')return ''",js)
        self.assertIn("el.dataset.supportAccent='1'",js)
        self.assertIn('.stream-card[data-support-accent="1"]{background:color-mix',css)
        self.assertIn('.stream-card[data-support-accent="1"]:hover',css)
        self.assertIn('[data-support-mode="dual_color"].stream-card:hover',css)

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
        self.assertIn("position:fixed;left:2px;top:378px;z-index:65;width:64px", css)
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

    def test_immersive_exit_lives_inside_transplanted_fullscreen_surface(self):
        dom=(ROOT/'site/assets/4174-shared-viewing-a144bb3-dom.js').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertIn('id="immersiveExit" class="immersive-exit"',dom)
        self.assertIn("const immersiveExit=document.getElementById('immersiveExit')",js)
        self.assertIn("immersiveExit?.addEventListener('click'",js)
        self.assertIn("#immersiveExit.immersive-exit{display:none}",css)
        self.assertIn("body.custom-session-watching.custom-immersive #immersiveExit.immersive-exit",css)
        self.assertNotIn('id="immersiveExit"',html)

    def test_accepted_full_viewer_css_and_immersive_lifecycle(self):
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertGreater(len(css),100000)
        self.assertIn('body.custom-immersive',css)
        self.assertIn('body.custom-session-watching',css)
        self.assertIn('id="viewer-4174-transplant-css"',html)
        self.assertIn('requestFullscreen()',js)
        self.assertIn('fullscreenchange',js)
        self.assertIn('function applyImmersiveState(active)',js)
        self.assertIn('window.hvExit4174Immersive',js)

    def test_4174_viewer_ptt_panel_is_not_a_fake_feed(self):
        dom=(ROOT/'site/assets/4174-shared-viewing-a144bb3-dom.js').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn('class="ptt-live-panel"',dom)
        self.assertIn('/ptt-today?focus=1&embed=1',dom)
        self.assertIn("const pttPanel=document.querySelector('.ptt-live-panel')",js)
        self.assertIn("function placePttForLayout()",js)
        self.assertNotIn('目前沒有足夠的專串來源與影片時間證據。',dom)

    def test_shared_shell_has_no_invented_footer_or_dead_id_bindings(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        dom=(ROOT/'site/assets/4174-shared-viewing-a144bb3-dom.js').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertNotIn('<footer',html)
        element_ids=set(re.findall(r'\bid="([^"]+)"',html+"\n"+dom))
        required_ids=set(re.findall(r"\$\('([^']+)'\)",js))
        required_ids.update(re.findall(r"getElementById\('([^']+)'\)",viewer))
        optional_ids={'ptt-worker-feed','ptt-worker-follow'}
        self.assertEqual((required_ids-element_ids)-optional_ids,set(),"JS required ID missing from Public shell + transplanted Viewer DOM")

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
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn("function appendWatchStream(videoId,label,channelId='')",js)
        self.assertIn("streams.push(stream);players.push(null)",js)
        self.assertIn("function setReplacementTarget(index)",js)
        self.assertIn("replacementTarget",js)
        self.assertIn("liveRailItems",js)
        self.assertIn("mountWatchPlayer(index)",js)
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
        start=js.index("function linkedPlayPause(event)")
        end=js.index("window.addEventListener('message'",start)
        self.assertNotIn("setInterval(",js[start:end])

    def test_session_url_encodes_and_restores_explicit_stream_ids(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("clean.forEach(id=>q.append('stream',id))",js)
        self.assertIn("return '/custom-view/session?'+q.toString()",js)
        self.assertIn("location.href=viewingSessionUrl(ids,opts)",js)
        self.assertIn("const params=new URLSearchParams(location.search)",js)
        self.assertIn("params.getAll('stream')",js)
        self.assertIn("if(location.pathname!=='/custom-view/session')return;",js)
        self.assertIn("window.hvOpenCustomSession(ids,opts)",js)
        self.assertNotIn("location.hash.substring",js)
        self.assertNotIn("history.replaceState",js)

    def test_single_player_ptt_keeps_positive_aspect_ratio_contract(self):
        css=(ROOT/'site/assets/viewer-4174.css').read_text(encoding='utf-8')
        anchor='/* Public-only correction: observed #customContentGrid'
        self.assertIn(anchor,css)
        fix=css[css.index(anchor):]
        self.assertIn('flex:1 1 auto!important',fix)
        self.assertIn('grid-auto-rows:max-content!important',fix)
        self.assertIn('aspect-ratio:16/9!important',fix)
        self.assertIn('.custom-content-grid:has(#stage > .player-card:only-child)',fix)
        self.assertNotIn('viewerPttPanel.remove()',fix)

    def test_public_viewer_does_not_mount_uncertified_ptt_or_collapse_video(self):
        dom=(ROOT/'site/assets/4174-shared-viewing-a144bb3-dom.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("render4174SharedViewerDOM(viewing.ptt==='live')",app)
        self.assertIn("showLivePtt?'':' video-only'",dom)
        self.assertIn('.video-wrap{position:relative;aspect-ratio:16/9',css)
        self.assertIn('.custom-content-grid.video-only{display:block}',css)

    def test_custom_session_restores_on_reload_without_blank_shell(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('async function restoreCustomSession()',js)
        self.assertIn("if(location.pathname!=='/custom-view/session')return;",js)
        self.assertIn("const params=new URLSearchParams(location.search)",js)
        self.assertIn("if(!ids.length){location.replace('/custom-view');return;}",js)
        self.assertIn('window.hvOpenCustomSession(ids,opts)',js)
        self.assertNotIn("sessionStorage.setItem('hvCustomViewing'",js)
        self.assertNotIn("sessionStorage.getItem('hvCustomViewing'",js)

    def test_immersive_overrides_watch_shell_and_has_exit(self):
        css=(ROOT/'site/assets/4174-shared-viewing-a144bb3.css').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('body.custom-session-watching.custom-immersive .client-main',css)
        self.assertIn('body.custom-immersive .client-rail',css)
        self.assertIn("if(!document.fullscreenElement&&immersiveEnabled)",js)
        self.assertIn("if(event.key!=='Escape'||!immersiveEnabled)return",js)
        self.assertIn('window.hvExit4174Immersive?.()',app)
        self.assertNotIn('function applyViewerImmersive(enabled)',app)

    def test_viewer_teardown_tracks_every_recurring_timer(self):
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn('const translationRefreshTimer=setInterval(',js)
        self.assertIn('const verifiedSyncTimer=setInterval(',js)
        self.assertIn('let collabPollTimer=null',js)
        self.assertIn('clearInterval(translationRefreshTimer)',js)
        self.assertIn('clearInterval(verifiedSyncTimer)',js)
        self.assertIn('if(collabPollTimer)clearInterval(collabPollTimer)',js)

    def test_transplanted_youtube_players_mount_when_api_is_already_loaded(self):
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn('if(window.YT?.Player)',js)
        self.assertIn('streams.forEach((stream,index)=>mountWatchPlayer(index))',js)
        self.assertIn('script[src="https://www.youtube.com/iframe_api"]',js)

    def test_custom_url_entry_reports_add_failures_and_starts_new_document(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertIn('id="custom-selection-status"',html)
        self.assertIn('aria-live="polite"',html)
        self.assertIn('已加入 ',js)
        self.assertIn("if(!items.length){alert('請先加入至少一個影片。');return;}",js)
        self.assertIn("location.href='/custom-view/session?'+q.toString()",js)
        self.assertNotIn("document.querySelectorAll('#stage .player-card iframe').length!==items.length",js)

    def test_verified_timeline_engine_is_fail_closed_and_uses_4174_offset_formula(self):
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('const verifiedTimelineStarts=(config.verifiedTimelineStarts||{})',js)
        self.assertIn('function verifiedTimelineComplete()',js)
        self.assertIn('function timelineStartFor(index)',js)
        self.assertIn('if(expected<0)return false;',js)
        self.assertIn('expected>=duration)return false;',js)
        self.assertIn('seekTo(expected,true)',js)
        self.assertIn('verifiedTimelineStarts:opts.verifiedTimelineStarts',app)
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
