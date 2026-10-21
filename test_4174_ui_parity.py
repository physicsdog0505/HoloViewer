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

    def test_history_cards_reuse_home_display_metadata_and_actual_start(self):
        js=(ROOT/'site/assets/app.js').read_text(encoding='utf-8')
        self.assertIn("item?.start_at||item?.actual_start||item?.scheduled_start",js)
        self.assertIn("'yt3.googleusercontent.com'",js)
        self.assertIn('function homeDisplayMetadataByChannel(rows)',js)
        self.assertIn('function historyDisplayRow(item,byChannel)',js)
        self.assertIn("avatar_url:item.avatar_url||profile.avatar_url||''",js)
        self.assertIn("member_accent:item.member_accent||profile.member_accent||''",js)
        self.assertIn("support_mode:item.support_mode||profile.support_mode||''",js)
        start=js.index('async function loadHistory(){')
        end=js.index('function collabEventState(event){',start)
        history=js[start:end]
        self.assertIn("api('/v1/catalog/today').catch(()=>null)",history)
        self.assertIn("historyDisplayRow({...item,lifecycle_state:'ended'},displayByChannel)",history)
        # Display fallback is metadata-only; lifecycle still comes from /v1/history.
        self.assertNotIn("scheduled_start",history.split("historyDisplayRow",1)[0].split("lifecycle_state",1)[-1])

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
        self.assertIn("api('/v1/collab/history?day='+encodeURIComponent(day)+'&limit=100&offset=0')", js)
        self.assertIn("const historyCollabByVideo=collabData?collabEventMap(collabData,day):new Map()", js)
        self.assertIn("const endedItems=data.items.map(item=>historyDisplayRow({...item,lifecycle_state:'ended'},displayByChannel))", js)
        self.assertIn("endedItems.forEach(item=>homeCard(item,list,{collabMap:historyCollabByVideo,history:true}))", js)
        self.assertIn("if(!history)overlay.append(node('span',status[0],'thumb-badge '+status[1]))", js)
        self.assertIn("if(history&&String(item.lifecycle_state||item.state||'').toLowerCase()!=='ended')return", js)
        self.assertNotIn('id="history-prev"', html)
        self.assertNotIn('id="history-next"', html)

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
        self.assertIn("pttLastGoodDay&&pttLastGoodDay!==today", js)
        self.assertIn("60 秒後重試", js)
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
        self.assertIn("const sameDayWindow=verifiedSameDayVodWindow(row)",viewer)
        self.assertIn("const archiveWindow=verifiedEndedVodWindow(row)",viewer)
        self.assertIn("archiveWindows.set(id,cached)",viewer)
        self.assertIn("await loadSameDayVodPtt(pttContext,token)",viewer)
        self.assertIn("await loadArchivePtt(pttContext,token)",viewer)
        self.assertIn("const resolvedPttMode=pttContext.mode==='live'?'live':(['archive','same-day'].includes(pttContext.mode)?'video':requestedPttMode)",viewer)
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
        self.assertIn("static-assets-full-2026-08.json",config)
        self.assertIn("static-assets-full-2026-09.json",config)
        self.assertIn("static-assets-full-2026-10.json",config)
        self.assertIn("params.getAll('ptt_window')",viewer)
        self.assertIn("anchorSource!==PTT_ARCHIVE_ANCHOR",viewer)
        self.assertIn("archiveHourKeys(startMs,endMs)",viewer)
        self.assertIn("const objects=new Map(archive.manifest.objects.map(item=>[item.key,item]));",viewer)
        self.assertIn("crypto.subtle.digest('SHA-256',buffer)",viewer)
        self.assertIn("payload.pushes.length!==item.pushes",viewer)
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("archiveSourcesForWindow(fetchStartMs,endMs)",viewer)
        self.assertIn("occurred>=fetchStartMs&&occurred<endMs",viewer)
        self.assertIn("row?.source_record_key||row?.push_id",viewer)
        self.assertIn("Number.isInteger(row?.floor)&&row.floor>0",viewer)
        self.assertIn("資料可能不完整",viewer)
        self.assertNotIn("/v1/ptt/history?day=",viewer)
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
        self.assertIn("function verifiedSameDayVodWindow(row)",viewer)
        self.assertIn("lifecycle!=='ended'",viewer)
        self.assertIn("function verifiedEndedVodWindow(row)",viewer)
        self.assertIn("if(taipeiDayForDate(window.start)!==today||taipeiDayForDate(new Date(endMs-1))!==today)return null",viewer)
        self.assertIn("taipeiDayForDate(new Date(endMs-1))!==today",viewer)
        self.assertIn("async function loadTodayPttPayload(day)",viewer)
        self.assertIn("&limit=1000",viewer)
        self.assertIn("async function loadSameDayVodPtt(context,token)",viewer)
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("occurred>=fetchStartMs&&occurred<endMs",viewer)
        self.assertIn("[window.videoId,window.start,window.end,window.anchorSource,window.scheduledStart||'']",viewer)
        self.assertIn("今日暫存 · 對齊播放時間 · ⚠ 尚未封存，不宣稱完整",viewer)
        self.assertIn("mode:'same-day'",viewer)


    def test_historical_ptt_month_registry_and_cross_month_plan(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        config=(ROOT/'site/assets/config.js').read_text(encoding='utf-8')
        start=viewer.index("function nextIsoDay(day){")
        end=viewer.index("async function archiveSha256Hex(buffer){",start)
        helpers=viewer[start:end]
        row_start=viewer.index("function archiveRowIdentity(row){")
        row_end=viewer.index("async function resolveArchiveRows(context,archives){",row_start)
        row_helpers=viewer[row_start:row_end]
        visible_start=viewer.index("function vodPttVisibleCountAt(rows,absoluteMs){")
        visible_end=viewer.index("function setVodPttRows(rows){",visible_start)
        visible_helper=viewer[visible_start:visible_end]
        registry="""{
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
VISIBLE_HELPER
const aug=archiveSourcesForWindow(Date.parse('2026-08-15T00:00:00Z'),Date.parse('2026-08-15T01:00:00Z'));
const sep=archiveSourcesForWindow(Date.parse('2026-09-18T11:00:25Z'),Date.parse('2026-09-18T16:13:34Z'));
const oct=archiveSourcesForWindow(Date.parse('2026-10-18T00:00:00Z'),Date.parse('2026-10-18T01:00:00Z'));
const cross=archiveSourcesForWindow(Date.parse('2026-09-30T15:59:00Z'),Date.parse('2026-09-30T16:01:00Z'));
const keys=archiveHourKeys(Date.parse('2026-09-18T11:00:25Z'),Date.parse('2026-09-18T16:13:34Z'));
const manifest={objects:keys.map(key=>({key}))};
const plan=archiveChunkPlan([{source:sep[0],manifest}],Date.parse('2026-09-18T11:00:25Z'),Date.parse('2026-09-18T16:13:34Z'));
const rows=Array.from({length:2019},(_,i)=>({
 source_record_key:'J33JnrVJiIQ:'+i,
 occurred_at:new Date(Date.parse('2026-09-18T11:00:25Z')+i*9000).toISOString(),
 aid:'J33JnrVJiIQ',source_line:247+i,floor:i+1
}));
rows.push({...rows[1000]});
const deduped=dedupeArchiveRows(rows);
const visible=vodPttVisibleCountAt(deduped,Date.parse('2026-09-18T16:13:34Z'));
process.stdout.write(JSON.stringify({aug,sep,oct,cross,keys,plan:plan.map(x=>x.source.base+'/'+x.item.key),deduped:deduped.length,visible}));
""".replace("REGISTRY",registry).replace("ROW_HELPERS",row_helpers).replace("VISIBLE_HELPER",visible_helper).replace("HELPERS",helpers)
        result=subprocess.run(["node","-e",script],check=True,capture_output=True,text=True)
        payload=json.loads(result.stdout)
        self.assertEqual(payload["aug"][0]["month"],"2026-08")
        self.assertIn("full-offline",payload["aug"][0]["base"])
        self.assertEqual(payload["sep"][0]["month"],"2026-09")
        self.assertIn("static-assets-pilot",payload["sep"][0]["base"])
        self.assertEqual(payload["oct"][0]["month"],"2026-10")
        self.assertIn("full-offline",payload["oct"][0]["base"])
        self.assertEqual([x["month"] for x in payload["cross"]],["2026-09","2026-10"])
        self.assertEqual(payload["keys"],[
            "ptt/v1/chunks/2026/09/18/1100.json",
            "ptt/v1/chunks/2026/09/18/1200.json",
            "ptt/v1/chunks/2026/09/18/1300.json",
            "ptt/v1/chunks/2026/09/18/1400.json",
            "ptt/v1/chunks/2026/09/18/1500.json",
            "ptt/v1/chunks/2026/09/18/1600.json",
        ])
        self.assertEqual(len(payload["plan"]),6)
        self.assertTrue(all("static-assets-pilot.singlebagel.workers.dev" in url for url in payload["plan"]))
        self.assertEqual(payload["deduped"],2019)
        self.assertEqual(payload["visible"],2019)
        self.assertIn('"2026-09": Object.freeze({',config)

        # Archive reads must preserve the existing VOD pre-roll contract:
        # scheduled/actual anchor minus one hour, while coverage remains actual-window only.
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs",viewer)
        self.assertIn("archiveChunkPlan(archives,fetchStartMs,endMs)",viewer)
        self.assertIn("occurred>=fetchStartMs&&occurred<endMs",viewer)
        self.assertIn("archiveCoverageStatus(archive.manifest,startMs,endMs,archive.source.month)",viewer)

        pre_start=Date.parse("2026-10-01T00:00:25+08:00")
        pre_fetch=pre_start-3600000
        pre_script=helpers+"\nconst PTT_ARCHIVE_MONTHS="+registry+";function archiveUnavailableError(message){const error=new Error(message);error.archiveUnavailable=true;return error;}process.stdout.write(JSON.stringify(archiveSourcesForWindow("+str(pre_fetch)+","+str(pre_start+60000)+")));"
        pre_result=subprocess.run(["node","-e",pre_script],check=True,capture_output=True,text=True)
        pre_payload=json.loads(pre_result.stdout)
        self.assertEqual([x["month"] for x in pre_payload],["2026-09","2026-10"])

    def test_historical_ptt_manifest_failure_is_unavailable_not_empty(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        self.assertIn("throw archiveUnavailableError('歷史 PTT '+source.month+' manifest HTTP '+response.status+'：'+url);",viewer)
        self.assertIn("pttMeta.textContent='歷史 Static Assets · UNKNOWN / UNAVAILABLE';",viewer)
        self.assertIn("'歷史 PTT UNKNOWN / UNAVAILABLE：'+detail",viewer)
        load=viewer.split("async function loadArchivePtt(context,token){",1)[1].split("async function resolvePrimaryPtt()",1)[0]
        self.assertIn("result.coverageStatus==='COMPLETE'?'這段 VOD 時間範圍內沒有 PTT 推文。'",load)
        self.assertNotIn("UNKNOWN / UNAVAILABLE：'+detail,'ptt-empty'));\n  startVodPttTimeline()",load)

    def test_historical_ptt_archive_path_is_read_only(self):
        viewer=(ROOT/'site/assets/viewer-standalone.js').read_text(encoding='utf-8')
        archive=viewer.split("const archiveManifestCache=new Map();",1)[1].split("async function resolvePrimaryPtt()",1)[0]
        for verb in ("method:'POST'","method:'PUT'","method:'PATCH'","method:'DELETE'","INSERT ","UPDATE ","DELETE FROM","wrangler","D1","R2"):
            self.assertNotIn(verb,archive)
        self.assertIn("credentials:'omit'",archive)
        self.assertIn("cache:'no-cache'",archive)

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
        choose_end=js.index('function renderHomeHighlights(rows){',rules_start)
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
        self.assertIn("'#custom-session?'+new URLSearchParams([",js)
        self.assertIn("...viewing.ids.map(id=>['stream',id])",js)
        self.assertIn("params.getAll('stream')",js)
        self.assertIn("const recovered=urls.length?ids:",js)
        self.assertIn("const hashRoute=location.hash.substring(1).split('?')[0];",js)
        self.assertIn("const pathRoute=location.pathname==='/history'?'history':",js)
        self.assertIn("route(hashRoute||pathRoute||'home')",js)

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
        self.assertIn("scheduledStart:archiveWindow.scheduledStart||''",viewer)
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
        self.assertIn("function vodPttVisibleCountAt(rows,absoluteMs)",viewer)
        self.assertIn("function syncVodPttTimeline({forceFollow=false}={})",viewer)
        helper_start=viewer.index("function vodPttVisibleCountAt(rows,absoluteMs){")
        helper_end=viewer.index("function setVodPttRows(rows){",helper_start)
        helper=viewer[helper_start:helper_end]
        script=helper+"\nconst rows=[{occurred_at:'2026-10-18T08:14:59Z'},{occurred_at:'2026-10-18T08:15:00Z'},{occurred_at:'2026-10-18T08:15:01Z'}];process.stdout.write(String(vodPttVisibleCountAt(rows,Date.parse('2026-10-18T08:15:00Z'))));"
        result=subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
        self.assertEqual(result.stdout,'2')
        self.assertIn("if(visible>pttVodVisibleCount)",viewer)
        self.assertIn("pttFeed.replaceChildren(...pttVodRows.slice(0,visible).map(pttRow))",viewer)
        self.assertIn("currentSeconds<pttVodLastSample.seconds-.75",viewer)
        self.assertIn("Math.abs(currentSeconds-expected)>2.5",viewer)
        self.assertIn("setInterval(()=>syncVodPttTimeline(),500)",viewer)
        self.assertIn("syncVodPttTimeline({forceFollow:true})",viewer)
        self.assertIn("最新 · '+clock",viewer)
        self.assertIn("對齊播放時間",viewer)
        self.assertNotIn("pttFeed.scrollTop=0;\n  pttMeta.textContent=context.day",viewer)

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
        self.assertIn("workspace.className='viewer-workspace workspace-sidebar layout-'+effective+' count-'+streams.length;", js)
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
        self.assertIn("if(primaryChanged)resolvePrimaryPtt();", js)
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


if __name__ == "__main__":
    unittest.main()
