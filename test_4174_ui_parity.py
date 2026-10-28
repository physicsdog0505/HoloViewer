"""Guard against accidental redesign while migrating accepted local 4174 UI.

Only tests the frozen shared-sidebar contract, NOT full parity.
"""
from html.parser import HTMLParser
import json
import re
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent
EXPECTED = [
    ("home", "今", "今日直播"),
    ("history", "史", "歷史直播"),
    ("watchalong", "視", "同時視聽"),
    ("single", "自", "自訂觀看"),
    ("multi", "", "多人連動"),
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
    def test_sidebar_pointer_navigation_releases_focus_without_harming_keyboard(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertIn("function navigateSidebarLink(event,destination)",js)
        self.assertIn("if(event.detail>0)event.currentTarget.blur();",js)
        self.assertIn("navigateSidebarLink(event,link.dataset.route)",js)
        self.assertIn("navigateSidebarLink(event,'home')",js)
        self.assertIn(".client-rail:hover,.client-rail:focus-within",css)

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

    def test_home_degraded_bucket_is_kept_but_hidden_from_public_home(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        bucket_start=js.index('function homeBuckets(rows){')
        bucket_end=js.index('async function loadHomeCollab()',bucket_start)
        buckets=js[bucket_start:bucket_end]
        self.assertIn("buckets[homeLifecycleBucket(item)].push(item)",buckets)
        render_start=js.index('function renderHomeRows(rows){')
        render_end=js.index('function homeTimestamp(',render_start)
        render=js[render_start:render_end]
        self.assertIn("if(key==='unknown')",render)
        self.assertIn("$('home-unknown-section').hidden=true",render)

    def test_history_cards_use_canonical_batch_profiles_with_catalog_fallback(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("item?.start_at||item?.actual_start||item?.scheduled_start",js)
        self.assertIn("'yt3.googleusercontent.com'",js)
        self.assertIn('const canonicalChannelProfileCache=new Map()',js)
        self.assertIn('function normalizeCanonicalChannelProfile(profile)',js)
        self.assertIn('async function loadCanonicalChannelProfiles(channelIds)',js)
        self.assertIn("api('/v1/channels/profiles?'+query.toString())",js)
        self.assertNotIn("api('/v1/channels/'+encodeURIComponent(id)+'/profile')",js)
        self.assertIn('async function historyDisplayMetadataByChannel(items,catalogRows)',js)
        self.assertIn('else if(fallback.has(id))byChannel.set(id,fallback.get(id))',js)
        self.assertIn('function historyDisplayRow(item,byChannel)',js)
        self.assertIn("avatar_url:profile.avatar_url||item.avatar_url||''",js)
        self.assertIn("member_accent:profile.member_accent||item.member_accent||''",js)
        self.assertIn("support_mode:profile.support_mode||item.support_mode||''",js)
        self.assertIn("group:profile.group||profile.channel_group||item.group||item.channel_group||'other'",js)
        start=js.index('async function loadHistory(){')
        end=js.index('function collabEventState(event){',start)
        history=js[start:end]
        self.assertIn("requestHomeCatalogRows().then(rows=>({streams:rows})).catch(()=>null)",history)
        self.assertIn("homeCatalogPromise=api('/v1/catalog/today')",js)
        self.assertIn("const displayByChannel=await historyDisplayMetadataByChannel(data.items,catalogRows)",history)
        self.assertIn("historyDisplayRow({...item,lifecycle_state:'ended'},displayByChannel)",history)
        # Canonical profile owns presentation only; lifecycle/timing remains History-owned.
        self.assertNotIn("scheduled_start",history.split("historyDisplayRow",1)[0].split("lifecycle_state",1)[-1])

    def test_time_hub_uses_shared_canonical_batch_profile_cache(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        profile_start=js.index('function timeHubProfileRow(channelId){')
        profile_end=js.index('function timeHubAvatar(event){',profile_start)
        profile=js[profile_start:profile_end]
        self.assertIn('canonicalChannelProfileCache.get(id)',profile)
        self.assertIn("homeCatalogRows.find(row=>String(row?.channel_id||'')===id)",profile)
        open_start=js.index('function openTimeHub(){')
        open_end=js.index('function updateClientTopbar(',open_start)
        open_hub=js[open_start:open_end]
        self.assertIn('loadCanonicalChannelProfiles(TIME_HUB_MEMBERS.map(member=>member.channelId))',open_hub)
        self.assertIn("if($('timeHub')?.open)renderTimeHub()",open_hub)
        self.assertNotIn("/v1/channels/'+",open_hub)
        self.assertIn("function timeHubMonthEvents(monthKey)", js)
        self.assertIn("timeHubSelected='';renderTimeHub()", js)
        self.assertIn("這個月沒有生日或出道週年。", js)
        self.assertIn("dayLabel+' · '+event.label", js)

    def test_history_uses_direct_date_navigation_and_month_search(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")

        for snippet in (
            'id="historyHub"',
            'id="historyHubGrid"',
            'id="historyHubAgenda"',
            'id="historyHubPrev"',
            'id="historyHubNext"',
            'id="historyHubLatest"',
            'id="historyHubMemberSearch"',
            'id="historyHubSelectedAction"',
        ):
            self.assertIn(snippet, html)
        self.assertNotIn('id="historyTopDate"', html)

        for snippet in (
            'id="history-picker"',
            'id="historyDate"',
            'history-date-field-hidden',
            'id="historyPrevDay"',
            'id="historyNextDay"',
            'id="historyYesterday"',
            'id="historySearch"',
            'id="history-availability"',
            'id="history-search-summary"',
            'id="history-search-intent"',
            'id="history-channel-filters"',
            'id="history-pagination"',
            'id="historyMultiSelectBar"',
            'placeholder="搜尋直播、頻道或日期（例：10/15、9/10~10/15）…"',
        ):
            self.assertIn(snippet, html)

        self.assertNotIn('type="submit">查看</button>', html[html.index('id="history"'):html.index('id="ptt"')])
        self.assertIn('.history-toolbar{display:grid', css)
        self.assertIn('.history-date-nav{display:flex', css)
        self.assertIn('.history-date-field-hidden{display:none}', css)
        self.assertIn('.history-search-field input{width:100%}', css)
        self.assertIn('.history-search-intent{display:flex', css)
        self.assertIn('.history-search-chip{display:inline-flex', css)
        self.assertIn('.history-channel-filters{display:flex', css)
        self.assertIn('.history-channel-filter{display:inline-flex', css)
        self.assertIn('.history-channel-filter[aria-pressed="true"]', css)

        for snippet in (
            "historyDate').addEventListener('change'",
            "historyPrevDay').onclick=()=>historySetDay",
            "historyNextDay').onclick=()=>historySetDay",
            "historyYesterday').onclick=()=>historySetDay(historyBounds().latest)",
            "historySearch').addEventListener('keydown'",
            "if(event.key!=='Enter')return",
            "historySearch').addEventListener('input'",
            "if(String(event.target.value||'').trim())return",
            "async function loadYoutubeHistorySearchMonth(day)",
            "const HISTORY_MEMBER_ALIASES_PATH='/data/search/member-aliases.v1.json'",
            "function parseHistorySearchQuery(raw,registry,contentRegistry)",
            "intent:members.length?'member':'text'",
            "function historySearchRows(items,parsed)",
            "function renderHistorySearchIntent(parsed,rows)",
            "label.textContent='已辨識成員：'",
            "優先顯示同時相關的結果",
            "Number(b.score.allMembers)-Number(a.score.allMembers)",
            "const aliasesPromise=searchQuery?loadHistoryMemberAliases():Promise.resolve(null);",
            "resultCount>200?'找到 '+resultCount+' 筆 · 顯示前 200 筆'",
            "params.set('date',day)",
            "params.set('q',$('historySearch').value.trim())",
        ):
            self.assertIn(snippet, js)

        self.assertIn("let historyLoadGeneration=0;", js)
        self.assertIn("const generation=++historyLoadGeneration;", js)
        self.assertGreaterEqual(js.count("if(generation!==historyLoadGeneration)return;"), 3)

        self.assertIn("const HISTORY_CONTENT_ALIASES_PATH='/assets/search/history-content-aliases.v1.json';", js)
        self.assertIn("async function loadHistoryContentAliases()", js)
        self.assertIn("function historyContentAliasGroups(registry)", js)
        self.assertIn("function historyCollapseContentAliasPhrases(value,registry)", js)
        self.assertIn("function historyKeywordVariants(keyword,registry)", js)
        self.assertIn("const contentAliasesPromise=searchQuery?loadHistoryContentAliases():Promise.resolve(null);", js)
        self.assertIn("parseHistorySearchQuery(searchQuery,aliasRegistry,contentAliasRegistry)", js)
        self.assertNotIn("const HISTORY_CONTENT_ALIAS_GROUPS=[", js)

        aliases = json.loads((ROOT / "site/assets/search/history-content-aliases.v1.json").read_text(encoding="utf-8"))
        self.assertEqual(aliases["schema_version"], 1)
        self.assertEqual(aliases["dataset"], "holodocchi-history-content-aliases-v1")
        self.assertEqual(aliases["ownership"], "frontend-code-owned")
        self.assertGreaterEqual(len(aliases["groups"]), 90)
        flat_groups = [set(group) for group in aliases["groups"]]
        for expected in (
            {"歌回", "歌枠", "karaoke"},
            {"雜談", "雑談", "zatsudan"},
            {"minecraft", "マイクラ", "麥塊"},
            {"monster hunter", "モンハン", "魔物獵人"},
            {"street fighter 6", "スト6", "快打旋風6"},
            {"final fantasy xiv", "ff14", "ファイナルファンタジー14"},
            {"resident evil", "バイオハザード", "惡靈古堡"},
            {"mahjong soul", "雀魂", "麻將"},
            {"holocure", "ホロキュア"},
        ):
            self.assertTrue(any(expected.issubset(group) for group in flat_groups), expected)

        self.assertIn("const historyChannelSelection=new Set();", js)
        self.assertIn("function homeStartLabel(item,{includeYear=false}={})", js)
        self.assertIn("return (includeYear?out.year+'/':'')+out.month+'/'+out.day+' '+out.hour+':'+out.minute;", js)
        self.assertIn("function historyDurationLabel(item)", js)
        self.assertIn("Math.round((end-start)/60000)", js)
        self.assertIn("const time=homeStartLabel(item,{includeYear:history});const duration=history?historyDurationLabel(item):'';", js)
        self.assertIn("let activeRoute='';", js)
        self.assertIn("const reenteringHistory=r==='history'&&activeRoute&&activeRoute!=='history';", js)
        self.assertIn("if(reenteringHistory){", js)
        self.assertIn("$('historySearch').value='';", js)
        self.assertIn("$('historyDate').value=historyBounds().latest;", js)
        self.assertIn("historyChannelSelection.clear();", js)
        self.assertIn("function openHistoryHub()", js)
        self.assertIn("function renderHistoryHub()", js)
        self.assertIn("function historyHubDayRows(rows,month)", js)
        self.assertIn("function historyHubMoveMonth(delta)", js)
        self.assertIn("function historyHubImportantLabels(rows)", js)
        self.assertIn("function historyHubAgendaRows(rows)", js)
        self.assertIn("function historyHubGoDay(day)", js)
        self.assertIn("function historyHubMemberFilterState(rows,query,memberRegistry,contentRegistry)", js)
        self.assertIn("const matched=historySearchRows(rows,parsed).map(row=>row.item);", js)
        self.assertIn("await Promise.all([loadHistoryMemberAliases(),loadHistoryContentAliases()])", js)
        self.assertIn("function historyHubFilteredDayAvatars(dayRows,members,displayByChannel)", js)
        self.assertIn("appearance:'own'", js)
        self.assertIn("appearance:'guest'", js)
        self.assertIn("出現在其他頻道直播", js)
        self.assertIn(".history-hub-filter-avatar.is-guest", css)
        aliases = json.loads((Path(__file__).parent / "site/data/search/member-aliases.v1.json").read_text())
        ayame = next(member for member in aliases["members"] if member["channel_id"] == "UC7fk0CB07ly8oSl0aqKkqFg")
        ayame_aliases = {alias.get("value"): alias for alias in ayame.get("aliases", [])}
        for value in ("百鬼", "大小姐", "お嬢", "Ojou"):
            self.assertIn(value, ayame_aliases)
            self.assertEqual(ayame_aliases[value].get("strength"), "strong")
            self.assertIsNot(ayame_aliases[value].get("enabled"), False)
        self.assertNotIn("余", ayame_aliases)
        self.assertNotIn("よ", ayame_aliases)
        self.assertNotIn("Yo", ayame_aliases)
        vivi = next(member for member in aliases["members"] if member["channel_id"] == "UCGzTVXqMQHa4AgJVJIVvtDQ")
        vivi_aliases = {alias.get("value"): alias for alias in vivi.get("aliases", [])}
        self.assertEqual(vivi_aliases["VV"].get("strength"), "strong")
        self.assertIn(".history-hub-filter-avatar{width:36px;height:36px;", css)
        self.assertIn("if(members.length<1||members.length>3)return [];", js)
        self.assertIn("const filteredAvatars=historyHubFilteredDayAvatars(byDay.get(day)||[],resolvedMembers,displayByChannel);", js)
        self.assertIn("'history-hub-filter-avatars'", js)
        self.assertIn("button.onclick=()=>{historyHubSelected=day;renderHistoryHub().catch(()=>{})}", js)
        self.assertIn("button.ondblclick=event=>{event.preventDefault();historyHubGoDay(day)}", js)
        self.assertIn("$('historyHubSelectedAction').onclick=()=>historyHubGoDay(historyHubSelected);", js)
        self.assertIn("$('historyHubMemberSearch').addEventListener('keydown'", js)
        self.assertIn("historyHubMemberQuery=String(event.target.value||'').trim();", js)
        self.assertIn("historyHubMemberQuery='';", js)
        self.assertIn("if(selectedRows.length)selectedRows.forEach(item=>agenda.append(historyHubAgendaRow(item)))", js)
        self.assertNotIn("HISTORY_HUB_AGENDA_LIMIT", js)
        self.assertNotIn("history-stream-avatar", js)
        self.assertIn("overscroll-behavior:contain", css)
        self.assertIn("if(atTop||atBottom)event.preventDefault()", js)
        self.assertIn("const displayByChannel=await historyDisplayMetadataByChannel(rows,homeCatalogRows);", js)
        self.assertIn("historyHubSelected=historyBounds().latest", js)
        self.assertIn("if(routeName==='history'){openHistoryHub();return}", js)
        self.assertNotIn("historyTopDate", js)
        self.assertIn("function historyChannelFacetEntries(rows)", js)
        self.assertIn("if(!map.has(channelId))map.set(channelId,{channelId,count:0,row});", js)
        self.assertIn("function renderHistoryChannelFacets(rows)", js)
        self.assertIn("button.setAttribute('aria-pressed',String(historyChannelSelection.has(entry.channelId)))", js)
        self.assertIn("if(historyChannelSelection.has(entry.channelId))historyChannelSelection.delete(entry.channelId);else historyChannelSelection.add(entry.channelId);", js)
        self.assertIn("return historyChannelFacetRows.filter(row=>historyChannelSelection.has(String(row?.channel_id||'')));", js)
        self.assertIn("clear.onclick=()=>{historyChannelSelection.clear();", js)
        self.assertIn("historyChannelFacetRows=query?endedItems:[];", js)

        self.assertNotIn("已辨識多人搜尋：", js)
        self.assertNotIn("member_set", js[js.index("function parseHistorySearchQuery"):js.index("function historyMemberAliases")])
        self.assertNotIn("shiftDay(today,-30)", js[js.index("function historyBounds()"):js.index("const YOUTUBE_HISTORY_MANIFEST_PATH")])

    def test_history_prefers_youtube_static_manifest_month_read_path(self):
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

        self.assertIn("const YOUTUBE_HISTORY_MANIFEST_PATH='/youtube/v1/manifest.json'", js)
        self.assertIn("config.youtubeStaticBase", js)
        self.assertIn("fetchYoutubeStaticJson(YOUTUBE_HISTORY_MANIFEST_PATH,{manifest:true})", js)
        self.assertIn("youtubeHistoryMonthEntry(manifest,month)", js)
        self.assertIn("const cacheKey=String(entry.path||'')", js)
        self.assertIn("youtubeHistoryMonthCache.has(cacheKey)", js)
        self.assertIn("const payload=await fetchYoutubeStaticJson(entry.path)", js)
        self.assertIn("youtubeHistoryMonthCache.set(cacheKey,payload)", js)
        self.assertIn("payload?.schema_version!==1||!Array.isArray(payload.videos)", js)
        self.assertIn("youtubeHistoryTaipeiDay(row)===day", js)
        self.assertIn("function youtubeHistoryPayloadMonthsForDay(day)", js)
        self.assertIn("String(day||'').slice(8,10)!=='01'", js)
        self.assertIn("const previous=shiftDay(day,-1).slice(0,7)", js)
        self.assertIn("youtubeHistoryPayloadsForTaipeiMonth", js)
        self.assertIn("const liveArchive=row.is_live===true||Number(row.is_live)===1", js)
        self.assertIn("if(!liveArchive||!Number.isFinite(Date.parse(start))||!Number.isFinite(Date.parse(end))||Date.parse(end)<=Date.parse(start))return null", js)
        self.assertIn("if(availability==='private'||availability==='unavailable')return null", js)
        self.assertIn("return await loadYoutubeHistoryDay(day,offset,50)", js)
        self.assertIn("return api('/v1/history?day='+encodeURIComponent(day)+'&limit=50&offset='+offset)", js)
        self.assertIn("data.source==='legacy-api'&&data.static_error", js)
        self.assertIn("staticError?.code==='HISTORY_STATIC_UNAVAILABLE'", js)
        self.assertIn("throw youtubeHistoryUnavailable('YouTube 歷史月份尚未公開')", js)
        self.assertIn("published_months", js)
        self.assertNotIn("/objects/", js[js.index("const YOUTUBE_HISTORY_MANIFEST_PATH"):js.index("function historyChrome(){")])

    def test_custom_builder_matches_accepted_4174_controls(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/app.css").read_text(encoding="utf-8")
        for part in ('class="custom-layout"', 'class="selection-panel"', 'id="liveLibrary"',
                     'id="historyLibrary"', 'id="layout"', 'id="primary"', 'id="audio"',
                     'id="pttMode"', 'id="selectedCount"', 'id="custom-session"',
                     'data-custom-filter="hololive"', 'data-custom-filter="holostars"',
                     'data-custom-filter="mekpark"', 'data-custom-filter="all"'):
            self.assertIn(part, html)
        for part in ('moveStream(from,to)', "className='drag-handle'",
                     "radio.name='mainVideo'", "window.hvCustomCatalog=function(rows)",
                     'window.hvOpenCustomSession=function(ids,opts={})',
                     'function customLibraryFilter(){return homeFilter()}',
                     "card.dataset.group=String(row.group||row.channel_group||'other').toLowerCase()",
                     "button.addEventListener('click',()=>setCustomLibraryFilter(button.dataset.customFilter))"):
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
        self.assertIn('.ptt-reader{position:relative;border:1px solid var(--line)', css)
        self.assertIn('ptt-focus-mode', css)
        self.assertIn('document.body.classList.toggle(\'ptt-focus-mode\'', js)
        self.assertIn("/v1/ptt/today?day=", js)
        self.assertIn("public-consumer-v1", js)
        self.assertIn("pttLastGoodCount", js)
        self.assertIn("pttLastGoodDay", js)
        self.assertIn("pttLoadInFlight", js)
        self.assertIn("homeLoadInFlight", js)
        self.assertNotIn("pttLastGoodDay&&pttLastGoodDay!==today", js)
        self.assertIn("pttCarryLoadedFor!==today", js)
        self.assertIn("60 秒後重試", js)
        self.assertIn('id="ptt-newest"', html)
        self.assertIn('id="ptt-show-floor"', html)
        self.assertIn("function pttAtBottom()", js)
        self.assertIn("function pttToLatest(force=false)", js)
        self.assertIn("pttFollowing", js)
        self.assertIn("list.addEventListener('wheel'", js)
        self.assertIn("list.addEventListener('scroll'", js)
        self.assertIn("while(list.children.length>1000)", js)
        self.assertIn("row.floor+'樓'", js)
        self.assertIn(".ptt-reader .pushes{height:100%;overflow-y:auto", css)
        self.assertIn("font-family:Menlo,Monaco", css)
        self.assertIn(".ptt-push-author{color:#ffff00", css)
        self.assertIn(".ptt-push-content{color:#a9a900", css)
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
        self.assertIn("location.href='/watchalong-viewer/?'+q.toString();", js)
        self.assertIn("第一版同時視聽先支援 YouTube 片源", js)
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
        self.assertIn("function openStandaloneCollab(event)", js)
        self.assertIn("q.set('collab_event',String(event.event_id||''));", js)
        self.assertIn("q.set('collab_kind',isLive?'live':'vod');", js)
        self.assertIn("location.href='/viewer/?'+q.toString();", js)
        self.assertIn("if(event.target.closest('.stream-collab-entry'))return", js)

    def test_viewer_resolves_ptt_source_from_lifecycle_not_entry_mode(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("function verifiedEndedVodWindow(row)",viewer)
        self.assertIn("pttMeta.textContent='判定影片狀態中'",viewer)
        self.assertIn("async function videoMetadata(id)",viewer)
        self.assertIn("window.HoloViewerVideoMetadata?.resolve(id",viewer)
        self.assertIn("waitForRecovery:true,maxAttempts:6",viewer)
        self.assertIn("const row=await videoMetadata(id)",viewer)
        self.assertIn("if(lifecycle==='live')",viewer)
        self.assertIn("if(lifecycle==='ended')",viewer)
        self.assertIn("const vodWindow=verifiedEndedVodWindow(row)",viewer)
        self.assertIn("archiveWindows.set(id,cached)",viewer)
        self.assertIn("await loadCoverageDrivenVodPtt(pttContext,token)",viewer)
        self.assertIn("const resolvedPttMode=pttContext.mode==='live'?'live':(pttContext.mode==='vod'?'video':requestedPttMode)",viewer)
        self.assertNotIn("verifiedSameDayVodWindow",viewer)
        self.assertNotIn("loadSameDayVodPtt",viewer)
        self.assertNotIn("loadHybridVodPtt",viewer)
        resolver=viewer.split("async function resolvePrimaryPtt(){",1)[1].split("async function loadPtt(){",1)[0]
        self.assertNotIn("if(archiveVodEntry)",resolver)
        self.assertNotIn("requestedPttMode==='live'&&todayState==='live'",resolver)
        self.assertNotIn("歷史 VOD 請由 History 提供 verified window",resolver)

    def test_vod_history_ptt_uses_static_assets_and_verified_windows(self):
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/viewer-standalone.css').read_text(encoding='utf-8')
        config=(ROOT/'site/assets/config.js').read_text(encoding='utf-8')
        self.assertIn("const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';",app)
        self.assertIn("function trustedArchiveWindow(item)",app)
        self.assertIn("const start=String(item?.actual_start||'');",app)
        self.assertIn("const end=String(item?.actual_end||'');",app)
        trusted=app.split("function trustedArchiveWindow(item)",1)[1].split("function archiveScheduledStart",1)[0]
        self.assertNotIn("scheduled_start",trusted)
        self.assertIn("function archiveScheduledStart(item,window)",app)
        self.assertIn("scheduledStart:archiveScheduledStart(item,archiveWindow)",app)
        self.assertIn("query.append('ptt_window'",app)
        self.assertIn("window.scheduledStart||''",app)
        self.assertIn("openStandaloneViewer(ids,{vodWindows:historyVodWindows,pttMode:'video'})",app)
        self.assertIn("pttArchiveMonths:",config)
        self.assertIn("holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev",config)
        self.assertIn("holoviewer-ptt-static-assets-pilot.singlebagel.workers.dev",config)
        self.assertIn("static-assets-full-2026-06.json",config)
        self.assertIn("static-assets-full-2026-07.json",config)
        self.assertIn("static-assets-full-2026-08.json",config)
        self.assertIn("static-assets-full-2026-09.json",config)
        self.assertIn("static-assets-full-2026-10.json",config)
        self.assertIn("params.getAll('ptt_window')",viewer)
        self.assertIn("anchorSource!==PTT_ARCHIVE_ANCHOR",viewer)
        self.assertIn("function archiveObjectRange(item)",viewer)
        self.assertIn("function archiveObjectPlan(archives,startMs,endMs)",viewer)
        self.assertIn("for(const item of archive.manifest.objects)",viewer)
        self.assertIn("archiveRangesIntersect(range.startMs,range.endMs,startMs,endMs)",viewer)
        self.assertIn("crypto.subtle.digest('SHA-256',buffer)",viewer)
        self.assertIn("payload.pushes.length!==expectedPushCount",viewer)
        self.assertIn("async function fetchArchiveObject(source,item)",viewer)
        self.assertNotIn("fetchArchiveChunk",viewer)
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("const days=archiveCoverageDays(fetchStartMs,endMs)",viewer)
        self.assertIn("const source=archiveSourceForMonth(month)",viewer)
        self.assertIn("occurred>=rangeStart&&occurred<rangeEnd",viewer)
        self.assertIn("row?.source_record_key||row?.push_id",viewer)
        self.assertIn("Number.isInteger(row?.floor)&&row.floor>0",viewer)
        self.assertIn("資料可能不完整",viewer)
        self.assertIn("async function loadPttDayWindowRows(day,startMs,endMs)",viewer)
        self.assertIn("/v1/ptt/history?day=",viewer)
        self.assertIn("if(!archiveVodEntry)await loadCatalog();",viewer)
        self.assertIn(".ptt-floor{",css)
        self.assertIn(".ptt-row.has-floor{grid-template-columns:max-content max-content max-content minmax(0,1fr)}",css)
        self.assertIn(".ptt-time{color:#dedede;font-size:.82em;font-weight:500",css)
        self.assertIn(".ptt-row{display:grid;grid-template-columns:max-content max-content minmax(0,1fr);column-gap:0",css)
        self.assertIn(".ptt-body{min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;padding-left:4px}",css)
        self.assertIn(".ptt-kind{font-weight:800;color:#f4f4f4;padding-right:2px}",css)
        self.assertIn(".ptt-floor{color:#929da4;font-size:.76em;font-weight:600",css)
        self.assertIn('id="pttShowFloor" type="checkbox"',(ROOT/'site/viewer/index.html').read_text(encoding='utf-8'))
        self.assertIn('class="viewer-ptt ptt-floor-hidden"',(ROOT/'site/viewer/index.html').read_text(encoding='utf-8'))
        self.assertIn(".viewer-ptt.ptt-floor-hidden .ptt-row.has-floor{grid-template-columns:max-content max-content minmax(0,1fr)}",css)
        self.assertIn(".viewer-ptt.ptt-floor-hidden .ptt-floor{display:none}",css)
        self.assertIn("function setPttFloorVisible(show)",viewer)
        self.assertIn("pttShowFloor.addEventListener('change'",viewer)
        self.assertIn("setPttFloorVisible(false);",viewer)
        self.assertIn("el.append(kindEl,time,floorEl,body);",viewer)
        self.assertIn("if(floor!==null)el.classList.add('has-floor');",viewer)
        self.assertIn("const todayRow=catalogRows.find(row=>String(row?.video_id||'')===id);",viewer)
        self.assertNotIn("function verifiedSameDayVodWindow(row)",viewer)
        self.assertIn("lifecycle!=='ended'",viewer)
        self.assertIn("function verifiedEndedVodWindow(row)",viewer)
        self.assertIn("async function loadTodayPttPayload(day)",viewer)
        self.assertIn("&limit=300",viewer)
        self.assertNotIn("&limit=1000",viewer)
        self.assertIn("const VOD_PTT_HISTORY_PAGE_CAP=20;",viewer)
        self.assertIn("async function loadCoverageDrivenVodPtt(context,token)",viewer)
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("occurred>=rangeStart&&occurred<rangeEnd",viewer)
        self.assertIn("[window.videoId,window.start,window.end,window.anchorSource,window.scheduledStart||'']",viewer)
        self.assertIn("await loadCoverageDrivenVodPtt(pttContext,token)",viewer)
        self.assertIn("Archive + D1 · ⚠ 尚未完成封存",viewer)
        self.assertIn("D1 history · ⚠ Archive 尚不可用",viewer)
        self.assertIn("mode:'vod'",viewer)


    def test_historical_ptt_manifest_drives_partition_neutral_object_plan(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        config=(ROOT/'site/assets/config.js').read_text(encoding='utf-8')
        helper_start=viewer.index("function nextIsoDay(day){")
        helper_end=viewer.index("async function archiveSha256Hex(buffer){",helper_start)
        helpers=viewer[helper_start:helper_end]
        row_start=viewer.index("function archiveRowIdentity(row){")
        row_end=viewer.index("function archiveObjectPlan(archives,startMs,endMs){",row_start)
        row_helpers=viewer[row_start:row_end]
        plan_start=viewer.index("function archiveObjectPlan(archives,startMs,endMs){")
        plan_end=viewer.index("async function loadCoverageDrivenVodPtt(context,token){",plan_start)
        plan_helper=viewer[plan_start:plan_end]
        visible_start=viewer.index("function buildVodPttPresentationTimes(rows){")
        visible_end=viewer.index("function setVodPttRows(rows){",visible_start)
        visible_helper=viewer[visible_start:visible_end]
        registry="""{
          "2026-06": {"base":"https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev","manifest":"/ptt/v1/manifests/static-assets-full-2026-06.json"},
          "2026-07": {"base":"https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev","manifest":"/ptt/v1/manifests/static-assets-full-2026-07.json"},
          "2026-08": {"base":"https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev","manifest":"/ptt/v1/manifests/static-assets-full-2026-08.json"},
          "2026-09": {"base":"https://holoviewer-ptt-static-assets-pilot.singlebagel.workers.dev","manifest":"/ptt/v1/manifests/static-assets-full-2026-09.json"},
          "2026-10": {"base":"https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev","manifest":"/ptt/v1/manifests/static-assets-full-2026-10.json"}
        }"""
        script="""
const PTT_ARCHIVE_MONTHS=REGISTRY;
function taipeiDayForDate(value){
 const d=value instanceof Date?value:new Date(value);
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d);
 const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function archiveUnavailableError(message){const error=new Error(message);error.archiveUnavailable=true;return error;}
HELPERS
ROW_HELPERS
PLAN_HELPER
VISIBLE_HELPER
const sep=archiveSourcesForWindow(Date.parse('2026-09-18T11:00:25Z'),Date.parse('2026-09-18T16:13:34Z'));
const crossSources=archiveSourcesForWindow(Date.parse('2026-09-30T15:59:00Z'),Date.parse('2026-09-30T16:01:00Z'));
const july=archiveSourcesForWindow(Date.parse('2026-07-01T00:00:00Z'),Date.parse('2026-07-31T15:59:59Z'));
const julyAugust=archiveSourcesForWindow(Date.parse('2026-07-31T15:59:00Z'),Date.parse('2026-07-31T16:01:00Z'));
const juneJuly=archiveSourcesForWindow(Date.parse('2026-06-30T15:59:00Z'),Date.parse('2026-06-30T16:01:00Z'));

const hourlyObjects=Array.from({length:7},(_,i)=>({
 key:'ptt/v1/chunks/2026/09/18/'+String(1100+i*100).padStart(4,'0')+'.json',
 bucket_start:new Date(Date.parse('2026-09-18T11:00:00Z')+i*3600000).toISOString(),
 bucket_end:new Date(Date.parse('2026-09-18T12:00:00Z')+i*3600000).toISOString(),
 sha256:'a'.repeat(64),pushes:10
}));
const hourlyPlan=archiveObjectPlan(
 [{source:sep[0],manifest:{objects:hourlyObjects}}],
 Date.parse('2026-09-18T11:00:25Z'),Date.parse('2026-09-18T16:13:34Z')
);

const dailyObject={
 key:'ptt/v1/days/2026-10-21/day.json',
 partition_start:'2026-10-20T16:00:00Z',
 partition_end:'2026-10-21T16:00:00Z',
 sha256:'b'.repeat(64),push_count:2400
};
const dailyPlan=archiveObjectPlan(
 [{source:{month:'2026-10',base:'https://example.invalid'},manifest:{objects:[dailyObject]}}],
 Date.parse('2026-10-21T01:00:00Z'),Date.parse('2026-10-21T03:00:00Z')
);

const previousDay={
 key:'ptt/v1/days/2026-10-20/day.json',
 range_start:'2026-10-19T16:00:00Z',range_end:'2026-10-20T16:00:00Z',
 sha256:'c'.repeat(64),push_count:2000
};
const nextDay={
 key:'ptt/v1/days/2026-10-21/day.json',
 range_start:'2026-10-20T16:00:00Z',range_end:'2026-10-21T16:00:00Z',
 sha256:'d'.repeat(64),push_count:2100
};
const crossDayPlan=archiveObjectPlan(
 [{source:{month:'2026-10',base:'https://example.invalid'},manifest:{objects:[previousDay,nextDay]}}],
 Date.parse('2026-10-20T15:30:00Z'),Date.parse('2026-10-20T17:30:00Z')
);

const twelveHour={
 key:'ptt/v1/partitions/2026-10-21-a.json',
 range_start:'2026-10-20T16:00:00Z',range_end:'2026-10-21T04:00:00Z',
 sha256:'e'.repeat(64),push_count:1200
};
const twelveHourPlan=archiveObjectPlan(
 [{source:{month:'2026-10',base:'https://example.invalid'},manifest:{objects:[twelveHour]}}],
 Date.parse('2026-10-21T02:00:00Z'),Date.parse('2026-10-21T03:00:00Z')
);

const rows=Array.from({length:2019},(_,i)=>({
 source_record_key:'J33JnrVJiIQ:'+i,
 occurred_at:new Date(Date.parse('2026-09-18T11:00:25Z')+i*9000).toISOString(),
 aid:'J33JnrVJiIQ',source_line:247+i,push_id:'push-'+i,floor:i+1
}));
rows.push({...rows[1000]});
const deduped=dedupeArchiveRows(rows);
const visible=vodPttVisibleCountAt(deduped,Date.parse('2026-09-18T16:13:34Z'));

process.stdout.write(JSON.stringify({
 crossSources,july,julyAugust,juneJuly,
 hourlyPlan:hourlyPlan.map(x=>x.item.key),
 dailyPlan:dailyPlan.map(x=>x.item.key),
 crossDayPlan:crossDayPlan.map(x=>x.item.key),
 twelveHourPlan:twelveHourPlan.map(x=>x.item.key),
 oldRange:archiveObjectRange(hourlyObjects[0]),
 dailyRange:archiveObjectRange(dailyObject),
 oldCount:archiveObjectPushCount(hourlyObjects[0]),
 dailyCount:archiveObjectPushCount(dailyObject),
 deduped:deduped.length,visible
}));
""".replace("REGISTRY",registry).replace("ROW_HELPERS",row_helpers).replace("PLAN_HELPER",plan_helper).replace("VISIBLE_HELPER",visible_helper).replace("HELPERS",helpers)
        result=subprocess.run(["node","-e",script],check=True,capture_output=True,text=True)
        payload=json.loads(result.stdout)
        self.assertEqual([x["month"] for x in payload["crossSources"]],["2026-09","2026-10"])
        self.assertEqual([x["month"] for x in payload["july"]],["2026-07"])
        self.assertEqual([x["month"] for x in payload["julyAugust"]],["2026-07","2026-08"])
        self.assertEqual([x["month"] for x in payload["juneJuly"]],["2026-06","2026-07"])
        self.assertEqual(len(payload["hourlyPlan"]),6)
        self.assertEqual(payload["dailyPlan"],["ptt/v1/days/2026-10-21/day.json"])
        self.assertEqual(payload["crossDayPlan"],[
            "ptt/v1/days/2026-10-20/day.json",
            "ptt/v1/days/2026-10-21/day.json",
        ])
        self.assertEqual(payload["twelveHourPlan"],["ptt/v1/partitions/2026-10-21-a.json"])
        self.assertEqual(payload["oldCount"],10)
        self.assertEqual(payload["dailyCount"],2400)
        self.assertEqual(payload["deduped"],2019)
        self.assertEqual(payload["visible"],2019)
        self.assertIn('"2026-09": Object.freeze({',config)
        self.assertIn('"2026-06": Object.freeze({',config)
        self.assertIn('"2026-07": Object.freeze({',config)

        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("archiveObjectPlan([{source,manifest}],rangeStart,rangeEnd)",viewer)
        self.assertIn("occurred>=rangeStart&&occurred<rangeEnd",viewer)
        self.assertIn("const coverageStatus=archiveDayCoverageStatus(manifest,day)",viewer)
        self.assertNotIn("archiveHourKey(",viewer)
        self.assertNotIn("archiveHourKeys(",viewer)
        self.assertNotIn("archiveHourTaipeiMonth(",viewer)
        self.assertNotIn("chunk_minutes!==60",viewer)
        self.assertNotIn("if daily",viewer.lower())
        self.assertNotIn("if hourly",viewer.lower())

    def test_historical_ptt_manifest_failure_falls_back_without_claiming_empty(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("throw archiveUnavailableError('歷史 PTT '+source.month+' manifest HTTP '+response.status+'：'+url);",viewer)
        self.assertIn("if(!archive||archive.coverageStatus!=='COMPLETE')",viewer)
        self.assertIn("try{d1=await loadPttDayWindowRows(day,rangeStart,rangeEnd)}",viewer)
        self.assertIn("const unresolvedDays=dayResults.filter(item=>!item.archive&&!item.d1)",viewer)
        self.assertIn("result.authoritativeZero",viewer)
        self.assertIn("Archive 尚未 COMPLETE，不能宣稱這段真正沒有推文",viewer)
        self.assertIn("VOD PTT · UNKNOWN / UNAVAILABLE",viewer)

    def test_historical_ptt_archive_transport_is_read_only(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        archive=viewer.split("const archiveManifestCache=new Map();",1)[1].split("function taipeiDayStartMs(day){",1)[0]
        for verb in ("method:'POST'","method:'PUT'","method:'PATCH'","method:'DELETE'","INSERT ","UPDATE ","DELETE FROM","wrangler","D1","R2"):
            self.assertNotIn(verb,archive)
        self.assertIn("credentials:'omit'",archive)
        self.assertIn("cache:'no-cache'",archive)

    def test_vod_ptt_source_selection_is_coverage_driven_per_taipei_day(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("function archiveDayCoverageStatus(manifest,day)",viewer)
        self.assertIn("async function resolveArchiveDaySlice(day,rangeStart,rangeEnd)",viewer)
        self.assertIn("async function resolveCoverageDrivenVodPtt(context)",viewer)
        self.assertIn("const days=archiveCoverageDays(fetchStartMs,endMs);",viewer)
        self.assertIn("if(!archive||archive.coverageStatus!=='COMPLETE')",viewer)
        self.assertIn("d1=await loadPttDayWindowRows(day,rangeStart,rangeEnd)",viewer)
        self.assertIn("rows:merged,days:dayResults.map(item=>item.day)",viewer)
        self.assertIn("allArchiveComplete,authoritativeZero:allArchiveComplete&&merged.length===0",viewer)
        self.assertIn("d1IncompleteDays",viewer)
        self.assertIn("Archive + D1 · ⚠ 尚未完成封存",viewer)
        self.assertIn("D1 history · ⚠ Archive 尚不可用",viewer)
        self.assertNotIn("function recentUnsealedArchiveDay(day)",viewer)
        self.assertNotIn("function recentSingleDayVodDay(context)",viewer)

    def test_vod_ptt_coverage_resolver_executes_complete_partial_unavailable_and_incomplete_cases(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        day_start=viewer.index("function nextIsoDay(day){")
        day_end=viewer.index("function archiveMonthKeys(startMs,endMs){",day_start)
        day_helpers=viewer[day_start:day_end]
        resolver_start=viewer.index("async function resolveCoverageDrivenVodPtt(context){")
        resolver_end=viewer.index("function archiveRowIdentity(row){",resolver_start)
        resolver=viewer[resolver_start:resolver_end]
        row_start=viewer.index("function archiveRowIdentity(row){")
        row_end=viewer.index("function archiveObjectPlan(archives,startMs,endMs){",row_start)
        row_helpers=viewer[row_start:row_end]
        script=r"""
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
function taipeiDayForDate(value){
 const d=value instanceof Date?value:new Date(value);
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(d);
 const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function taipeiDayStartMs(day){
 const ms=Date.parse(String(day||'')+'T00:00:00+08:00');
 return Number.isFinite(ms)?ms:null;
}
function vodPttFetchStartMs(context){return Date.parse(context.start)}
DAY_HELPERS
ROW_HELPERS
RESOLVER
function row(key,occurred){return {source_record_key:key,push_id:key,aid:'aid',source_line:Number(key.replace(/\D/g,''))||1,occurred_at:occurred,author:'u',content:key}}

(async()=>{
 let d1Calls=[];
 resolveArchiveDaySlice=async(day)=>{
  if(day==='2026-10-20')return {day,coverageStatus:'COMPLETE',rows:[row('a1','2026-10-20T15:45:00Z')]};
  return {day,coverageStatus:'PARTIAL',rows:[row('x2','2026-10-20T16:30:00Z')]};
 };
 loadPttDayWindowRows=async(day)=>{d1Calls.push(day);return {rows:[row('x2','2026-10-20T16:30:00Z'),row('y3','2026-10-20T17:00:00Z')],incomplete:false}};
 const cross=await resolveCoverageDrivenVodPtt({
  start:'2026-10-20T15:30:00Z',end:'2026-10-20T17:30:00Z',anchorSource:PTT_ARCHIVE_ANCHOR
 });

 let completeD1=0;
 resolveArchiveDaySlice=async(day)=>({day,coverageStatus:'COMPLETE',rows:[]});
 loadPttDayWindowRows=async()=>{completeD1+=1;return {rows:[],incomplete:false}};
 const completeZero=await resolveCoverageDrivenVodPtt({
  start:'2026-10-21T01:00:00Z',end:'2026-10-21T03:00:00Z',anchorSource:PTT_ARCHIVE_ANCHOR
 });

 let fallbackD1=0;
 resolveArchiveDaySlice=async()=>{throw new Error('archive unavailable')};
 loadPttDayWindowRows=async()=>{fallbackD1+=1;return {rows:[row('f4','2026-10-21T01:30:00Z')],incomplete:false}};
 const unavailable=await resolveCoverageDrivenVodPtt({
  start:'2026-10-21T01:00:00Z',end:'2026-10-21T03:00:00Z',anchorSource:PTT_ARCHIVE_ANCHOR
 });

 resolveArchiveDaySlice=async(day)=>({day,coverageStatus:'PARTIAL',rows:[]});
 loadPttDayWindowRows=async()=>({rows:[],incomplete:true});
 const capped=await resolveCoverageDrivenVodPtt({
  start:'2026-10-21T01:00:00Z',end:'2026-10-21T03:00:00Z',anchorSource:PTT_ARCHIVE_ANCHOR
 });

 process.stdout.write(JSON.stringify({
  crossRows:cross.rows.map(x=>x.source_record_key),
  crossD1:d1Calls,
  crossDays:cross.days,
  completeD1,completeZero:completeZero.authoritativeZero,
  fallbackD1,unavailableRows:unavailable.rows.length,unavailableDays:unavailable.archiveUnavailableDays,
  cappedIncomplete:capped.d1IncompleteDays,cappedZero:capped.authoritativeZero
 }));
})().catch(error=>{console.error(error);process.exit(1)});
""".replace("DAY_HELPERS",day_helpers).replace("ROW_HELPERS",row_helpers).replace("RESOLVER",resolver)
        result=subprocess.run(["node","-e",script],check=True,capture_output=True,text=True)
        payload=json.loads(result.stdout)
        self.assertEqual(payload["crossDays"],["2026-10-20","2026-10-21"])
        self.assertEqual(payload["crossD1"],["2026-10-21"])
        self.assertEqual(payload["crossRows"],["a1","x2","y3"])
        self.assertEqual(payload["completeD1"],0)
        self.assertTrue(payload["completeZero"])
        self.assertEqual(payload["fallbackD1"],1)
        self.assertEqual(payload["unavailableRows"],1)
        self.assertEqual(payload["unavailableDays"],["2026-10-21"])
        self.assertEqual(payload["cappedIncomplete"],["2026-10-21"])
        self.assertFalse(payload["cappedZero"])
        self.assertIn("if(token!==pttResolveToken)return;",viewer)

    def test_public_collab_context_reaches_standalone_viewer(self):
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("function openStandaloneCollab(event)",app)
        self.assertIn("q.set('collab_event',String(event.event_id||''));",app)
        self.assertIn("q.set('collab_kind',isLive?'live':'vod');",app)
        self.assertIn("q.set('collab_day',collabDay);",app)
        self.assertIn("api('/v1/collab/history?day='+encodeURIComponent(selected)+'&limit=50&offset=0')",app)
        self.assertIn("const collabDay=/^\\d{4}-\\d{2}-\\d{2}$/.test",viewer)
        self.assertIn("(collabDay?'?day='+encodeURIComponent(collabDay):'')",viewer)
        self.assertIn("const collabEventId=String(params.get('collab_event')||'');",viewer)
        self.assertIn("const collabKind=['live','vod'].includes(params.get('collab_kind'))?params.get('collab_kind'):'';",viewer)
        self.assertIn("async function fetchCollabEvent()",viewer)
        self.assertIn("'/v1/collab/events/'+encodeURIComponent(collabEventId)",viewer)
        self.assertIn("async function reconcileLiveCollab()",viewer)
        self.assertIn("collabState(row)==='live'",viewer)
        self.assertIn("setInterval(()=>{if(!document.hidden)reconcileLiveCollab()},10000)",viewer)
        self.assertIn("function reconcileVodCollab()",viewer)
        self.assertIn("event?.sync?.available===true",viewer)
        self.assertIn("absoluteMs>=start&&absoluteMs<end",viewer)
        self.assertIn("player.seekTo(target,true)",viewer)

    def test_collab_hub_card_follows_4174_event_presentation(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("const ordered=streams.slice().sort(",js)
        self.assertIn("String(event.label||'多人連動').replace(/候選/g,'')",js)
        self.assertIn("const dateLabel=dateTimes.length?",js)
        self.assertIn("timeZone:'Asia/Taipei'",js)
        self.assertIn("seenChannels=new Set()",js)
        self.assertIn("parts.join(' · ')+' · 進入多人連動畫面'",js)
        self.assertIn("youtube.dataset.youtubeHref='https://www.youtube.com/watch?v='+first.video_id",js)
        self.assertIn("if(e.target.closest('[data-youtube-href]'))return",js)

    def test_public_home_lifecycle_freshness_grouping_contract(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        start=js.index('function homeLifecycleBucket(item){')
        end=js.index('function homeCard(',start)
        classifier=js[start:end]
        self.assertNotIn('scheduled_start',classifier)
        self.assertNotIn('actual_start',classifier)
        self.assertNotIn('actual_end',classifier)
        cases=[
            {'video_id':'fresh-live','lifecycle_state':'live','stale':False},
            {'video_id':'stale-live','lifecycle_state':'live','stale':True},
            {'video_id':'unknown','lifecycle_state':'unknown','stale':False},
            {'video_id':'ended','lifecycle_state':'ended','stale':False},
            {'video_id':'0-21K73BYWc','lifecycle_state':'upcoming','stale':False,'start_at':'2026-10-19T12:30:00Z'},
            {'video_id':'waiting','lifecycle_state':'waiting','stale':False},
        ]
        script=classifier+'\nprocess.stdout.write(JSON.stringify('+json.dumps(cases)+' .map(homeLifecycleBucket)));'
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout),['live','unknown','unknown','ended','upcoming','upcoming'])
        bucket_start=js.index('function homeBuckets(rows){')
        bucket_end=js.index('async function loadHomeCollab()',bucket_start)
        buckets=js[bucket_start:bucket_end]
        self.assertIn('buckets[homeLifecycleBucket(item)].push(item)',buckets)

    def test_public_home_highlights_follow_lifecycle_freshness_contract(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        classifier_start=js.index('function homeLifecycleBucket(item){')
        classifier_end=js.index('function homeCard(',classifier_start)
        rules_start=js.index('const HOME_HIGHLIGHT_RULES=')
        choose_end=js.index('function renderHomeHighlights(rows,filter=homeFilter()){',rules_start)
        script=js[classifier_start:classifier_end]+js[rules_start:choose_end]
        cases=[
            {'video_id':'stale000001','lifecycle_state':'live','stale':True,'title':'重大告知'},
            {'video_id':'fresh000001','lifecycle_state':'live','stale':False,'title':'重大告知'},
            {'video_id':'0-21K73BYWc','lifecycle_state':'upcoming','stale':False,'title':'重大告知','start_at':'2026-10-19T12:30:00Z'},
        ]
        node=script+'\nconst rows='+json.dumps(cases)+';process.stdout.write(JSON.stringify({picks:chooseHomeHighlights(rows).map(x=>({id:x.row.video_id,score:x.score})),scores:rows.map(x=>homeHighlightMatch(x).score)}));'
        result=subprocess.run(['node','-e',node],check=True,capture_output=True,text=True)
        payload=json.loads(result.stdout)
        picks={item['id']:item['score'] for item in payload['picks']}
        self.assertNotIn('stale000001',picks)
        self.assertIn('fresh000001',picks)
        self.assertIn('0-21K73BYWc',picks)
        self.assertEqual(payload['scores'][0],105)
        self.assertEqual(payload['scores'][1],110)
        self.assertEqual(payload['scores'][2],105)
        choose=js[js.index('function chooseHomeHighlights(rows){'):choose_end]
        self.assertIn("const bucket=homeLifecycleBucket(row)",choose)
        self.assertIn("if(bucket!=='live'&&bucket!=='upcoming')continue",choose)
        match=js[js.index('function homeHighlightMatch(item){'):js.index('function chooseHomeHighlights(rows){')]
        self.assertIn("homeLifecycleBucket(item)==='live'",match)
        self.assertNotIn("String(item.lifecycle_state",match)

    def test_original_4174_home_highlights_have_verified_rules(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn('id="home-highlights"',html)
        self.assertIn('id="home-announcements"',html)
        for name in ('三期生告知','重大告知','初配信','周年','新衣裝','生日','3D LIVE','大型聯動','歌回','新造型'):
            self.assertIn(name,js)
        self.assertIn('renderHomeHighlights(homeCatalogRows,value)',js)
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
        self.assertIn("function homeStartLabel(item,{includeYear=false}={})",js)
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

    def test_public_viewer_call_mode_is_frontend_only_and_keeps_iframes_mounted(self):
        html=(ROOT/'site/viewer/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/viewer-standalone.css').read_text(encoding='utf-8')
        self.assertIn('id="viewerCallMode"',html)
        self.assertIn("function setCallMode(on,{hint=false}={})",js)
        self.assertIn("function callTapTempo(now=performance.now())",js)
        self.assertIn("if(callTapTimes.length>4)callTapTimes.shift()",js)
        self.assertIn("function callDirectionDown(direction,now=performance.now())",js)
        self.assertIn("<=callBeatMs*2.05",js)
        self.assertIn("callSetSideMotion(direction,switched?'fast':'two')",js)
        self.assertIn("performance.now()-callDirectionStartedAt>=callBeatMs*1.9",js)
        self.assertIn("callSetSideMotion(direction,'wave')",js)
        self.assertIn("function callFlickUp()",js)
        self.assertIn("function callPulseChest()",js)
        self.assertIn("function callSpaceDown()",js)
        self.assertIn("document.addEventListener('keydown',handleCallKeyDown)",js)
        self.assertIn("document.addEventListener('keyup',handleCallKeyUp)",js)
        self.assertIn("callEditableTarget(event.target)",js)
        self.assertIn("mountCallOverlay();",js)
        self.assertIn("card.append(callOverlay)",js)
        self.assertIn("Never re-append live iframe cards",js)
        self.assertIn(".call-overlay{",css)
        self.assertIn("body.call-mode .call-overlay{display:block}",css)
        self.assertIn("@keyframes call-arc-left",css)
        self.assertIn("@keyframes call-arc-wide-left",css)
        self.assertIn("@keyframes call-space-pump",css)
        self.assertIn("bottom:-10%;width:min(84%,820px);height:56%",css)
        self.assertIn("width:40px;height:48%",css)
        self.assertIn("translate(-50%,-104%)",js)
        self.assertIn("animation:call-arc-wide-left var(--call-beat-4)",css)
        self.assertIn("animation:call-arc-wide-right var(--call-beat-4)",css)
        self.assertIn("--call-beat-2",css)
        self.assertIn("callOverlay.style.setProperty('--call-beat-4'",js)
        self.assertIn('id="viewerCallMode" type="button" aria-pressed="false" title="關閉打 Call 模式" hidden',html)
        self.assertIn("callWakeTaps=callWakeTaps.filter(t=>now-t<=800)",js)
        self.assertIn("setCallMode(true,{hint:true})",js)
        self.assertIn("if(callTapTimes.length===4)startCallAutoBeat()",js)
        self.assertIn("callAutoBeatTimer=setInterval",js)
        self.assertIn("callModeButton.hidden=!callEnabled",js)
        self.assertIn("clip-path:polygon",css)
        self.assertIn("@keyframes call-arc-fast",css)
        self.assertNotIn("/v1/call",js)

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
        self.assertIn("'/custom-view#custom-session?'+new URLSearchParams([",js)
        self.assertIn("...viewing.ids.map(id=>['stream',id])",js)
        self.assertIn("params.getAll('stream')",js)
        self.assertIn("const recovered=urls.length?ids:",js)
        self.assertIn("const hashRoute=location.hash.substring(1).split('?')[0];",js)
        self.assertIn("const pathRoute=location.pathname==='/history'?'history':",js)
        self.assertIn("const initialRoute=hashRoute==='custom-session'?'custom-session':legacyHashRoute||pathRoute||hashRoute||'home';",js)
        self.assertIn("route(initialRoute)",js)

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

    def test_custom_history_start_preserves_verified_ptt_windows(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("const historyVodWindows=new Map()",js)
        self.assertIn("const window=trustedArchiveWindow(row)",js)
        self.assertIn("window.scheduledStart=archiveScheduledStart(row,window)",js)
        self.assertIn("historyVodWindows.set(window.videoId,window)",js)
        self.assertIn("document.getElementById('start').onclick=async()=>",js)
        self.assertIn("const missing=items.filter(id=>!historyVodWindows.has(id))",js)
        self.assertIn("async function resolveVideoMetadata(id)",js)
        self.assertIn("window.HoloViewerVideoMetadata?.resolve(id",js)
        self.assertIn("waitForRecovery:false,maxAttempts:1",js)
        self.assertIn("async function resolveVodWindow(id)",js)
        self.assertIn("if(!row||String(row?.lifecycle_state||row?.state||'').toLowerCase()!=='ended')return null",js)
        self.assertIn("const window=trustedArchiveWindow({...row,video_id:String(row?.video_id||id)})",js)
        self.assertIn("const window=await resolveVodWindow(id)",js)
        self.assertIn("if(window)historyVodWindows.set(id,window)",js)
        self.assertIn("const selectedHistory=items.length>0&&items.every(id=>historyVodWindows.has(id))",js)
        self.assertIn("const pttMode=selectedHistory?'video':document.getElementById('pttMode').value",js)
        self.assertIn("if(selectedHistory)items.forEach(id=>appendArchiveWindow(q,historyVodWindows.get(id)))",js)

    def test_vod_ptt_preloads_before_actual_start_when_scheduled_hint_is_missing(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("const anchorMs=hasScheduled?Math.min(startMs,scheduledMs):startMs",viewer)
        self.assertIn("return anchorMs-3600000",viewer)
        self.assertIn("Math.abs(scheduledMs-startMs)<=43200000",viewer)
        helper_start=viewer.index("function vodPttFetchStartMs(context){")
        helper_end=viewer.index("function pttVodPlaybackMs(){",helper_start)
        helper=viewer[helper_start:helper_end]
        script=helper+"\nprocess.stdout.write(JSON.stringify([vodPttFetchStartMs({start:'2026-10-17T06:00:12Z',scheduledStart:''}),vodPttFetchStartMs({start:'2026-10-17T06:00:12Z',scheduledStart:'2026-10-17T06:00:00Z'}),vodPttFetchStartMs({start:'2026-10-17T06:00:12Z',scheduledStart:'2026-10-17T06:01:00Z'})]));"
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        values=json.loads(result.stdout)
        self.assertEqual(values[0],1792213212000)
        self.assertEqual(values[1],1792213200000)
        self.assertEqual(values[2],1792213212000)

    def test_vod_ptt_preloads_scheduled_start_before_first_play(self):
        app=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("parts.length!==4&&parts.length!==5",viewer)
        self.assertIn("scheduledStart:Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000?scheduledStart:''",viewer)
        self.assertIn("function vodPttCutoffMs(context,seconds,hasPlayed)",viewer)
        self.assertIn("if(!hasPlayed&&seconds<=3&&Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000)return scheduledMs",viewer)
        self.assertIn("return anchorMs-3600000",viewer)
        self.assertIn("if(state===YT.PlayerState.PLAYING)pttVodHasPlayed=true",viewer)
        self.assertIn("scheduledStart:vodWindow.scheduledStart||''",viewer)
        helper_start=viewer.index("function vodPttCutoffMs(context,seconds,hasPlayed){")
        helper_end=viewer.index("function vodPttFetchStartMs(context){",helper_start)
        helper=viewer[helper_start:helper_end]
        script=helper+"\nconst c={start:'2026-10-18T06:10:00Z',end:'2026-10-18T07:00:00Z',scheduledStart:'2026-10-18T06:00:00Z'};process.stdout.write(JSON.stringify([vodPttCutoffMs(c,0,false),vodPttCutoffMs(c,2,false),vodPttCutoffMs(c,10,false),vodPttCutoffMs(c,0,true)]));"
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        values=json.loads(result.stdout)
        self.assertEqual(values[0],1792303200000)
        self.assertEqual(values[1],1792303200000)
        self.assertEqual(values[2],1792303810000)
        self.assertEqual(values[3],1792303800000)

    def test_vod_ptt_tracks_youtube_playback_timeline(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("function pttVodPlaybackMs()",viewer)
        self.assertIn("const raw=startMs+Math.max(0,seconds)*1000",viewer)
        self.assertIn("function buildVodPttPresentationTimes(rows)",viewer)
        self.assertIn("function vodPttVisibleCountAt(rows,absoluteMs,presentationTimes=null)",viewer)
        self.assertIn("function syncVodPttTimeline({forceFollow=false}={})",viewer)
        helper_start=viewer.index("function buildVodPttPresentationTimes(rows){")
        helper_end=viewer.index("function setVodPttRows(rows){",helper_start)
        helper=viewer[helper_start:helper_end]
        script=helper+"\nconst rows=[{occurred_at:'2026-10-18T08:14:59Z'},{occurred_at:'2026-10-18T08:15:00Z'},{occurred_at:'2026-10-18T08:15:01Z'}];process.stdout.write(String(vodPttVisibleCountAt(rows,Date.parse('2026-10-18T08:15:00Z'))));"
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        self.assertEqual(result.stdout,'2')
        self.assertIn("pttVodPresentationTimes=buildVodPttPresentationTimes(pttVodRows)",viewer)
        self.assertIn("vodPttVisibleCountAt(pttVodRows,absoluteMs,pttVodPresentationTimes)",viewer)
        self.assertIn("if(visible>pttVodVisibleCount)",viewer)
        self.assertIn("pttFeed.replaceChildren(...pttVodRows.slice(0,visible).map(pttRow))",viewer)
        self.assertIn("currentSeconds<pttVodLastSample.seconds-.75",viewer)
        self.assertIn("Math.abs(currentSeconds-expected)>2.5",viewer)
        self.assertIn("setInterval(()=>syncVodPttTimeline(),500)",viewer)
        self.assertIn("syncVodPttTimeline({forceFollow:true})",viewer)
        self.assertIn("最新 · '+clock",viewer)
        self.assertIn("對齊播放時間",viewer)
        self.assertNotIn("pttFeed.scrollTop=0;\n  pttMeta.textContent=context.day",viewer)

    def test_vod_ptt_dense_minute_is_paced_in_stable_order(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        helper_start=viewer.index("function buildVodPttPresentationTimes(rows){")
        helper_end=viewer.index("function setVodPttRows(rows){",helper_start)
        helper=viewer[helper_start:helper_end]
        script=helper+r"""
const base='2026-10-17T06:10:00Z';
const rows=Array.from({length:60},(_,i)=>({occurred_at:base,push_id:'p'+String(i).padStart(2,'0')}));
const times=buildVodPttPresentationTimes(rows);
const t0=Date.parse(base);
process.stdout.write(JSON.stringify({
 first:times[0]-t0,
 second:times[1]-t0,
 middle:times[30]-t0,
 last:times[59]-t0,
 at10s:vodPttVisibleCountAt(rows,t0+10000,times),
 at30s:vodPttVisibleCountAt(rows,t0+30000,times),
 at59s:vodPttVisibleCountAt(rows,t0+59000,times)
}));
"""
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        payload=json.loads(result.stdout)
        self.assertEqual(payload["first"],0)
        self.assertEqual(payload["second"],1000)
        self.assertEqual(payload["middle"],30000)
        self.assertEqual(payload["last"],59000)
        self.assertEqual(payload["at10s"],11)
        self.assertEqual(payload["at30s"],31)
        self.assertEqual(payload["at59s"],60)

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
        self.assertIn("sessionStorage.setItem('hvCustomViewing'",js)
        self.assertIn('function restoreCustomSession()',js)
        self.assertIn("if(!recovered.length){route('single');return;}",js)
        self.assertIn("openStandaloneViewer(recovered,{pttMode:legacyPtt==='live'?'live':'video'})",js)
        self.assertNotIn('window.hvOpenCustomSession(recovered,',js)

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

    def test_transplanted_youtube_players_mount_when_api_is_already_loaded(self):
        js=(ROOT/'site/assets/4174-shared-viewing-a144bb3.js').read_text(encoding='utf-8')
        self.assertIn('if(window.YT?.Player)',js)
        self.assertIn('streams.forEach((stream,index)=>mountWatchPlayer(index))',js)
        self.assertIn('script[src="https://www.youtube.com/iframe_api"]',js)

    def test_custom_url_entry_reports_add_and_standalone_start(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        self.assertIn('id="custom-selection-status"',html)
        self.assertIn('aria-live="polite"',html)
        self.assertIn('已加入 ',js)
        self.assertIn("q.set('mode',items.length>1?'multi':'single')",js)
        self.assertIn("location.href='/viewer/?'+q.toString();",js)
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
        self.assertIn("$('live-channel-rail').hidden=!box.children.length;",js)
        self.assertIn("$('live-channel-rail').hidden=!$('live-channel-list').childElementCount;",js)
        self.assertNotIn("!['home','custom-session'].includes(r)",js)
        self.assertNotIn("(!$('home').classList.contains('active')&&!$('custom-session').classList.contains('active'))",js)
        self.assertIn("window.hvEnsureLiveRail?.();",js)
        self.assertIn("applyHomeFilter();refreshWatchRail();",js)
        self.assertIn("selectWatchRailVideo(id,name)",js)

    def test_public_shell_dedupes_catalog_and_defers_watchalong_startup(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("let homeCatalogPromise=null;",js)
        self.assertIn("function requestHomeCatalogRows(){",js)
        self.assertIn("if(homeCatalogPromise)return homeCatalogPromise;",js)
        self.assertIn("homeCatalogPromise=api('/v1/catalog/today')",js)
        self.assertIn("requestHomeCatalogRows().then(rows=>({streams:rows})).catch(()=>null)",js)
        self.assertIn("window.hvLoadWatchalongLanding=loadWatchalongLanding;",js)
        self.assertIn("if(initialRoute==='watchalong')loadWatchalongLanding();",js)
        self.assertIn("if(r==='watchalong')window.hvLoadWatchalongLanding?.();",js)
        self.assertNotIn("\nloadWatchalongLanding();\n\nconst youtubePanel=",js)

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

    def test_public_ptt_polling_matches_60s_publisher_cadence(self):
        app=(ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        ptt_today=(ROOT / "site/assets/ptt-today.js").read_text(encoding="utf-8")
        viewer=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        watch=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        for js in (app,ptt_today,viewer,watch):
            self.assertIn("const PTT_POLL_MS=60000;",js)
        self.assertIn("},PTT_POLL_MS);",app)
        self.assertIn("const pollTimer=setInterval(()=>{if(!document.hidden)loadPtt()},PTT_POLL_MS);",ptt_today)
        self.assertIn("const pttPollTimer=setInterval(()=>{if(!document.hidden)loadPtt()},PTT_POLL_MS);",viewer)
        self.assertIn("pttTimer=setInterval(()=>{if(!document.hidden)loadTodayPtt(taipeiDay())},PTT_POLL_MS);",watch)
        self.assertIn("if($('ptt').classList.contains('active'))loadPtt();",app)
        self.assertIn("if(!document.hidden&&pttContext.mode==='live')loadPtt();",viewer)
        self.assertIn("if(!document.hidden&&hostStatus.textContent==='live')loadTodayPtt(taipeiDay());",watch)
        self.assertNotIn("setInterval(loadPtt,10000)",viewer)
        self.assertNotIn("loadTodayPtt(taipeiDay())},10000",watch)
        self.assertNotIn("if(!document.hidden&&$('ptt').classList.contains('active'))loadPtt();\n},10000)",app)
        self.assertNotIn("10 秒後重試",app)
        self.assertNotIn("每 10 秒自動重試",app)
        self.assertNotIn("10 秒後重試",ptt_today)
        self.assertNotIn("loadPtt()},10000",ptt_today)
        # Non-PTT timers (collab lifecycle, local VOD timeline rendering, etc.)
        # are intentionally outside this emergency mitigation.
        self.assertIn("reconcileLiveCollab()},10000)",viewer)
        self.assertIn("syncVodPttTimeline(),500)",viewer)

    def test_all_vod_entries_use_metadata_fallback_for_timing(self):
        app=(ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        viewer=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        watch=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        resolver=(ROOT / "site/assets/video-metadata-resolver.js").read_text(encoding="utf-8")
        for html_path in ("site/index.html","site/viewer/index.html","site/watchalong-viewer/index.html"):
            html=(ROOT / html_path).read_text(encoding="utf-8")
            self.assertIn("video-metadata-resolver.js",html)
        self.assertIn("payload.status==='metadata_pending'",resolver)
        self.assertIn("payload.error==='recovery_queue_busy'",resolver)
        self.assertIn("payload.error==='metadata_not_found_cached'",resolver)
        self.assertIn("async function resolveVideoMetadata(id)",app)
        self.assertIn("window.HoloViewerVideoMetadata?.resolve(id",app)
        self.assertIn("async function resolveVodWindow(id)",app)
        self.assertIn("const window=await resolveVodWindow(id);",app)
        self.assertIn("async function videoMetadata(id)",viewer)
        self.assertIn("window.HoloViewerVideoMetadata?.resolve(id",viewer)
        self.assertIn("waitForRecovery:true,maxAttempts:6",viewer)
        self.assertIn("const row=await videoMetadata(id);",viewer)
        self.assertIn("window.HoloViewerVideoMetadata?.resolve(videoId",watch)
        self.assertIn("pttDay:/^\\d{4}-\\d{2}-\\d{2}$/.test(watchalongSessionDay)",watch)

    def test_metadata_transport_fallback_is_bounded(self):
        resolver=(ROOT / "site/assets/video-metadata-resolver.js").read_text(encoding="utf-8")
        app=(ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        script = """
global.window={HOLOVIEWER_CONFIG:{apiBase:'https://api.example'}};
let calls=[];
global.fetch=async(url,options)=>{
  calls.push(url);
  if(url.includes('/v1/catalog/videos/'))throw new TypeError('catalog transport');
  return {status:200,json:async()=>({video_id:'abcdefghijk',lifecycle_state:'ended',actual_start:'2026-10-18T15:00:06Z',actual_end:'2026-10-18T16:04:31Z'})};
};
eval(RESOLVER_SOURCE);
const first=await window.HoloViewerVideoMetadata.resolve('abcdefghijk',{apiBase:'https://api.example',maxAttempts:1});
global.fetch=async(url,options)=>{
  calls.push(url);
  if(url.includes('/v1/catalog/videos/'))return {status:404,json:async()=>({error:'not_found'})};
  throw new TypeError('metadata transport');
};
const second=await window.HoloViewerVideoMetadata.resolve('abcdefghijk',{apiBase:'https://api.example',maxAttempts:1});
const controller=new AbortController();controller.abort();
const third=await window.HoloViewerVideoMetadata.resolve('abcdefghijk',{apiBase:'https://api.example',signal:controller.signal,maxAttempts:1});
process.stdout.write(JSON.stringify({first,second,third,calls}));
""".replace("RESOLVER_SOURCE", json.dumps(resolver))
        result=subprocess.run(
            ["node","--input-type=module","-e",script],
            check=True,capture_output=True,text=True
        )
        payload=json.loads(result.stdout)
        self.assertEqual(payload["first"]["status"],"ready")
        self.assertEqual(payload["first"]["source"],"metadata")
        self.assertTrue(any("/v1/videos/abcdefghijk/metadata" in url for url in payload["calls"]))
        self.assertEqual(payload["second"]["status"],"error")
        self.assertEqual(payload["second"]["httpStatus"],0)
        self.assertEqual(payload["second"]["row"]["error"],"transport_error")
        self.assertEqual(payload["third"]["status"],"aborted")

        # Custom History Start must fail closed if the shared resolver itself
        # rejects unexpectedly. Keep this structural check local to the exact
        # production wrapper instead of evaluating app.js under Node globals.
        wrapper_start=app.index("async function resolveVideoMetadata(id){")
        wrapper_end=app.index("async function resolveVodWindow(id){",wrapper_start)
        wrapper=app[wrapper_start:wrapper_end]
        self.assertIn("try{",wrapper)
        self.assertIn("await window.HoloViewerVideoMetadata?.resolve(id",wrapper)
        self.assertIn("return result?.status==='ready'?result.row:null;",wrapper)
        self.assertIn("catch{return null}",wrapper)

    def test_public_viewing_entries_use_standalone_surfaces_not_spa(self):
        app=(ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("function standaloneViewerUrl(ids,{vodWindows=null,pttMode=''}={})",app)
        self.assertIn("return '/viewer/?'+q.toString();",app)
        self.assertIn("location.href='/viewer/?'+q.toString();",app)
        self.assertIn("location.href='/watchalong-viewer/?'+q.toString();",app)
        # Keep the old SPA mount only as dormant compatibility code; normal entry
        # points and old-session recovery must not call it.
        self.assertEqual(app.count("window.hvOpenCustomSession?.("),0)
        self.assertNotIn("window.hvOpenCustomSession(recovered,",app)
        self.assertIn("openStandaloneViewer(recovered,{pttMode:legacyPtt==='live'?'live':'video'})",app)

    def test_viewer_lock_is_behavior_not_ptt_workspace_geometry(self):
        js=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let lockedIndex=workspaceLayout==='focus'?primaryIndex:null;", js)
        self.assertIn("workspaceLayout='sidebar';", js)
        self.assertIn("return lockedIndex!==null?'focus':'primary';", js)
        self.assertIn("else if(preset==='focus'){layout='primary';lockedIndex=primaryIndex}", js)
        self.assertIn("workspace.className='viewer-workspace workspace-sidebar layout-'+effective+' count-'+Math.max(1,geometryCount);", js)
        self.assertIn("const count=Math.max(0,streams.filter((_,index)=>viewingPovVisible(index)).length);", js)
        self.assertIn("q.set('workspace',currentLayoutPreset()==='focus'?'focus':'sidebar');", js)

    def test_viewer_ptt_follow_changes_only_on_user_scroll_intent(self):
        js=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let pttUserScrollIntentUntil=0;", js)
        self.assertIn("function markPttUserScrollIntent(ms=1800)", js)
        self.assertIn("if(pttLayoutTransitionDepth>0||!hasPttUserScrollIntent())return;", js)
        self.assertIn("pttFeed.addEventListener('touchstart'", js)
        self.assertIn("pttFeed.addEventListener('pointerdown'", js)
        self.assertIn("new ResizeObserver(()=>", js)
        self.assertIn("if(pttFollowing)repinPttAfterLayout({force:true});", js)

    def test_viewer_lock_transition_preserves_follow_before_geometry_mutation(self):
        js=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let pttLayoutTransitionDepth=0;", js)
        self.assertIn("const wasFollowing=pttFollowing||pttAtBottom();\n pttLayoutTransitionDepth+=1;", js)
        self.assertIn("pttLayoutTransitionDepth=Math.max(0,pttLayoutTransitionDepth-1);", js)
        self.assertIn("if(pttLayoutTransitionDepth>0||!hasPttUserScrollIntent())return;", js)
        self.assertIn("if(wasFollowing){\n  pttFollowing=true;\n  repinPttAfterLayout({force:true});\n }", js)

    def test_viewer_locking_current_primary_does_not_reload_ptt(self):
        js=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        self.assertIn("const previousIndex=primaryIndex;", js)
        self.assertIn("const primaryChanged=index!==previousIndex;", js)
        self.assertIn("if(primaryChanged&&!viewingTimelineActive())resolvePrimaryPtt();", js)
        self.assertIn("if(index!==primaryIndex)setPrimary(index);", js)
        self.assertIn("setLayoutPreset('focus');", js)

    def test_viewer_ptt_follow_survives_immersive_layout_and_resize(self):
        js=(ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        self.assertIn("function repinPttAfterLayout({force=false}={})", js)
        self.assertIn("if(pttVodMode())syncVodPttTimeline({forceFollow:true});", js)
        self.assertIn("const wasFollowing=pttFollowing||pttAtBottom();", js)
        self.assertIn("document.addEventListener('fullscreenchange'", js)
        self.assertIn("window.addEventListener('resize'", js)
        self.assertIn("window.addEventListener('orientationchange'", js)
        self.assertIn("if(wasFollowing){\n  pttFollowing=true;\n  repinPttAfterLayout({force:true});\n }", js)
        self.assertIn("clearTimeout(pttLayoutRepinTimer);cancelAnimationFrame(pttResizeFrame);", js)


    def test_watchalong_user_offset_resets_and_static_base_is_separate(self):
        js=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let segmentBaseOffsetSeconds=0;",js)
        self.assertIn("let userOffsetSeconds=0;",js)
        self.assertIn("return hostSeconds+segmentBaseOffsetSeconds+userOffsetSeconds;",js)
        self.assertIn("function setSegmentBaseOffset(value)",js)
        self.assertIn("setSegmentBaseOffset(initialSegment.source-initialSegment.host);",js)
        self.assertIn("setOffset(source-host-segmentBaseOffsetSeconds)",js)
        self.assertNotIn("sourceOffsetSeconds",js)
        self.assertNotIn("q.set('offset'",js)
        self.assertNotIn("params.has('offset')",js)

        # Production repro contract: episode 13 starts at host 737.92s,
        # source starts at 0, and a fresh-page user correction is 0.
        host=1235.0
        base=0.0-737.92
        user=0.0
        expected=host+base+user
        self.assertAlmostEqual(expected,497.08,places=2)
        self.assertGreaterEqual(expected,0)

    def test_watchalong_resume_waits_for_both_players_and_does_not_pause_host(self):
        js=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        self.assertIn("let hostPlayerReady=false;",js)
        self.assertIn("let sourcePlayerReady=false;",js)
        self.assertIn("if(resumeApplied||resumePending||!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer)return;",js)
        self.assertIn("if(!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer||!Number.isFinite(seconds))return false;",js)
        self.assertIn("function verifyResumeClock(target,attempt=0)",js)
        self.assertIn("const delays=[120,400,1000];",js)
        self.assertIn("if(syncTimer||!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer)return;",js)
        self.assertIn("onError:event=>{hostPlayerReady=false;hostStatus.textContent=youtubePlayerErrorLabel(event?.data)}",js)
        self.assertIn("onError:event=>{sourcePlayerReady=false;sourceStatus.textContent=youtubePlayerErrorLabel(event?.data)}",js)
        resume_start=js.index("function seekWatchalongToHost(seconds){")
        resume_end=js.index("function resumeClockApplied",resume_start)
        resume=js[resume_start:resume_end]
        self.assertNotIn("hostPlayer.pauseVideo()",resume)

    def test_watchalong_pre_segment_standby_never_pauses_host(self):
        js=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        state_start=js.index("function onHostStateChange(event){")
        state_end=js.index("function youtubePlayerErrorLabel",state_start)
        state=js[state_start:state_end]
        self.assertIn("if(Number.isFinite(host)&&sourceExpectedTime(host)<0){setSourceStandby(true);return}",state)
        self.assertNotIn("hostPlayer.pauseVideo()",state)
        standby_start=js.index("function setSourceStandby(active){")
        standby_end=js.index("function onHostStateChange",standby_start)
        standby=js[standby_start:standby_end]
        self.assertNotIn("hostPlayer.pauseVideo()",standby)


    def test_watchalong_history_ptt_uses_daily_coverage_with_month_routing(self):
        js=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")
        config=(ROOT / "site/assets/config.js").read_text(encoding="utf-8")
        self.assertIn("const PTT_ARCHIVE_MONTHS=config.pttArchiveMonths||{};",js)
        self.assertIn("function archiveCoverageDays(startMs,endMs)",js)
        self.assertIn("function archiveSourceForMonth(month)",js)
        self.assertIn("function archiveDayCoverageStatus(manifest,day)",js)
        self.assertIn("function archiveObjectRange(item)",js)
        self.assertIn("item?.partition_start??item?.range_start??item?.bucket_start",js)
        self.assertIn("item?.partition_end??item?.range_end??item?.bucket_end",js)
        self.assertIn("function archiveObjectPlan(source,manifest,startMs,endMs)",js)
        self.assertIn("archiveRangesIntersect(entry.range.startMs,entry.range.endMs,startMs,endMs)",js)
        self.assertIn("async function resolveArchiveDaySlice(day,rangeStart,rangeEnd)",js)
        self.assertIn("async function loadPttDayWindowRows(day,startMs,endMs)",js)
        self.assertIn("async function resolveCoverageDrivenWatchalongPtt(windowInfo)",js)
        self.assertIn("if(!archive||archive.coverageStatus!=='COMPLETE')",js)
        self.assertIn("'/v1/ptt/history?day='",js)
        self.assertIn("const cacheKey=source.month+'|'+source.base+'|'+source.manifest;",js)
        self.assertIn("const url=source.base+'/'+item.key;",js)
        self.assertIn("fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache'",js)
        self.assertNotIn("function archiveHourKey",js)
        self.assertNotIn("function archiveHourKeys",js)
        self.assertNotIn("'ptt/v1/chunks/'",js)
        self.assertNotIn("day.json",js)
        self.assertNotIn("config.pttArchiveBase",js)
        self.assertNotIn("config.pttArchiveManifest",js)
        self.assertIn('pttArchiveMonths: Object.freeze({',config)
        self.assertIn('"2026-10": Object.freeze({',config)



    def test_watchalong_animation_layout_has_stable_host_volume_control(self):
        html=(ROOT / "site/watchalong-viewer/index.html").read_text(encoding="utf-8")
        css=(ROOT / "site/assets/watchalong-standalone.css").read_text(encoding="utf-8")
        js=(ROOT / "site/assets/watchalong-standalone.js").read_text(encoding="utf-8")

        self.assertIn('id="hostMuteToggle"',html)
        self.assertIn('id="hostVolume"',html)
        self.assertIn('id="hostVolumeValue"',html)
        self.assertIn('.watchalong-workspace.layout-source .host-volume-control{display:flex}',css)
        self.assertIn('.host-volume-label{font-size:10px',css)
        self.assertIn('.host-volume-control input{flex:1 1 auto',css)
        self.assertNotIn('position:absolute;right:8px;top:8px',css)
        self.assertLess(html.index('</article>'),html.index('class="host-volume-control"'))

        self.assertIn("const hostVolume=document.getElementById('hostVolume');",js)
        self.assertIn("function refreshHostVolumeUi()",js)
        self.assertIn("function setHostVolume(value)",js)
        self.assertIn("hostPlayer?.setVolume?.(volume);",js)
        self.assertIn("hostPlayer?.mute?.();",js)
        self.assertIn("hostPlayer.unMute?.();",js)
        self.assertIn("hostVolume?.addEventListener('input'",js)
        self.assertIn("hostMuteToggle?.addEventListener('click'",js)
        self.assertNotIn("sourcePlayer?.setVolume?.(volume)",js)



    def test_watchalong_past_uses_recent_history_months_without_touching_featured(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn('const recentMonths=published.slice(-2);',js)
        self.assertIn('.filter(row=>watchalongCandidateTitle(row?.title));',js)
        self.assertIn('watchalongPastRows=historyRows.map(row=>historyDisplayRow(row,canonical));',js)
        self.assertIn('renderWatchalongPastRows(curatedHosts);',js)
        self.assertNotIn("api('/v1/watchalong/recent?days=90&limit=100')",js)
        self.assertIn('id="watchalongPastSearch"',html)
        self.assertIn('#watchalong-past .history-search-field{',css)
        self.assertIn('width:min(620px,100%)',css)
        self.assertIn('margin:4px 0 22px',css)
        self.assertIn("watchalongPastSearch?.addEventListener('keydown'",js)
        self.assertIn("if(event.key!=='Enter')return",js)
        self.assertIn("watchalongPastSearch?.addEventListener('input'",js)
        self.assertIn("fetch('/data/watchalong/manifest.json'",js)
        self.assertIn("href:'/watchalong-viewer/?watchalong_event='",js)

    def test_history_search_accepts_single_dates_unbounded_ranges_and_combined_terms(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')

        self.assertIn('function parseHistoryDateIntent(raw,yearHint=\'\')',js)
        self.assertIn('function parseHistoryCombinedIntent(raw,yearHint=\'\')',js)
        self.assertIn("String(token||'').normalize('NFKC').trim()",js)
        self.assertIn("String(raw||'').normalize('NFKC').trim()",js)
        self.assertIn("return {kind:'range',start,end,span};",js)
        self.assertNotIn("if(span>62)return {kind:'range_too_large',start,end,span};",js)
        self.assertIn('while(cursor<=last){',js)
        self.assertNotIn('months.length<3',js)
        self.assertIn('async function loadYoutubeHistoryRange(start,end)',js)
        self.assertIn("const dateIntent=combinedIntent.dateIntent,searchQuery=combinedIntent.query;",js)
        self.assertIn("const aliasesPromise=searchQuery?loadHistoryMemberAliases():Promise.resolve(null);",js)
        self.assertIn("parsedSearch=parseHistorySearchQuery(searchQuery,aliasRegistry,contentAliasRegistry);",js)
        self.assertIn("if(pureDateIntent?.kind==='day')",js)
        self.assertIn("return loadHistory();",js)
        self.assertIn("dateIntent?.kind==='range'",js)
        self.assertIn('9/10~10/15',html)

    def test_watchalong_landing_uses_history_channel_ids_for_canonical_profiles(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')

        self.assertIn('const watchalongChannelIds=[...new Set(historyRows.map',js)
        self.assertIn('const canonical=await loadCanonicalChannelProfiles(watchalongChannelIds);',js)
        self.assertIn('watchalongPastRows=historyRows.map(row=>historyDisplayRow(row,canonical));',js)
        self.assertIn("const channelId=String(row?.channel_id||'');",js)
        self.assertNotIn('function watchalongChannelByVideo(todayRows,recentEvents)',js)
        self.assertNotIn("api('/v1/watchalong/recent",js)


    def test_watchalong_landing_cards_expose_youtube_without_hijacking_primary_action(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn("youtube.dataset.youtubeHref='https://www.youtube.com/watch?v='+videoId",js)
        self.assertIn("youtube.textContent='YouTube ↗'",js)
        self.assertIn("event.target.closest('[data-youtube-href]')",js)
        self.assertIn("window.open(youtube.dataset.youtubeHref,'_blank','noopener,noreferrer')",js)
        self.assertIn(".watchalong-card-actions{",css)
        self.assertIn(".watchalong-youtube-link{",css)

    def test_watchalong_compact_cards_clamp_text_before_stacking(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn("-webkit-line-clamp:3",css)
        self.assertIn("@media(max-width:1180px){",css)
        self.assertIn("-webkit-line-clamp:2",css)
        self.assertIn("@media(max-width:980px){",css)
        self.assertIn(".watchalong-compact-card{grid-template-columns:1fr}",css)



    def test_viewer_hides_raw_video_ids_but_keeps_human_labels(self):
        js=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')

        self.assertIn("function playerDisplayLabel(stream)",js)
        self.assertIn("if(!label||label===videoId||/^[A-Za-z0-9_-]{11}$/.test(label))return '';",js)
        self.assertIn("node('div',playerDisplayLabel(stream),'player-label')",js)
        self.assertIn("label.textContent=playerDisplayLabel(streams[0])",js)
        self.assertIn("label.textContent=playerDisplayLabel(stream)",js)
        self.assertNotIn("node('div',stream.label,'player-label')",js)



    def test_watchalong_translation_danmaku_uses_slower_readable_pacing(self):
        js=(ROOT/'site/assets/watchalong-standalone.js').read_text(encoding='utf-8')

        self.assertIn("const duration=Math.max(9,Math.min(18,9+text.length*0.09));",js)
        self.assertNotIn("const duration=Math.max(6,Math.min(12,6+text.length*0.06));",js)



    def test_viewer_primary_carousel_geometry_caps_at_visible_slots(self):
        js=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')

        self.assertIn("const geometryCount=effective==='primary'?Math.min(FOCUS_VISIBLE_SLOTS,count):count;",js)
        self.assertIn("stage.className='viewer-stage layout-'+effective+' count-'+Math.max(1,geometryCount);",js)
        self.assertIn("workspace.className='viewer-workspace workspace-sidebar layout-'+effective+' count-'+Math.max(1,geometryCount);",js)
        self.assertIn("Math.max(0,geometryCount-1)",js)



    def test_viewer_carousel_keeps_all_povs_in_rotation_while_showing_four_slots(self):
        js=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')

        # Carousel mode rotates the primary across the full stream list.
        self.assertIn(
            "carouselTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length),ms);",
            js,
        )

        # Focus/lock keeps the primary fixed and rotates only the secondary window.
        self.assertIn(
            "const secondaryCount=Math.max(0,streams.length-1);",
            js,
        )
        self.assertIn(
            "secondaryOffset=(secondaryOffset+Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryCount))%secondaryCount;",
            js,
        )

        # Visible geometry remains bounded at one primary + three secondary POVs.
        self.assertIn("const FOCUS_VISIBLE_SLOTS=4;",js)
        self.assertIn(
            "const geometryCount=effective==='primary'?Math.min(FOCUS_VISIBLE_SLOTS,count):count;",
            js,
        )



    def test_viewer_mobile_primary_layout_restores_sidebar_stage_grid(self):
        css=(ROOT/'site/assets/viewer-standalone.css').read_text(encoding='utf-8')

        self.assertIn(
            ".viewer-workspace.workspace-focus.layout-primary,.viewer-workspace.workspace-sidebar.layout-primary{grid-template-columns:1fr;grid-template-rows:none}",
            css,
        )
        self.assertIn(
            ".viewer-workspace.workspace-focus.layout-primary .viewer-stage,.viewer-workspace.workspace-sidebar.layout-primary .viewer-stage{display:grid}",
            css,
        )
        self.assertIn(
            ".viewer-workspace.workspace-sidebar.layout-primary .viewer-stage .player-card.primary",
            css,
        )
        self.assertIn(
            ".viewer-workspace.workspace-focus.layout-primary .viewer-ptt,.viewer-workspace.workspace-sidebar.layout-primary .viewer-ptt{grid-column:1;grid-row:auto}",
            css,
        )



    def test_home_lifecycle_sections_have_minimal_visual_separation(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn("#home-live-section>.section-head",css)
        self.assertIn("#home-upcoming-section>.section-head",css)
        self.assertIn("#home-upcoming-section{",css)
        self.assertIn("background:color-mix(in srgb,var(--accent-soft) 54%,var(--bg));",css)
        self.assertIn("border:1px solid color-mix(in srgb,var(--accent) 18%,var(--line));",css)
        self.assertIn("#home-upcoming-section::before{",css)
        self.assertNotIn("#home-upcoming-section .section-icon",css)



    def test_home_lifecycle_labels_and_ended_section_hierarchy(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn("<h2>現在直播中</h2><p>LIVE NOW</p>",html)
        self.assertIn("<h2>即將開始</h2><p>UP NEXT</p>",html)
        self.assertIn("<h2>已結束</h2><p>PAST STREAMS</p>",html)
        self.assertIn("#home-ended-section{",css)
        self.assertIn("background:color-mix(in srgb,#e9e4dd 46%,var(--bg));",css)
        self.assertIn("#home-ended-section::before{",css)
        self.assertIn("#home-ended-section>.section-head h2{",css)



    def test_home_highlights_follow_active_home_filter(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')

        self.assertIn("renderHomeHighlights(homeCatalogRows,value);",js)
        self.assertIn("function renderHomeHighlights(rows,filter=homeFilter()){",js)
        self.assertIn("const visibleRows=(filter==='all'?rows:rows.filter",js)
        self.assertIn("const picks=chooseHomeHighlights(visibleRows);",js)
        self.assertNotIn("renderHomeHighlights(rows);\n applyHomeFilter();",js)



    def test_home_stream_cards_have_consistent_base_surface(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn(
            ".stream-card{position:relative;border:1px solid var(--line);background:var(--surface);",
            css,
        )
        self.assertIn(
            ".stream-card[data-support-accent=\"1\"]{background:color-mix(in srgb,var(--member-accent) 4%,var(--surface));",
            css,
        )
        self.assertNotIn(
            ".stream-card{position:relative;border:1px solid transparent;background:transparent;",
            css,
        )



    def test_home_time_hub_v1_is_custom_and_frontend_only(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertIn('id="timeHub"',html)
        self.assertIn('id="timeHubGrid"',html)
        self.assertIn('aria-controls="timeHub"',html)
        self.assertIn("const TIME_HUB_MEMBERS=",js)
        self.assertIn("function renderTimeHub()",js)
        self.assertNotIn("function timeHubStreamsForDay(day)",js)
        self.assertIn("$('timeHub').showModal()",js)
        self.assertIn(".time-hub-grid{",css)
        self.assertIn(".time-hub-agenda{",css)
        self.assertNotIn('type="date"',html[html.index('id="timeHub"'):html.index('id="connection"')])



    def test_ptt_midnight_rollover_keeps_previous_tail_at_1000_rows(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')

        self.assertNotIn("if(pttLastGoodDay&&pttLastGoodDay!==today)",js)
        self.assertIn("pttCarryLoadedFor!==today",js)
        self.assertIn("const previous=shiftDay(today,-1)",js)
        self.assertIn("/v1/ptt/history?day='+encodeURIComponent(day)+'&limit='+PTT_HISTORY_PAGE_LIMIT",js)
        self.assertIn("data.page.next_checkpoint",js)
        self.assertIn("PTT_HISTORY_PAGE_CAP=100",js)
        self.assertIn("PTT_CARRY_CACHE_KEY='holoviewer-ptt-carry-v1'",js)
        self.assertIn("sessionStorage.setItem(PTT_CARRY_CACHE_KEY",js)
        self.assertIn("carryRows=await loadPttHistoryTail(previous)",js)
        self.assertNotIn("/v1/ptt/today?day='+encodeURIComponent(previous)+'&limit=1000",js)
        self.assertIn("/v1/ptt/today?day='+encodeURIComponent(today)+'&limit=1000",js)
        self.assertIn("const rows=[...carryRows,...todayRows]",js)
        self.assertIn("}).slice(-1000)",js)
        self.assertIn("while(list.children.length>1000)",js)



    def test_ptt_reload_carry_uses_history_tail_not_yesterday_today_endpoint(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')

        self.assertIn("async function loadPttHistoryTail(day)",js)
        self.assertIn("PTT_HISTORY_PAGE_LIMIT=200",js)
        self.assertIn("PTT_HISTORY_PAGE_CAP=100",js)
        self.assertIn("/v1/ptt/history?day='+encodeURIComponent(day)+'&limit='+PTT_HISTORY_PAGE_LIMIT",js)
        self.assertIn("data.page.next_checkpoint",js)
        self.assertIn("tail.length>1000",js)
        self.assertIn("writePttCarryCache(day,tail)",js)
        self.assertIn("carryRows=await loadPttHistoryTail(previous)",js)
        self.assertNotIn("encodeURIComponent(previous)+'&limit=1000",js)



    def test_time_hub_v2_uses_stable_channel_identity_without_stream_schedule(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')

        self.assertNotIn('LIVE SCHEDULE',html)
        self.assertNotIn('id="timeHubStreams"',html)
        self.assertNotIn('<i class="stream"></i>STREAM',html)
        self.assertNotIn('timeHubStreamsForDay',js)
        self.assertIn("function timeHubProfileRow(channelId)",js)
        self.assertIn("row?.channel_id",js)
        self.assertIn("function timeHubAvatar(event)",js)
        self.assertIn("wrap.dataset.channelId",js)
        self.assertIn("UC1DCedRgGHBdm81E1llLhOQ|兎田ぺこら",js)
        self.assertIn("UCt9H_RpQzhxzlyBxFqrdHqA|Fuwawa Abyssgard",js)
        self.assertIn("UCt9H_RpQzhxzlyBxFqrdHqA|Mococo Abyssgard",js)
        hub=js[js.index('// Time Hub V2 static event registry.'):js.index('function updateClientTopbar(routeName){')]
        self.assertNotIn('.includes(key)',hub)
        self.assertNotIn('key.includes(',hub)
        self.assertIn('.time-hub-avatar.is-birthday',css)
        self.assertIn('.time-hub-avatar.is-anniversary',css)

    def test_time_hub_trigger_preserves_existing_top_status_typography(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertIn('.top-status{margin-left:auto;color:#856C86;font-size:13px;font-weight:800;letter-spacing:.065em;background:transparent;border:0;border-radius:0;padding:6px 0}',css)
        trigger=css[css.index('.top-date-trigger{'):css.index('.time-hub{')]
        self.assertNotIn('padding:6px 8px',trigger)
        self.assertNotIn('border-radius:9px',trigger)
        self.assertNotIn('font:inherit',trigger)



    def test_public_home_and_sections_use_clean_canonical_paths(self):
        html=(ROOT/'site/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')

        self.assertIn('data-route="home" href="/"',html)
        self.assertIn('data-route="history" href="/history"',html)
        self.assertIn('data-route="watchalong" href="/watchalong"',html)
        self.assertIn('data-route="single" href="/custom-view"',html)
        self.assertIn('data-route="multi" href="/collab"',html)
        self.assertIn("home:'/',history:'/history',single:'/custom-view',multi:'/collab'",js)
        self.assertIn("watchalong:'/watchalong',ptt:'/ptt-today'",js)
        self.assertIn("history.replaceState(null,'',sessionUrl)",js)
        self.assertIn("const legacyHashRoute=['home','history','single','multi','watchalong']",js)
        self.assertIn("location.pathname==='/'?'home':''",js)
        self.assertNotIn(":'#'+r;",js)



    def test_time_hub_identity_registry_uses_verified_channel_mapping(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        expected=[
            ("UCjLEmnpCNeisMxy134KPwWw","Kobo Kanaeru"),
            ("UCYz_5n-uDuChHtLo7My1HnQ","Kureiji Ollie"),
            ("UCOyYb1c43VlX9rc_lT6NKQw","Ayunda Risu"),
            ("UCP0BspO_AMEe3aQqqpo89Dg","Moona Hoshinova"),
            ("UCAoy6rzhSf4ydcYjJw3WoVg","Airani Iofifteen"),
            ("UCWQtYtq9EOB4-I5P-3fh8lA","音乃瀬奏"),
            ("UCtyWhCj3AqKh2dXctLkDtng","一条莉々華"),
            ("UCdXAk5MpyLD8594lm_OvtGQ","儒烏風亭らでん"),
            ("UC1iA6_NT4mtAcIII6ygrvCw","轟はじめ"),
            ("UC9LSiN9hXI55svYEBrrK-tw","響咲リオナ"),
            ("UCGzTVXqMQHa4AgJVJIVvtDQ","綺々羅々ヴィヴィ"),
            ("UCjk2nKmHzgH5Xy-C5qYRd5A","水宮枢"),
            ("UCKMWFR6lAstLa7Vbf5dH7ig","輪堂千速"),
            ("UCuI_opAVX6qbxZY-a-AxFuQ","虎金妃笑虎"),
        ]
        for channel_id,name in expected:
            self.assertIn(channel_id+"|"+name+"|",js)
        self.assertNotIn("UCjLEmnpCNeisMxy134KPwWw|綺々羅々ヴィヴィ|",js)
        self.assertNotIn("UCjLEmnpCNeisMxy134KPwWw|Kikirara Vivi|",js)

    def test_time_hub_rwd_avatar_layout_is_independent_from_day_number(self):
        css=(ROOT/'site/assets/app.css').read_text(encoding='utf-8')
        self.assertIn(".time-hub-day-number{position:absolute",css)
        self.assertIn(".time-hub-day-people{position:absolute",css)
        self.assertIn("width:42px;height:42px",css)
        self.assertIn("grid-template-rows:repeat(6,72px)",css)
        self.assertIn(".time-hub-avatar{width:34px;height:34px",css)
        self.assertIn('content:"B"',css)
        self.assertIn('content:"★"',css)
        self.assertIn(".time-hub-special .time-hub-avatar{width:50px;height:50px}",css)
        self.assertIn(".time-hub-special-copy strong{font-size:15px",css)



    def test_time_hub_locale_name_policy_jp_dev_is_japanese_en_id_english(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        # JP / DEV_IS: Japanese display names.
        for value in (
            "UC1DCedRgGHBdm81E1llLhOQ|兎田ぺこら|",
            "UCWQtYtq9EOB4-I5P-3fh8lA|音乃瀬奏|",
            "UCGzTVXqMQHa4AgJVJIVvtDQ|綺々羅々ヴィヴィ|",
        ):
            self.assertIn(value,js)
        # ID / EN: English display names.
        for value in (
            "UCjLEmnpCNeisMxy134KPwWw|Kobo Kanaeru|",
            "UCYz_5n-uDuChHtLo7My1HnQ|Kureiji Ollie|",
            "UCL_qhgtOy0dy1Agp8vkySQg|Mori Calliope|",
        ):
            self.assertIn(value,js)
        self.assertNotIn("UCjLEmnpCNeisMxy134KPwWw|こぼ・かなえる|",js)



    def test_watchalong_subtitle_and_danmaku_default_on_but_preserve_user_choice(self):
        html=(ROOT/'site/watchalong-viewer/index.html').read_text(encoding='utf-8')
        js=(ROOT/'site/assets/watchalong-standalone.js').read_text(encoding='utf-8')
        self.assertIn("let subtitleEnabled=true;",js)
        self.assertIn("let danmakuEnabled=true;",js)
        self.assertIn("localStorage.getItem('holoviewer-watchalong-subtitle-standard')",js)
        self.assertIn("localStorage.getItem('holoviewer-watchalong-subtitle-danmaku')",js)
        self.assertIn('data-subtitle-mode="standard" class="active" aria-pressed="true"',html)
        self.assertIn('data-subtitle-mode="danmaku" class="active" aria-pressed="true"',html)

    def test_watchalong_intermediate_width_keeps_toolbar_legible_before_mobile_stack(self):
        css=(ROOT/'site/assets/watchalong-standalone.css').read_text(encoding='utf-8')
        self.assertIn("white-space:nowrap;flex:0 0 auto",css)
        self.assertIn("@media(max-width:1180px){",css)
        self.assertIn(".segment-controls,.resume-status{display:none}",css)
        self.assertIn("@media(max-width:900px){",css)
        self.assertIn(".sync-controls{display:none}",css)
        self.assertIn("@media(max-width:820px){",css)
        self.assertIn(".control-toggle span:last-child{display:none}",css)
        self.assertIn("@media(max-width:760px){",css)
        self.assertNotIn("@media(max-width:980px){\n .sync-controls,.subtitle-mode-controls{display:none}",css)



if __name__ == "__main__":
    unittest.main()
