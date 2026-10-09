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
assert.ok(relayBody.includes("for (const push of pendingPushes.values()) state.pushes.set(push.pushId, push);"));
assert.ok(relayBody.indexOf("if (pageNumber === RELAY_MAX_PAGES_PER_POLL - 1) throw") < relayBody.indexOf("state.cursor = nextCursor"));
assert.ok(relayBody.indexOf("if (stopped) return;", relayBody.indexOf("const pendingPushes")) < relayBody.indexOf("state.cursor = nextCursor"));

// Atomic gap bookkeeping: a failed second page must not apply a first-page
// history_gap flag before its batch, cursor and rows can be committed.
assert.ok(!relayBody.includes("if (page.historyGap) state.historyIncomplete = true;"));
assert.ok(relayBody.indexOf("if (historyGap) state.historyIncomplete = true;") > relayBody.indexOf("state.cursor = nextCursor;"));

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

// Cancelled in-flight relay failures must not clobber a newly selected article status.
// This structural guard complements the browser race test pending owner acceptance.
const cancelledPollSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const cancelledPollBody = cancelledPollSource.slice(cancelledPollSource.indexOf("async function pollRelay("), cancelledPollSource.indexOf("async function startPtt("));
assert.ok(cancelledPollBody.includes('if (!stopped) state.relayStatus("stale"'), "cancelled poll must not write an obsolete stale status");

// Behavioral race: an old article's in-flight fetch fails after the poll was cancelled.
// Prior test re-exposed loadPttArtifact only; re-expose pollRelay within this VM.
vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { pollRelay, "));
// The cancelled old poll must never write over the new article's status.
{
  const previousFetch = globalThis.fetch;
  const previousSetTimeout = globalThis.setTimeout;
  const previousClearTimeout = globalThis.clearTimeout;
  let rejectOldRequest;
  const statuses = [];
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = () => new Promise((resolve, reject) => { rejectOldRequest = reject; });
  try {
    const oldState = {
      cursor: 0, pushes: new Map(), timer: null,
      relayStatus: (kind) => statuses.push(kind),
    };
    const stopOld = await window.HoloViewerCloud.pollRelay(
      {liveRelay:new URL("https://relay.example/v1/ptt"),ptt:null},
      "old-article", oldState, () => { throw new Error("cancelled poll updated DOM"); }
    );
    assert.equal(typeof rejectOldRequest, "function", "old request must be in flight");
    stopOld();
    rejectOldRequest(new Error("old request failed after switch"));
    for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(statuses, [], "cancelled old request must not update status");
    assert.equal(oldState.cursor, 0);
  } finally {
    globalThis.fetch = previousFetch;
    globalThis.setTimeout = previousSetTimeout;
    globalThis.clearTimeout = previousClearTimeout;
  }
}

// Multi-page atomicity: page one reports a retention gap, page two fails.
// No cursor, rows, gap flag, or repaint should be committed from that poll.
{
  vm.runInThisContext(source.replace("window.HoloViewerCloud = {", "window.HoloViewerCloud = { pollRelay, "));
  const oldFetch = globalThis.fetch;
  const oldSetTimeout = globalThis.setTimeout;
  const oldClearTimeout = globalThis.clearTimeout;
  let calls = 0;
  let paints = 0;
  const states = [];
  globalThis.setTimeout = () => 1;
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async () => {
    calls++;
    if (calls === 2) throw new Error("second relay page failed");
    return new Response(JSON.stringify({
      ...page, history_gap:true, purged_through_cursor:1,
      has_more:true, checked_at:new Date().toISOString(),
      pushes:[{...push, cursor:1}], next_cursor:1,
    }), {status:200,headers:{"content-type":"application/json"}});
  };
  try {
    const state = {cursor:0,pushes:new Map(),timer:null,relayStatus:(kind)=>states.push(kind)};
    const stop = await window.HoloViewerCloud.pollRelay(
      {liveRelay:new URL("https://relay.example/v1/ptt"),ptt:null},
      "M.123.A.1",state,()=>{paints++;}
    );
    for (let i=0; i<20 && calls<2; i++) await new Promise(resolve=>setImmediate(resolve));
    for (let i=0; i<10; i++) await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls,2);
    assert.equal(state.cursor,0,"failed page must not advance cursor");
    assert.equal(state.pushes.size,0,"failed page must not commit pushes");
    assert.equal(state.historyIncomplete,undefined,"failed page must not commit gap");
    assert.equal(paints,0,"failed page must not repaint");
    assert.equal(states.at(-1),"stale","failed poll reports temporary failure");
    stop();
  } finally {
    globalThis.fetch=oldFetch;
    globalThis.setTimeout=oldSetTimeout;
    globalThis.clearTimeout=oldClearTimeout;
  }
}

// Idle relay polls must preserve DOM and reading position, including long articles.
const liveSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const livePoll = liveSource.slice(liveSource.indexOf("async function pollRelay("), liveSource.indexOf("async function startPtt("));
assert.ok(livePoll.includes("if (pendingPushes.size || historyGap) onUpdate("));

// Authoritative reader parity: baseline rows are immediately visible, new relay
// rows enter a reveal queue, and visual speed never scrolls through old history.
const readerSource = fs.readFileSync(new URL("./assets/cloud-client.js", import.meta.url), "utf8");
const readerBody = readerSource.slice(readerSource.indexOf("async function startPtt("), readerSource.indexOf("async function startCustomView("));
assert.ok(readerBody.includes('["0.5", "普通（0.5 秒）"]'));
assert.ok(readerBody.includes('["0.2", "快（0.2 秒）"]'));
assert.ok(readerBody.includes('["1", "慢（1 秒）"]'));
assert.ok(readerBody.includes("visibleIds = new Set(initial.slice(0, visibleCount).map((push) => push.pushId))"));
assert.ok(readerBody.includes("for (const push of newPushes) pending.push(push.pushId)"));
assert.ok(readerBody.includes('revealTimer = setTimeout(revealNext, Number(speedSelect.value) * 1000)'));
assert.ok(readerBody.includes("const id = pending.shift()"));
assert.ok(readerBody.includes("if (row) row.hidden = false"));
assert.ok(readerBody.includes("flushPending();"));
assert.ok(readerBody.includes("userPausedFollow = false;"));
assert.ok(readerBody.includes('window.addEventListener("wheel", pauseOnManualNavigation'));
assert.ok(readerBody.includes('window.addEventListener("touchmove", pauseOnManualNavigation'));
assert.ok(readerBody.includes("sessionStorage.setItem(checkpointKey, pushId)"));
assert.ok(!readerBody.includes("next.scrollIntoView"), "old-message scroll timer must not return");
assert.ok(readerBody.includes('window.scrollTo({ top: previousScroll, behavior: "instant" })'));
assert.ok(readerBody.includes("if (sequence !== activeArticle) return"));

// Behavioral reader-queue test executes the actual production queue closure,
// using a small DOM/timer shim rather than relying only on source assertions.
{
  const begin = readerBody.indexOf("    // The authoritative private Viewer paces NEW message reveal");
  const end = readerBody.indexOf("    let stopRelay = null;", begin);
  assert.ok(begin >= 0 && end > begin, "locate reader queue implementation");
  const actualQueue = readerBody.slice(begin, end);
  const listeners = {};
  const checkpoints = new Map();
  const timeouts = new Map();
  let timerSerial = 0, scrolls = 0, revealCount = 0;
  const list = {children:[],lastElementChild:null};
  const speedSelect = {value:"0.5", addEventListener:(key,fn)=>listeners["speed:"+key]=fn};
  const followInput = {checked:true, addEventListener:(key,fn)=>listeners["follow:"+key]=fn};
  const latestButton = {addEventListener:(key,fn)=>listeners["latest:"+key]=fn};
  const viewport = {addEventListener:(key,fn)=>listeners[key]=fn};
  const fakeSession = {setItem:(key,value)=>checkpoints.set(key,value)};
  const makeRows = (_target, pushes, visible) => {
    list.children=pushes.map(p=>({dataset:{pushId:p.pushId},hidden:!visible.has(p.pushId),
      scrollIntoView:()=>{scrolls++;}}));
    list.lastElementChild=list.children.at(-1);
  };
  const fakeSetTimeout = (fn,delay)=>{const id=++timerSerial;timeouts.set(id,{fn,delay});return id;};
  const fakeClearTimeout = id=>timeouts.delete(id);
  const create = new Function("list","speedSelect","followInput","latestButton","window",
    "sessionStorage","renderPushes","setTimeout","clearTimeout",
    actualQueue + "return {setBase(ids){visibleIds=new Set(ids);checkpointKey='test-aid';},"+
    "enqueue(ids){pending.push(...ids);},rebuildRows,scheduleReveal,flushPending,"+
    "pendingSize:()=>pending.length,paused:()=>userPausedFollow};");
  const reader = create(list,speedSelect,followInput,latestButton,viewport,fakeSession,
    makeRows,fakeSetTimeout,fakeClearTimeout);
  reader.setBase(["old"]);
  reader.rebuildRows([{pushId:"old"},{pushId:"new"}]);
  assert.equal(list.children[0].hidden,false,"historical baseline immediately visible");
  assert.equal(list.children[1].hidden,true,"new relay row initially queued");
  reader.enqueue(["new"]);
  reader.scheduleReveal();
  assert.equal([...timeouts.values()][0].delay,500,"default reveal is 500ms, not page scrolling");
  listeners.wheel();
  assert.equal(reader.paused(),true,"manual scroll pauses following");
  const [id,timer]=[...timeouts][0];timeouts.delete(id);timer.fn();
  assert.equal(list.children[1].hidden,false,"timer reveals queued new row");
  assert.equal(scrolls,0,"manual scroll not overridden by reveal");
  assert.equal(checkpoints.get("test-aid"),"new");
  reader.rebuildRows([{pushId:"old"},{pushId:"new"},{pushId:"new2"}]);
  reader.enqueue(["new2"]);reader.scheduleReveal();
  listeners["latest:click"]();
  assert.equal(reader.pendingSize(),0,"jump latest flushes queue");
  assert.equal(list.children[2].hidden,false);
  assert.equal(timeouts.size,0,"jump latest cancels reveal timer");
  assert.equal(reader.paused(),false,"jump latest resumes follow");
  assert.equal(scrolls,1,"jump latest scrolls once");
  assert.equal(checkpoints.get("test-aid"),"new2");
  listeners["latest:click"]();
  assert.equal(scrolls,2,"jump latest remains idempotent");
}

// Incremental batch regressions: the production queue deduplicates and sorts
// incoming PTT rows, and stale poll startup cannot replace the active stop hook.
assert.ok(readerBody.includes("const known = new Set([...visibleIds, ...pending])"));
assert.ok(readerBody.includes("pending.sort((a, b) => pushOrder(byId.get(a), byId.get(b)))"));
assert.ok(readerBody.includes("if (sequence !== activeArticle) stopCurrentRelay?.()"));
assert.ok(readerBody.includes("else stopRelay = stopCurrentRelay || null"));
assert.ok(readerBody.includes("const previousCheckpoint = loadCheckpoint()"));

// Private 8501 checkpoint contract: never mark previously unread baseline rows
// as read before their paced reveal. A missing checkpoint means first visit.
assert.ok(readerBody.includes("const checkpointIndex = previousCheckpoint"));
assert.ok(readerBody.includes("const visibleCount = checkpointIndex >= 0 ? checkpointIndex + 1 : initial.length"));
assert.ok(readerBody.includes("pending = initial.slice(visibleCount).map((push) => push.pushId)"));
assert.ok(readerBody.includes("if (initial.length && pending.length === 0)"));
assert.ok(readerBody.includes("scheduleReveal();"));
{
  const initial = [{pushId:"seen-1"},{pushId:"seen-2"},{pushId:"unseen-3"},{pushId:"unseen-4"}];
  const derive = (checkpoint) => {
    const checkpointIndex = checkpoint ? initial.findIndex((push) => push.pushId === checkpoint) : -1;
    const visibleCount = checkpointIndex >= 0 ? checkpointIndex + 1 : initial.length;
    return {visible:initial.slice(0,visibleCount).map(p=>p.pushId),pending:initial.slice(visibleCount).map(p=>p.pushId)};
  };
  assert.deepEqual(derive("seen-2"), {visible:["seen-1","seen-2"],pending:["unseen-3","unseen-4"]});
  assert.deepEqual(derive(null), {visible:initial.map(p=>p.pushId),pending:[]});
  assert.deepEqual(derive("rotated-away"), {visible:initial.map(p=>p.pushId),pending:[]});
}

{
  const order = (x,y) => (x.floor ?? Number.MAX_SAFE_INTEGER)-(y.floor ?? Number.MAX_SAFE_INTEGER);
  const visible = new Set(["old"]);
  let pending = ["new-3"];
  const pushes = [
    {pushId:"old",floor:1},
    {pushId:"new-3",floor:3},
    {pushId:"new-2",floor:2},
    {pushId:"new-2",floor:2},
  ];
  const known = new Set([...visible, ...pending]);
  const incoming = pushes.filter(p => {
    if(known.has(p.pushId)) return false;
    known.add(p.pushId);
    return true;
  }).sort(order);
  for(const p of incoming) pending.push(p.pushId);
  const byId = new Map(pushes.map(p => [p.pushId,p]));
  pending.sort((a,b) => order(byId.get(a),byId.get(b)));
  assert.deepEqual(pending,["new-2","new-3"]);
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
