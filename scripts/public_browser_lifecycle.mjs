import { chromium } from 'playwright';

const base=process.env.HOLOVIEWER_TEST_BASE||'http://127.0.0.1:8788';
const api='https://holoviewer-public-api.singlebagel.workers.dev';
const streams=[
 {video_id:'AAAAAAAAAAA',title:'Live A',channel_id:'UC_A',channel_name:'Channel A',channel_title:'Channel A',lifecycle_state:'live',group:'hololive',start_at:'2026-10-16T10:00:00Z',avatar_url:''},
 {video_id:'BBBBBBBBBBB',title:'Live B',channel_id:'UC_B',channel_name:'Channel B',channel_title:'Channel B',lifecycle_state:'live',group:'hololive',start_at:'2026-10-16T10:02:00Z',avatar_url:''}
];
const collabEvent={
 event_id:'evt-1',label:'Test Collab',confidence:'verified',sync:{available:true},
 streams:streams.map((x,i)=>({...x,actual_start:i?'2026-10-16T10:02:00Z':'2026-10-16T10:00:00Z'}))
};
const ptt={
 schema_version:'public-consumer-v1',
 pushes:[{push_id:'p1',aid:'M.TEST',source_line:1,floor:1,kind:'推',author:'tester',content:'hello',timestamp:'2026-10-16T10:00:00Z'}],
 freshness:{status:'fresh'}
};

function assert(condition,message){if(!condition)throw new Error(message)}
async function freshDocument(page,action,expected){
 await page.evaluate(()=>{window.__hvDocumentMarker='old-document'});
 await Promise.all([
   page.waitForURL(expected,{timeout:8000}),
   action()
 ]);
 const marker=await page.evaluate(()=>window.__hvDocumentMarker);
 assert(marker===undefined,'navigation stayed in the old SPA document: '+page.url());
}

const browser=await chromium.launch({headless:true});
const page=await browser.newPage();
const browserErrors=[];
page.on('pageerror',error=>browserErrors.push('pageerror: '+String(error?.stack||error)));
page.on('console',message=>{if(message.type()==='error')browserErrors.push('console.error: '+message.text())});
function assertNoBrowserErrors(label){
 if(browserErrors.length)throw new Error(label+' browser errors:\n'+browserErrors.join('\n'));
}

await page.route(api+'/**',async route=>{
 const url=new URL(route.request().url());
 let body;
 if(url.pathname==='/v1/catalog/today')body={streams};
 else if(url.pathname==='/v1/collab/live')body={schema_version:'public-experience-v1',kind:'collab',events:[collabEvent]};
 else if(url.pathname==='/v1/collab/events/evt-1')body={schema_version:'public-experience-v1',event:collabEvent};
 else if(url.pathname==='/v1/history')body={items:streams.map(x=>({...x,lifecycle_state:'ended'})),total:2,has_more:false};
 else if(url.pathname==='/v1/watchalong/recent')body={schema_version:'public-experience-v1',kind:'watchalong',scope:'recent',events:[{event_id:'watch-1',title:'Test Watchalong',day:'2026-10-16',scheduled_time:'20:00',member_only:false,hosts:[{label:'Host A',video_id:'AAAAAAAAAAA'}],source_mapping:null,capabilities:{source_mapping:false,translation:false,telemetry:false}}]};
 else if(url.pathname==='/v1/watchalong/events/watch-1')body={schema_version:'public-experience-v1',event:{event_id:'watch-1',title:'Test Watchalong',day:'2026-10-16',scheduled_time:'20:00',member_only:false,hosts:[{label:'Host A',video_id:'AAAAAAAAAAA'}],source_mapping:null,capabilities:{source_mapping:false,translation:false,telemetry:false}}};
 else if(url.pathname==='/v1/ptt/today')body=ptt;
 else body={};
 await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
});
await page.route('https://www.youtube.com/iframe_api',async route=>{
 const body=`
 window.YT={PlayerState:{PLAYING:1,PAUSED:2,ENDED:0},Player:function(id,opts){
   const host=document.getElementById(id);
   const frame=document.createElement('iframe');frame.setAttribute('data-test-youtube','1');frame.src='about:blank';
   if(host)host.appendChild(frame);
   this.getPlayerState=()=>2;this.getCurrentTime=()=>0;this.getDuration=()=>3600;
   this.playVideo=()=>{};this.pauseVideo=()=>{};this.seekTo=()=>{};this.mute=()=>{};this.unMute=()=>{};this.setVolume=()=>{};
   this.destroy=()=>{frame.remove()};
   setTimeout(()=>opts?.events?.onReady?.({target:this}),0);
 }};
 setTimeout(()=>window.onYouTubeIframeAPIReady?.(),0);
 `;
 await route.fulfill({status:200,contentType:'application/javascript',body});
});
await page.route(/https:\/\/(i\.ytimg\.com|yt3\.ggpht\.com)\/.*/,route=>route.abort());

try{
 // Home: selecting is page-local; Watch action must create a new document.
 await page.goto(base+'/',{waitUntil:'domcontentloaded'});
 await page.waitForSelector('#homeDynamic .stream-card');
 const cards=page.locator('#homeDynamic .stream-card');
 assert(await cards.count()===2,'home fixture cards did not render');
 await cards.nth(0).click();
 assert(new URL(page.url()).pathname==='/' ,'selecting one home card unexpectedly navigated');
 assert(!(await page.locator('#multiSelectBar').getAttribute('hidden')),'home selection bar stayed hidden');
 await freshDocument(page,()=>page.locator('#multiWatch').click(),url=>url.pathname==='/custom-view/session'&&url.searchParams.getAll('stream').length===1);
 await page.waitForSelector('#stage .player-card');
 assert(await page.locator('#stage .player-card').count()===1,'single viewer did not mount one card');
 const box=await page.locator('#stage .player-card .video-wrap').boundingBox();
 assert(box&&box.height>100,'single viewer video viewport collapsed');
 assert(await page.locator('[data-test-youtube="1"]').count()===1,'YouTube player stub did not mount');

 // Viewer -> PTT must be a fresh document and must not inherit viewer body state.
 await freshDocument(page,()=>page.locator('a[data-route="ptt"]').click(),url=>url.pathname==='/ptt-today');
 await page.waitForSelector('#ptt-list .push');
 assert(!await page.evaluate(()=>document.body.classList.contains('custom-session-watching')),'PTT inherited Viewer body state');
 assert(await page.locator('#ptt-list .push').count()===1,'PTT reader did not render fixture push');
 await freshDocument(page,()=>page.locator('#ptt-focus').click(),url=>url.pathname==='/ptt-today'&&url.searchParams.get('focus')==='1');
 assert(await page.evaluate(()=>document.body.classList.contains('ptt-focus-mode')),'PTT focus document did not activate focus mode');
 assert(await page.evaluate(()=>getComputedStyle(document.querySelector('.client-rail')).display==='none'),'PTT focus document did not hide sidebar');
 await freshDocument(page,()=>page.locator('#ptt-focus').click(),url=>url.pathname==='/ptt-today'&&!url.searchParams.has('focus'));
 assert(!await page.evaluate(()=>document.body.classList.contains('ptt-focus-mode')),'PTT focus mode survived exit');

 // PTT -> Home is also a new document; prior Home selection cannot survive.
 await freshDocument(page,()=>page.locator('a[data-route="home"]').click(),url=>url.pathname==='/');
 await page.waitForSelector('#homeDynamic .stream-card');
 assert(await page.locator('#multiSelectBar').getAttribute('hidden')!==null,'Home selection survived a document lifecycle');

 // Two-card Home selection -> Multi-view.
 await page.locator('#homeDynamic .stream-card').nth(0).click();
 await page.locator('#homeDynamic .stream-card').nth(1).click();
 await freshDocument(page,()=>page.locator('#multiWatch').click(),url=>url.pathname==='/custom-view/session'&&url.searchParams.getAll('stream').length===2);
 await page.waitForSelector('#stage .player-card:nth-child(2)');
 assert(await page.locator('#stage .player-card').count()===2,'multi-view did not mount two cards');
 assert(await page.evaluate(()=>document.body.classList.contains('layout-equal')),'two-stream auto layout did not resolve to Equal');
 await page.locator('#watchSettings').click();
 assert(await page.evaluate(()=>document.body.classList.contains('settings-open')),'Viewer settings did not open');
 await page.locator('[data-layout="primary"]').click();
 assert(await page.evaluate(()=>document.body.classList.contains('layout-primary')),'Focus/primary layout did not activate');
 await page.locator('#focusChoices [data-focus-index="1"]').click();
 assert(await page.locator('#stage .player-card[data-index="1"]').evaluate(el=>el.classList.contains('primary')),'Focus target did not become primary');
 await page.locator('#audioFollowFocus').check();
 assert(await page.locator('#audioFollowFocus').isChecked(),'audio-follow-focus control did not enable');
 await page.locator('[data-layout="equal"]').click();
 assert(await page.evaluate(()=>document.body.classList.contains('layout-equal')),'Equal layout did not restore');
 await page.locator('#watchSettings').click();
 assert(!await page.evaluate(()=>document.body.classList.contains('settings-open')),'Viewer settings did not close');
 await page.locator('#watchSettings').click();
 assert(await page.evaluate(()=>document.body.classList.contains('settings-open')),'Viewer settings did not reopen for immersive control');
 await page.locator('#customImmerse').click();
 assert(await page.evaluate(()=>document.body.classList.contains('custom-immersive')),'Viewer immersive state did not activate');
 await page.locator('#immersiveExit').click();
 assert(!await page.evaluate(()=>document.body.classList.contains('custom-immersive')),'Viewer immersive exit button did not clear state');

 // Canonical Custom View builder uses full-document session navigation.
 await freshDocument(page,()=>page.locator('a[data-route="single"]').click(),url=>url.pathname==='/custom-view');
 await page.waitForSelector('#custom-live-picker [data-live-pick]');
 await page.locator('#custom-live-picker [data-live-pick]').nth(0).click();
 await freshDocument(page,()=>page.locator('#start').click(),url=>url.pathname==='/custom-view/session'&&url.searchParams.getAll('stream').length===1);
 await page.waitForSelector('#stage .player-card');
 const pttFrameHandle=await page.waitForSelector('.ptt-live-panel iframe');
 const pttFrame=await pttFrameHandle.contentFrame();
 assert(pttFrame,'Viewer PTT iframe did not create a document');
 await pttFrame.waitForSelector('#ptt-list .push');
 assert(await pttFrame.evaluate(()=>document.body.classList.contains('ptt-focus-mode')),'Viewer PTT iframe is not in focus mode');
 assert(await pttFrame.evaluate(()=>getComputedStyle(document.querySelector('.client-rail')).display==='none'),'Viewer PTT iframe leaked the main sidebar');

 // History selection is independent and uses its own fresh viewer document.
 await freshDocument(page,()=>page.locator('a[data-route="history"]').click(),url=>url.pathname==='/history');
 await page.waitForSelector('#historyDynamic .stream-card');
 await page.locator('#historyDynamic .stream-card').nth(0).click();
 await freshDocument(page,()=>page.locator('#historyMultiWatch').click(),url=>url.pathname==='/custom-view/session'&&url.searchParams.getAll('stream').length===1);
 await page.waitForSelector('#stage .player-card');

 // Collab event identity lives in URL, rehydrates after a full document load, and survives history traversal.
 await freshDocument(page,()=>page.locator('a[data-route="multi"]').click(),url=>url.pathname==='/collab');
 await page.waitForSelector('.collab-event-card');
 await freshDocument(page,()=>page.locator('.collab-event-card').click(),url=>url.pathname==='/custom-view/session'&&url.searchParams.get('event')==='evt-1');
 await page.waitForSelector('#stage .player-card:nth-child(2)');
 assert(await page.locator('#stage .player-card').count()===2,'collab viewer did not rehydrate two POVs');
 assert(await page.evaluate(()=>document.body.classList.contains('collab-live-session')),'collab live polling context was not restored');

 await page.goBack({waitUntil:'domcontentloaded'});
 await page.waitForSelector('.collab-event-card');
 assert(new URL(page.url()).pathname==='/collab','browser Back did not restore collab document');
 await page.goForward({waitUntil:'domcontentloaded'});
 await page.waitForSelector('#stage .player-card:nth-child(2)');
 assert(new URL(page.url()).pathname==='/custom-view/session','browser Forward did not restore viewer URL');


 // Watchalong recent API + manual YouTube session use real document navigation.
 await freshDocument(page,()=>page.locator('a[data-route="watchalong"]').click(),url=>url.pathname==='/watchalong');
 await page.waitForSelector('#recentWatchGrid .recent-watch-card');
 assert(await page.locator('#recentWatchGrid .recent-watch-card').count()===1,'Watchalong recent API card did not render');
 await freshDocument(page,()=>page.locator('#recentWatchGrid .recent-watch-card').click(),url=>url.pathname==='/watchalong'&&url.searchParams.get('master')==='AAAAAAAAAAA');
 await page.waitForSelector('#watchalongBuilder .selected-master');
 assert(await page.locator('#watchalongBuilder input[type="hidden"][name="master"][value="AAAAAAAAAAA"]').count()===1,'Watchalong selected master was not preserved');
 await page.locator('#watchalongBuilder [name="source"]').fill('CCCCCCCCCCC');
 await freshDocument(page,()=>page.locator('#watchalongBuilder button[type="submit"]').click(),url=>
  url.pathname==='/watchalong/session'&&
  url.searchParams.get('master')==='AAAAAAAAAAA'&&
  url.searchParams.get('source_kind')==='youtube'&&
  url.searchParams.get('youtube_mode')==='single'&&
  url.searchParams.get('source')==='CCCCCCCCCCC'
 );
 await page.waitForSelector('.watchalong-player-grid',{timeout:8000}).catch(()=>{assertNoBrowserErrors('Watchalong session');throw new Error('Watchalong session grid did not render at '+page.url())});
 assertNoBrowserErrors('Watchalong session');
 assert(await page.locator('.watchalong-player-card').count()===2,'Watchalong YouTube session did not render two player cards');
 await page.waitForSelector('#watchalong-master-player [data-test-youtube="1"]');
 await page.waitForSelector('#watchalong-source-player [data-test-youtube="1"]');

 // External-provider companion remains in a separate normal browser tab and the Public page only tracks time.
 await freshDocument(page,()=>page.locator('a[data-route="watchalong"]').click(),url=>url.pathname==='/watchalong');
 await page.locator('#watchalongBuilder [name="master"]').fill('AAAAAAAAAAA');
 await page.locator('#watchalongBuilder input[name="source_kind"][value="external"]').check();
 await page.locator('#watchalongBuilder [name="external_source"]').fill('https://example.com/watch');
 await freshDocument(page,()=>page.locator('#watchalongBuilder button[type="submit"]').click(),url=>url.pathname==='/watchalong/session'&&url.searchParams.get('source_kind')==='external');
 await page.waitForSelector('.watchalong-companion-card');
 assert((await page.locator('.watchalong-companion-card a[href="https://example.com/watch"]').count())===1,'Watchalong external companion link missing');

 console.log('PUBLIC_BROWSER_LIFECYCLE_PASS');
} finally {
 await browser.close();
}
