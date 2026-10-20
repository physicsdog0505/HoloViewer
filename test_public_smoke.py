"""Public-only smoke release safety checks; no external credentials required."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import tempfile
import unittest

from public_snapshot import load_snapshot

ROOT = Path(__file__).resolve().parent
EXPECTED = {"app.py", "public_snapshot.py", "requirements.txt", "REFERENCES.md", "README.md", "test_public_smoke.py", ".github/workflows/public-smoke-ci.yml", ".github/workflows/deploy-cloudflare-production.yml", "cloudflare/wrangler.json", "cloudflare/DEPLOY.md", "site/index.html", "site/assets/app.js", "site/assets/app.css", "site/assets/viewer-4174.css", "site/assets/config.js", "site/assets/shared-shell.css", "site/assets/viewer-standalone.css", "site/assets/viewer-standalone.js", "site/viewer/index.html", "site/ptt-today/index.html", "site/assets/ptt-today.css", "site/assets/ptt-today.js", "site/assets/4174-shared-viewing-a144bb3.css", "site/assets/4174-shared-viewing-a144bb3.js", "site/assets/4174-shared-viewing-a144bb3-dom.js", "site/_headers", "AGENTS.md", "HOLOVIEWER_PROJECT_GUIDELINES.md", "docs/PROJECT_STATUS.md", "docs/HANDOFF_TEMPLATE.md", "docs/handoffs/COORDINATION_REVIEW_WINDOW_20261009.md", "docs/4174_UI_PARITY_CONTRACT.md", "docs/handoffs/UI_PARITY_CHECKPOINT_20261015.md", "docs/PUBLIC_LOCAL_ACCEPTANCE.md", "scripts/check_public_local.sh", "scripts/start_public_local.sh", "scripts/public_browser_lifecycle.mjs", "test_4174_ui_parity.py", ".gitignore", "vendor/4174-a144bb3/shared_viewing_core.py", "vendor/4174-a144bb3/client_custom_view.py", "vendor/4174-a144bb3/client_ui_shell.py", "vendor/4174-a144bb3/client_app.py", "site/data/watchalong/manifest.json", "site/data/watchalong/events/eFYByyw5AJc.json", "site/data/watchalong/events/U2o13h1Oib4.json", "site/data/watchalong/events/8pF4qHcshDc.json", "scripts/export_watchalong_assets.py", "test_watchalong_assets.py", "docs/handoffs/WATCHALONG_PUBLIC_ASSET_HANDOFF_20261020.md"}

class PublicSmokeTests(unittest.TestCase):
    def test_repository_file_allowlist(self):
        present = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
                   if p.is_file() and ".git" not in p.parts and ".wrangler" not in p.parts
                   and "__pycache__" not in p.parts and not p.name.endswith(".pyc")}
        self.assertEqual(present, EXPECTED)

    def test_import_boundary_and_disabled_features(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        imports = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports += [a.name for a in n.names]
            if isinstance(n, ast.ImportFrom):
                imports.append(n.module or "")
        self.assertEqual(imports, ["__future__", "pathlib", "streamlit", "public_snapshot"])
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        for bad in ("BackfillJobQueue", "sqlite3", "subprocess", "requests", "Gemini",
                    "st.navigation", "st.Page", "playVideo", "st.video"):
            self.assertNotIn(bad, source)


    def test_static_deploy_security_boundary(self):
        config = json.loads((ROOT / "cloudflare/wrangler.json").read_text())
        self.assertEqual(set(config), {"name", "compatibility_date", "assets"})
        self.assertEqual(config["name"], "holoviewer-public")
        self.assertEqual(config["assets"], {"directory": "../site", "not_found_handling": "single-page-application"})
        self.assertNotIn("main", config)
        js = (ROOT / "site/assets/app.js").read_text()
        for token in ("setTimeout(", "location.reload(", "eval(", "innerHTML", "document.write("):
            self.assertNotIn(token, js)
        self.assertEqual(js.count("setInterval("), 2)
        self.assertIn("},30000);", js)
        self.assertIn("},10000);", js)
        self.assertIn("credentials:'omit'", js)
        self.assertIn("async function loadHomeCollab()", js)
        self.assertIn("function homeLifecycleBucket(item)", js)
        self.assertIn("if(lifecycle==='live')return item?.stale===true?'unknown':'live';", js)
        self.assertIn("if(lifecycle==='upcoming'||lifecycle==='waiting')return 'upcoming';", js)
        self.assertIn("if(lifecycle==='ended')return 'ended';", js)
        self.assertIn("function homeBuckets(rows)", js)
        self.assertIn("buckets[homeLifecycleBucket(item)].push(item);", js)
        self.assertNotIn("state==='ended'?'ended':'unknown'", js)
        self.assertIn("const customHistoryCache=new Map();", js)
        self.assertIn("function customHistoryBounds()", js)
        self.assertIn("return {earliest:shiftDay(today,-30),latest:today};", js)
        self.assertIn("function customHistoryDateValid(day)", js)
        self.assertIn("if(selected===taipeiDay())", js)
        self.assertIn("rows=homeBuckets(customCatalogCache).ended;", js)
        self.assertIn("async function loadCustomHistory(day)", js)
        self.assertIn("api('/v1/history?day='+encodeURIComponent(selected)+'&limit=50&offset=0')", js)
        self.assertIn("const liveRows=homeBuckets(Array.isArray(rows)?rows:[]).live;", js)
        self.assertIn("window.hvCustomHistory=function(rows,day)", js)
        self.assertIn("bindCustomPicker(document.getElementById('custom-history-picker'))", js)
        self.assertIn('id="customHistoryDate"', (ROOT / "site/index.html").read_text())
        self.assertIn('id="custom-history-picker"', (ROOT / "site/index.html").read_text())
        self.assertIn("const HOME_CATALOG_CACHE_KEY='holoviewer-home-catalog-v1';", js)
        self.assertIn("function readHomeCatalogCache()", js)
        self.assertIn("function writeHomeCatalogCache(rows)", js)
        self.assertIn("function renderHomeRows(rows)", js)
        self.assertIn("if(cachedRows.length)renderHomeRows(cachedRows);", js)
        self.assertIn("writeHomeCatalogCache(rows);", js)
        self.assertIn("document.documentElement.classList.add('home-hydrated')", js)
        self.assertIn('class="home-preboot"', (ROOT / "site/index.html").read_text())
        self.assertIn("html.home-preboot:not(.home-hydrated) #homeDynamic{visibility:hidden}", (ROOT / "site/assets/app.css").read_text())
        self.assertIn("function homeStartTimestamp(item)", js)
        self.assertIn("function homeEndTimestamp(item)", js)
        self.assertIn("buckets.live.sort(chronological)", js)
        self.assertIn("buckets.upcoming.sort(chronological)", js)
        self.assertIn("buckets.unknown.sort(chronological)", js)
        self.assertIn("buckets.ended.sort((a,b)=>", js)
        self.assertIn("const aVerified=ae!==null,bVerified=be!==null", js)
        self.assertIn("if(aVerified!==bVerified)return aVerified?-1:1", js)
        self.assertIn("const data=await api('/v1/catalog/today');", js)
        # Home must render Today before optional Collab enrichment; History may
        # fetch its date-scoped archive and Collab metadata in parallel.
        home_start = js.index("async function loadHome(){")
        home_end = js.index("function taipeiDay()", home_start)
        home_source = js[home_start:home_end]
        self.assertNotIn("Promise.all", home_source)
        self.assertIn("renderHomeRows(rows);", home_source)
        self.assertIn("loadHomeCollab();", home_source)
        self.assertLess(home_source.index("renderHomeRows(rows);"), home_source.index("loadHomeCollab();"))
        self.assertIn("const [data,collabData,catalogData]=await Promise.all([historyPromise,collabPromise,catalogPromise]);", js)
        self.assertIn('rel="preconnect" href="https://holoviewer-public-api.singlebagel.workers.dev"', (ROOT / "site/index.html").read_text())
        self.assertIn("textContent=", js)
        frontend_config = (ROOT / "site/assets/config.js").read_text()
        self.assertIn("https://holoviewer-public-api.singlebagel.workers.dev", frontend_config)
        self.assertIn("https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev", frontend_config)
        self.assertIn("/ptt/v1/manifests/static-assets-full-2026-10.json", frontend_config)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", frontend_config)

    def test_standalone_viewer_mode_contract(self):
        html = (ROOT / "site/viewer/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/viewer-standalone.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/viewer-standalone.css").read_text(encoding="utf-8")
        app = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        for label in (">預設<", ">輪播<"):
            self.assertIn(label, html)
        for old in (">鎖定<", ">平均<", ">主視角<", ">直播優先<"):
            self.assertNotIn(old, html)
        self.assertNotIn('id="viewerModeStatus"', html)
        self.assertIn('id="focusCarouselStatus"', html)
        self.assertIn("focusCarouselStatus.hidden=!carouselVisible;", js)
        self.assertIn("currentLayoutPreset()===\'focus\'?\'鎖定\'", js)
        self.assertIn(".focus-carousel-status[hidden]{display:none}", css)
        self.assertIn("const MAX_STREAMS=16;", js)
        self.assertIn("const FOCUS_VISIBLE_SLOTS=4;", js)
        self.assertIn("const HOME_FILTER_KEY='holoviewer-live-filter';", js)
        self.assertIn("const HOME_FILTERS=new Set(['hololive','holostars','mekpark','all']);", js)
        self.assertIn("function homeLiveFilter()", js)
        self.assertIn("if(filter!=='all'&&catalogGroup(row)!==filter)return false;", js)
        self.assertIn("if(event.key===HOME_FILTER_KEY)renderLiveRail(catalogRows)", js)
        self.assertIn("carousel.checked=currentLayoutPreset()!=='equal';", js)
        self.assertIn("secondaryOffset=(secondaryOffset+Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryCount))%secondaryCount;", js)
        self.assertNotIn("viewerModeStatus", js)
        self.assertIn("button.dataset.layoutPreset===\'primary\'&&preset===\'focus\'", js)
        self.assertIn("function handleFocusAvatarClick(index)", js)
        self.assertIn("currentLayoutPreset()==='focus'&&lockedIndex===index", js)
        self.assertIn("setLayoutPreset('primary');", js)
        self.assertIn("setLayoutPreset('focus');", js)
        self.assertIn("button.addEventListener('click',()=>handleFocusAvatarClick(index));", js)
        self.assertIn(".player-card.viewer-hidden{display:none!important}", css)
        self.assertIn(".viewer-workspace.workspace-focus.layout-primary,.viewer-workspace.workspace-sidebar.layout-primary{", css)
        self.assertIn(".viewer-workspace.workspace-focus.layout-primary .viewer-stage,.viewer-workspace.workspace-sidebar.layout-primary .viewer-stage{display:contents}", css)
        self.assertIn(".transport-button.is-feedback", css)
        self.assertIn("location.href='/viewer/?'+q.toString();", app)
        self.assertIn("function openStandaloneViewer(ids,options={})", app)
        self.assertIn("function collabEventMap(data,historyDay='')", app)
        self.assertIn("collabEventMap(collabData,day)", app)
        self.assertIn("history:true", app)
        self.assertIn("function customLibraryFilter(){return homeFilter()}", app)
        self.assertIn("data-custom-filter=\"mekpark\"", (ROOT / "site/index.html").read_text())
        self.assertIn("function openStandaloneCollab(event)", app)
        self.assertIn("q.set('collab_event',String(event.event_id||''));", app)
        self.assertIn("q.set('collab_kind',isLive?'live':'vod');", app)
        self.assertIn("q.set('collab_day',collabDay);", app)
        self.assertIn("api('/v1/collab/history?day='+encodeURIComponent(selected)+'&limit=50&offset=0')", app)
        self.assertIn('id="collabHistoryDate"', (ROOT / "site/index.html").read_text())
        self.assertIn('id="collab-history"', (ROOT / "site/index.html").read_text())
        self.assertIn("const collabDay=/^\\d{4}-\\d{2}-\\d{2}$/.test", js)
        self.assertIn("(collabDay?'?day='+encodeURIComponent(collabDay):'')", js)
        self.assertNotIn("entry.setAttribute('aria-disabled','true')", app)
        self.assertIn("openStandaloneCollab(event)", app)
        self.assertIn("const collabEventId=String(params.get('collab_event')||'');", js)
        self.assertIn("async function reconcileLiveCollab()", js)
        self.assertIn("collabState(row)==='live'", js)
        self.assertIn("function reconcileVodCollab()", js)
        self.assertIn("event?.sync?.available===true", js)
        self.assertIn("absoluteMs>=start&&absoluteMs<end", js)
        self.assertIn("player.seekTo(target,true)", js)
        self.assertIn("setInterval(()=>{if(!document.hidden)reconcileLiveCollab()},10000)", js)
        self.assertIn("setInterval(()=>{if(!document.hidden)reconcileVodCollab()},500)", js)
        self.assertIn("const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';", js)
        self.assertIn("const PTT_ARCHIVE_SCHEMA='ptt-r2-archive-v1';", js)
        self.assertIn("async function fetchArchiveManifest(force=false)", js)
        self.assertIn("async function fetchArchiveChunk(item)", js)
        self.assertIn("crypto.subtle.digest('SHA-256',buffer)", js)
        self.assertIn("const fetchStartMs=vodPttFetchStartMs(context)??startMs", js)
        self.assertIn("occurred>=fetchStartMs&&occurred<endMs", js)
        self.assertIn("row?.source_record_key||row?.push_id", js)
        self.assertIn("Number.isInteger(row?.floor)&&row.floor>0", js)
        self.assertNotIn("/v1/ptt/history?day=", js)
        self.assertIn("if(!archiveVodEntry)await loadCatalog();", js)
        self.assertIn("q.set('mode',clean.length>1?'multi':'single');", app)
        self.assertIn("$('multiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openStandaloneViewer(ids)};", app)
        self.assertIn("function standaloneViewerUrl(ids,{vodWindows=null,pttMode=''}={})", app)
        self.assertIn("entry.setAttribute('role','button')", app)
        self.assertIn("開啟多人連動", app)
        self.assertFalse((ROOT / "site/custom-view/index.html").exists())

    def test_standalone_ptt_today_contract(self):
        html = (ROOT / "site/ptt-today/index.html").read_text(encoding="utf-8")
        js = (ROOT / "site/assets/ptt-today.js").read_text(encoding="utf-8")
        css = (ROOT / "site/assets/ptt-today.css").read_text(encoding="utf-8")
        shell = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/assets/shared-shell.css"', html)
        self.assertIn('href="/assets/ptt-today.css"', html)
        self.assertIn('src="/assets/ptt-today.js"', html)
        self.assertIn('href="/ptt-today/" class="active"', html)
        self.assertIn("timeZone:'Asia/Taipei'", js)
        self.assertIn("clientTopbarDate(taipeiDay())", js)
        self.assertIn("/v1/ptt/today?day=", js)
        self.assertIn("&limit=1000", js)
        self.assertIn("&limit=300", js)
        self.assertIn("loadPttTodayPayload(today)", js)
        self.assertIn("[400,413,422]", js)
        self.assertIn("while(list.children.length>1000)", js)
        self.assertIn("Number.isInteger(row.floor)&&row.floor>0", js)
        self.assertIn("floorValue+'樓'", js)
        self.assertIn("push.append(kindEl,timeEl,floorEl,body);", js)
        self.assertIn("grid-template-columns:1.15em 3.15em 3.05em minmax(0,1fr)", css)
        self.assertIn(".ptt-push-floor{color:#929da4;font-size:.76em;font-weight:600", css)
        self.assertIn(".ptt-push-body{min-width:0;overflow-wrap:anywhere;padding-left:1px}", css)
        self.assertIn("body.ptt-floor-hidden .ptt-reader .push{grid-template-columns:1.15em 3.15em minmax(0,1fr)}", css)
        self.assertIn("#ptt-floor-toggle{", css)
        self.assertIn("min-height:40px;padding:0 12px", css)
        self.assertIn("border-radius:12px;border:1px solid var(--line);background:var(--surface)", css)
        self.assertIn("#ptt-floor-toggle input:checked{background:#a65788;border-color:#a65788}", css)
        self.assertIn("pttLastGoodDay&&pttLastGoodDay!==today", js)
        self.assertIn("setInterval(()=>{if(!document.hidden)loadPtt()},10000)", js)
        self.assertIn("body.ptt-focus-mode", css)
        self.assertIn(".ptt-empty[hidden]{display:none!important}", css)
        self.assertIn("html,body{height:100%;overflow:hidden}", css)
        self.assertIn("height:calc(100vh - 58px)", css)
        self.assertIn("position:relative;flex:1 1 auto;min-height:0", css)
        self.assertIn('href="/ptt-today/"', shell)
        self.assertIn('data-route="ptt" href="/ptt-today/"', shell)
        self.assertNotIn('data-page-link="ptt"', shell)
        app = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("if(destination==='ptt')", app)
        self.assertIn("allow", app)

    def test_static_response_content_security_policy(self):
        headers = (ROOT / "site/_headers").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy:", headers)
        for directive in ("default-src 'none'", "script-src 'self'", "connect-src https://holoviewer-public-api.singlebagel.workers.dev", "https://holoviewer-ptt-static-assets-full-offline.singlebagel.workers.dev", "frame-src https://www.youtube-nocookie.com", "frame-ancestors 'none'", "object-src 'none'"):
            self.assertIn(directive, headers)
        self.assertNotIn("'unsafe-inline'", headers)
        self.assertNotIn("'unsafe-eval'", headers)

    def test_manual_deployment_release_gate(self):
        workflow = (ROOT / ".github/workflows/deploy-cloudflare-production.yml").read_text()
        for token in ("workflow_dispatch:", "BASELINE-CHECKED", "release_sha", "git rev-parse HEAD", "cloudflare-production", "refs/heads/main", "persist-credentials: false"):
            self.assertIn(token, workflow)
        self.assertNotIn("  push:", workflow)
        self.assertNotIn("github.event_name == 'push'", workflow)
        self.assertNotIn("  schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)

    def test_absent_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            data, error = load_snapshot(Path(t) / "missing.json")
        self.assertIsNone(data)
        self.assertTrue(error)

    def test_snapshot_does_not_leak_extra_fields(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "snapshot.json"
            p.write_text(json.dumps({"schema_version": 1, "generated_at": "2026-01-01T00:00:00Z",
                    "streams": [{"title": "Example", "status": "ended", "video_id": "abcdefghijk",
                                 "private_token": "should never render"}]}), encoding="utf-8")
            data, error = load_snapshot(p)
        self.assertFalse(error)
        self.assertEqual(set(data["streams"][0]), {"title", "status", "video_id"})

    def test_no_accidental_credentials_or_publishable_data(self):
        for p in ROOT.rglob("*"):
            if ".git" in p.parts or "__pycache__" in p.parts:
                continue
            self.assertFalse(p.is_symlink())
            if p.is_file():
                self.assertNotIn(p.suffix.lower(), {".sqlite3", ".db", ".pem", ".p12", ".key"})
        self.assertFalse((ROOT / "published_snapshot.json").exists())

if __name__ == "__main__":
    unittest.main()
