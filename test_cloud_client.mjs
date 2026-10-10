import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

globalThis.window = {};
globalThis.location = { origin: "https://physicsdog0505.github.io" };
globalThis.document = { readyState: "loading", addEventListener() {}, querySelector() { return null; } };
vm.runInThisContext(fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8"));


assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtube.com/watch?v=abcdefghijk"), "abcdefghijk");
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtu.be/abcdefghijk"), "abcdefghijk");
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://example.com/watch?v=abcdefghijk"), null);
assert.equal(window.HoloViewerCloud.parseYouTubeId("https://youtube.com.evil.example/watch?v=abcdefghijk"), null);
assert.equal(window.HoloViewerCloud.parseYouTubeId("javascript:alert(1)"), null);
const push = {push_id:"ptt:C_Chat:aid:1",aid:"M.123.A.1",article_url:"https://www.ptt.cc/bbs/C_Chat/M.123.A.1.html",source_line:1,floor:1,kind:"推",author:"fixture",content:"hello",occurred_at:"2026-10-08T10:00:00Z",cursor:1};
const page = {schema_version:1,next_cursor:1,has_more:false,history_gap:false,purged_through_cursor:0,checked_at:"2026-10-08T10:00:01Z",pushes:[push]};
assert.equal(window.HoloViewerCloud.validateRelayPage(page, 0).pushes[0].cursor, 1);
assert.equal(window.HoloViewerCloud.validateRelayPage({...page,history_gap:true,purged_through_cursor:1},0).historyGap,true);
assert.throws(()=>window.HoloViewerCloud.validateRelayPage({...page,history_gap:"yes"},0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, items:page.pushes}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, pushes:[{...push, secret:"no"}]}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, next_cursor:0}, 0));
assert.throws(() => window.HoloViewerCloud.validateRelayPage({...page, pushes:[{...push,cursor:2},{...push,push_id:"ptt:C_Chat:aid:2",cursor:1}],next_cursor:2}, 0));

const transcript = JSON.parse(fs.readFileSync(new URL("./public-data/demo/transcripts.json", import.meta.url), "utf8"));
const bundles = window.HoloViewerCloud.validateTranscriptArtifact(transcript);
assert.equal(bundles[0].translations[0].texts.length, bundles[0].segments.length);
assert.throws(() => window.HoloViewerCloud.validateTranscriptArtifact({...transcript, bundles:[{...transcript.bundles[0], translations:[{...transcript.bundles[0].translations[0],texts:[]}]}]}));

// Regression: a failed later relay page must not advance cursor or publish partial pushes.
const source = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const relayBody = source.slice(source.indexOf("async function pollRelay("), source.indexOf("async function startPtt("));
assert.ok(relayBody.includes("const pendingPushes = new Map()"));
assert.ok(relayBody.includes('url.searchParams.set("tail", "1")'));
assert.ok(relayBody.includes("state.bootstrapTail = false"));
assert.ok(relayBody.includes("for (const push of pendingPushes.values()) state.pushes.set(push.pushId, push);"));
assert.ok(relayBody.indexOf("if (pageNumber === RELAY_MAX_PAGES_PER_POLL - 1) throw") < relayBody.indexOf("state.cursor = nextCursor"));
assert.ok(relayBody.indexOf("if (stopped) return;", relayBody.indexOf("const pendingPushes")) < relayBody.indexOf("state.cursor = nextCursor"));

// Offline producer/consumer boundary checks against #302 public PTT exporter limits.
const pttSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
assert.match(pttSource, /articleId: boundedString\(raw\.article_id, "article_id", 320, true\)/);
assert.match(pttSource, /aid: boundedString\(raw\.aid, "article.aid", 128, true\)/);

// A retention gap must try an approved slow-lane snapshot rebase, preserve the
// relay cursor, and continue to report partial rather than a false 'complete'.
assert.ok(relayBody.includes("const refreshed = await loadPttArtifact(config.ptt)"));
assert.ok(relayBody.includes("refreshed.articles.find((item) => item.aid === aid)"));
assert.ok(relayBody.includes("state.pushes.set(push.pushId, push)"));
assert.ok(relayBody.includes('state.historyIncomplete ? "partial"'));
assert.ok(relayBody.includes("Date.now() - lastRebaseAttempt >= 60000"));

// Behavioral integration: gap -> fetch slow snapshot -> preserve cursor -> dedupe -> partial warning.
// Expose the closure's poller ONLY in this test VM, not in shipped browser code.
vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { pollRelay, "));
const originalFetch = globalThis.fetch;
const originalSetTimeout = globalThis.setTimeout;
const originalClearTimeout = globalThis.clearTimeout;
const pendingTimers = [];
const requested = [];
let relayReadCount = 0;
const relayPush = {...push, content:"relay", cursor:1};
const baseline = JSON.parse(fs.readFileSync(new URL("./public-data/demo/ptt.json", import.meta.url), "utf8"));
baseline.completeness = "complete";
baseline.articles[0].completeness = "complete";
baseline.generated_at = new Date().toISOString();
baseline.articles[0].aid = "M.123.A.1";
baseline.articles[0].pushes = [{push_id:push.push_id, floor:1, source_line:1, kind:"推", author:"fixture", content:"snapshot", occurred_at:push.occurred_at}];
globalThis.fetch = async (url) => {
  const u = String(url);
  requested.push(u);
  const body = u.includes("/v1/ptt") ? (++relayReadCount === 1 ? {...page, history_gap:true, purged_through_cursor:1, checked_at:new Date().toISOString(), pushes:[relayPush]} : {...page, next_cursor:1, history_gap:false, purged_through_cursor:1, checked_at:new Date().toISOString(), pushes:[]}) : baseline;
  return new Response(JSON.stringify(body), {status:200, headers:{"content-type":"application/json"}});
};
globalThis.setTimeout = (callback, ms) => { pendingTimers.push({callback,ms}); return pendingTimers.length; };
globalThis.clearTimeout = () => {};
try {
  const state = {cursor:0, pushes:new Map(), relayStatus:(kind,message)=>{state.status={kind,message};}, timer:null};
  let rendered = [];
  const stop = await window.HoloViewerCloud.pollRelay(
    {liveRelay:new URL("https://relay.example/v1/ptt"), ptt:new URL("https://physicsdog0505.github.io/HoloViewer/public-data/demo/ptt.json")},
    "M.123.A.1",state,items=>{rendered=items;}
  );
  for(let i=0;i<40 && !state.status;i++) await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.cursor,1, "relay cursor advances after complete valid page");
  assert.equal(state.pushes.size,1, "same push_id deduplicated across both planes");
  assert.equal(rendered.length,1);
  assert.equal(state.status?.kind,"partial", "even a newer complete-labelled snapshot is not a publisher-ledger coverage proof");
  assert.ok(requested.some(u=>u.includes("/public-data/demo/ptt.json")), "gap triggers snapshot refresh");
  const nextPoll = pendingTimers.find(item=>item.ms===5000);
  assert.ok(nextPoll, "next relay poll scheduled");
  nextPoll.callback();
  for(let i=0;i<40 && relayReadCount<2;i++) await new Promise(resolve=>setImmediate(resolve));
  for(let i=0;i<10;i++) await new Promise(resolve=>setImmediate(resolve));
  assert.equal(state.status?.kind,"partial","subsequent healthy relay page does not erase historical uncertainty");
  assert.equal(state.cursor,1);
  stop();
} finally {
  globalThis.fetch=originalFetch;
  globalThis.setTimeout=originalSetTimeout;
  globalThis.clearTimeout=originalClearTimeout;
}


// Cross-repo producer contract example from private #302 public_ptt_projection.py.
// Use the production-shaped eight-field projection including exporter metadata.
vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { loadPttArtifact, "));
const exporterArtifact = {
  schema_version:1, snapshot_id:"public-ptt:v1:synthetic-contract",
  generated_at:"2026-10-08T05:00:00Z", completeness:"partial",
  date:"2026-10-08", exporter_policy_version:"public-ptt-export:v1",
  source_hashes:{collector:"synthetic",web:"synthetic"},
  articles:[{article_id:"ptt:C_Chat:M.1791417600.A.001",
    board:"C_Chat",aid:"M.1791417600.A.001",title:"fixture thread",
    url:"https://www.ptt.cc/bbs/C_Chat/M.1791417600.A.001.html",
    completeness:"partial",pushes:[{
      push_id:"ptt:synthetic:001",floor:null,source_line:10,kind:"推",
      author:"same",content:"collector wins",occurred_at:"2026-10-08T04:00:00Z"
    }]}]
};
const oldFetchForContract=globalThis.fetch;
globalThis.fetch=async()=>new Response(JSON.stringify(exporterArtifact),{status:200,headers:{"content-type":"application/json"}});
try {
  const actual=await window.HoloViewerCloud.loadPttArtifact(new URL("https://physicsdog0505.github.io/HoloViewer/public-data/ptt.json"));
  assert.equal(actual.articles[0].aid,"M.1791417600.A.001");
  assert.equal(actual.articles[0].pushes[0].floor,null);
  assert.equal(actual.articles[0].pushes[0].content,"collector wins");
  assert.equal(actual.completeness,"partial");
} finally {globalThis.fetch=oldFetchForContract;}

// Idle relay polls must preserve DOM and reading position, including long articles.
const liveSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const livePoll = liveSource.slice(liveSource.indexOf("async function pollRelay("), liveSource.indexOf("async function startPtt("));
assert.ok(livePoll.includes("if (pendingPushes.size || historyGap) onUpdate("));

// Reader parity: speed control is locally bounded and cannot overwrite live data.
const readerSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const readerBody = readerSource.slice(readerSource.indexOf("async function startPtt("), readerSource.indexOf("async function startCustomView("));
assert.ok(readerBody.includes('["0", "停止"]'));
for (const seconds of ["5", "3", "1"]) assert.ok(readerBody.includes('["' + seconds + '",'));
assert.ok(readerBody.includes('speedSelect.addEventListener("change", resetReading)'));
assert.ok(readerBody.includes('speedSelect.value = "0";\n      stopReading();'));
assert.ok(readerBody.includes('if (followInput.checked && nearBottom) goLatest()'));
assert.ok(readerBody.includes('if (sequence !== activeArticle) return'));

// Behavioral complexity guard: long articles must not linearly scan every row
// at each automatic-reading tick. Execute the actual reader search snippet.
{
  const from = readerSource.indexOf("        const rows = list.children;");
  const to = readerSource.indexOf("        if (!next) {", from);
  assert.ok(from >= 0 && to > from);
  const snippet = readerSource.slice(from, to);
  const rowCount = 2623;
  let geometryReads = 0;
  const rows = Array.from({length:rowCount}, (_,i) => ({
    getBoundingClientRect() { geometryReads++; return {top: i * 24 - 800}; },
  }));
  const list = {children:rows};
  const viewport = {scrollY:800};
  const selectNext = new Function("list", "window", snippet + "return next;");
  const next = selectNext(list, viewport);
  assert.equal(next, rows[38], "reader advances from first row below scroll threshold");
  assert.ok(geometryReads <= 13, "2,623-row reader lookup must use logarithmic geometry reads");
}

console.log("cloud-client contract tests: pass");


const checkedConfig = JSON.parse(fs.readFileSync(new URL("./public-data/config.json", import.meta.url), "utf8"));
assert.equal(
  checkedConfig.sources.live_relay,
  "https://holoviewer-ptt-relay.singlebagel.workers.dev/v1/ptt",
  "public preview must point at the deployed read-only relay",
);


// explicit Live Sync relay AID
const liveSyncBody = source.slice(source.indexOf("async function startCustomView("), source.indexOf("function validateWatchalong("));
assert.ok(liveSyncBody.includes('const relayAid = params.get("aid")'));
assert.ok(liveSyncBody.includes("if (validRelayAid)"));
assert.ok(liveSyncBody.includes("pollRelay(config, validRelayAid"));
assert.ok(liveSyncBody.includes("bootstrapTail: true"));


// Live Sync exposes relay freshness independently from video readiness.
const liveHtml = fs.readFileSync(new URL("./custom-view/session/index.html", import.meta.url), "utf8");
assert.ok(liveHtml.includes("data-live-relay-status"));
assert.ok(liveSyncBody.includes('document.querySelector("[data-live-relay-status]")'));
assert.ok(liveSyncBody.includes("status(relayMessage, kind, text)"));


assert.equal(
  checkedConfig.sources.ptt,
  "live/ptt.json",
  "public preview must use the live PTT bootstrap artifact",
);
const livePttBootstrap = JSON.parse(fs.readFileSync(new URL("./public-data/live/ptt.json", import.meta.url), "utf8"));
assert.equal(livePttBootstrap.articles[0].aid, "1gntGd6b");
assert.equal(livePttBootstrap.articles[0].pushes.length, 0);
assert.equal(livePttBootstrap.completeness, "partial");
assert.ok(readerBody.includes("bootstrapTail: article.pushes.length === 0"));
