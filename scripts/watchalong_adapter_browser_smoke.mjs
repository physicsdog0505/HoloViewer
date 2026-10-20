import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import fs from 'node:fs';

const port=Number(process.env.HOLOVIEWER_WATCHALONG_SMOKE_PORT||8792);
const base='http://127.0.0.1:'+port;
const root=new URL('../',import.meta.url);
const manifest=JSON.parse(fs.readFileSync(new URL('../site/data/watchalong/manifest.json',import.meta.url),'utf8'));

function assert(condition,message){if(!condition)throw new Error(message)}
function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
async function waitServer(){
 for(let i=0;i<50;i++){
  try{
   const r=await fetch(base+'/data/watchalong/manifest.json');
   if(r.ok)return;
  }catch{}
  await sleep(100);
 }
 throw new Error('static server did not start');
}

const server=spawn('python3',['-m','http.server',String(port),'--directory','site'],{
 cwd:new URL('..',import.meta.url).pathname,
 stdio:['ignore','pipe','pipe']
});
let browser=null;
try{
 await waitServer();
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage();
 const errors=[];
 page.on('pageerror',error=>errors.push(String(error?.stack||error)));
 page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text())});

 let manifestRequests=0;
 await page.route('**/data/watchalong/manifest.json',async route=>{
  manifestRequests++;
  await route.continue();
 });
 await page.route('https://www.youtube.com/iframe_api',async route=>{
  const body=`
  (()=> {
    const instances=[];
    let serial=0;
    window.__ytInstances=instances;
    window.__ytCreateCount=()=>instances.length;
    window.YT={
      PlayerState:{UNSTARTED:-1,ENDED:0,PLAYING:1,PAUSED:2,BUFFERING:3,CUED:5},
      Player:function(id,opts){
        this.__serial=++serial;
        this.__hostId=id;
        this.__videoId=String(opts?.videoId||'');
        this.__time=0;
        this.__state=2;
        this.__muted=false;
        this.__destroyed=false;
        this.__seekCalls=[];
        this.__loadCalls=[];
        const host=document.getElementById(id);
        const frame=document.createElement('iframe');
        frame.dataset.testYoutube='1';
        frame.dataset.playerSerial=String(this.__serial);
        frame.src='about:blank';
        host?.append(frame);
        this.getPlayerState=()=>this.__state;
        this.getCurrentTime=()=>this.__time;
        this.getDuration=()=>12000;
        this.getVideoData=()=>({video_id:this.__videoId});
        this.seekTo=(seconds)=>{this.__time=Number(seconds)||0;this.__seekCalls.push(this.__time)};
        this.playVideo=()=>{this.__state=1;opts?.events?.onStateChange?.({target:this,data:1})};
        this.pauseVideo=()=>{this.__state=2;opts?.events?.onStateChange?.({target:this,data:2})};
        this.mute=()=>{this.__muted=true};
        this.unMute=()=>{this.__muted=false};
        this.isMuted=()=>this.__muted;
        this.setVolume=()=>{};
        this.loadVideoById=spec=>{
          this.__videoId=String(spec?.videoId||'');
          this.__time=Number(spec?.startSeconds)||0;
          this.__state=1;
          this.__loadCalls.push({kind:'load',videoId:this.__videoId,time:this.__time});
        };
        this.cueVideoById=spec=>{
          this.__videoId=String(spec?.videoId||'');
          this.__time=Number(spec?.startSeconds)||0;
          this.__state=5;
          this.__loadCalls.push({kind:'cue',videoId:this.__videoId,time:this.__time});
        };
        this.destroy=()=>{this.__destroyed=true;frame.remove()};
        instances.push(this);
        setTimeout(()=>opts?.events?.onReady?.({target:this}),0);
      }
    };
    setTimeout(()=>window.onYouTubeIframeAPIReady?.(),0);
  })();
  `;
  await route.fulfill({status:200,contentType:'application/javascript',body});
 });

 // Normal Viewer must not enter or fetch Watchalong Adapter data.
 await page.route('https://holoviewer-public-api.singlebagel.workers.dev/**',async route=>{
  const url=new URL(route.request().url());
  let body={};
  if(url.pathname==='/v1/catalog/today')body={streams:[]};
  else if(url.pathname.startsWith('/v1/catalog/videos/'))body={video_id:url.pathname.split('/').pop(),lifecycle_state:'unknown'};
  else if(url.pathname==='/v1/ptt/today')body={schema_version:'public-consumer-v1',pushes:[]};
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(base+'/viewer/?stream=AAAAAAAAAAA',{waitUntil:'domcontentloaded'});
 await page.waitForSelector('.player-card [data-test-youtube="1"]');
 assert(await page.locator('.player-card').count()===1,'normal Viewer player count changed');
 assert(await page.locator('#watchalongSubtitleOverlay').count()===0,'normal Viewer mounted Watchalong subtitles');
 assert(manifestRequests===0,'normal Viewer fetched Watchalong manifest');

 for(const entry of manifest.events){
  const event=JSON.parse(fs.readFileSync(new URL('../site/'+entry.path.replace(/^\//,''),import.meta.url),'utf8'));
  await page.goto(base+'/viewer/?watchalong_event='+encodeURIComponent(entry.event_id),{waitUntil:'domcontentloaded'});
  await page.waitForSelector('.player-card:nth-child(2) [data-test-youtube="1"]');
  await page.waitForFunction(()=>window.__ytInstances?.length===2);
  assert(await page.locator('.player-card').count()===2,entry.event_id+' did not mount host + source');
  const initial=await page.evaluate(()=>window.__ytInstances.map(p=>({serial:p.__serial,videoId:p.__videoId,destroyed:p.__destroyed})));
  assert(initial[0].videoId===entry.master_video_id,entry.event_id+' host video mismatch');
  assert(initial[1].videoId===event.segments[0].source_video_id,entry.event_id+' initial source mismatch');
  const hostSerial=initial[0].serial;

  for(let i=0;i<event.segments.length;i++){
   const seg=event.segments[i];
   const hostSeconds=seg.host_start_ms/1000+0.25;
   await page.evaluate(value=>{
    const host=window.__ytInstances[0];
    host.__time=value;
    host.__state=1;
   },hostSeconds);
   await page.waitForFunction(({sourceId,target})=>{
    const source=window.__ytInstances?.[1];
    return source&&source.__videoId===sourceId&&Math.abs(source.__time-target)<0.05;
   },{
    sourceId:seg.source_video_id,
    target:seg.source_start_ms/1000+0.25
   },{timeout:2500});
   const state=await page.evaluate(()=>({
    count:window.__ytCreateCount(),
    hostSerial:window.__ytInstances[0].__serial,
    hostDestroyed:window.__ytInstances[0].__destroyed,
    sourceVideo:window.__ytInstances[1].__videoId
   }));
   assert(state.count===2,entry.event_id+' segment '+(i+1)+' remounted a player');
   assert(state.hostSerial===hostSerial&&!state.hostDestroyed,entry.event_id+' segment '+(i+1)+' remounted/destroyed host');
   assert(state.sourceVideo===seg.source_video_id,entry.event_id+' segment '+(i+1)+' source transition failed');
  }

  const cue=event.subtitles[Math.min(10,event.subtitles.length-1)];
  await page.evaluate(value=>{window.__ytInstances[0].__time=value},(cue.start_ms+1)/1000);
  await page.waitForFunction(expected=>document.querySelector('.watchalong-subtitle-line.translation')?.textContent===expected,cue.translation,{timeout:1500});
  assert((await page.locator('.watchalong-subtitle-line.original').textContent())===String(cue.original||''),entry.event_id+' original subtitle not host-clock selected');
  assert((await page.locator('.watchalong-subtitle-line.translation').textContent())===String(cue.translation||''),entry.event_id+' translation subtitle not host-clock selected');
  assert(await page.locator('.watchalong-failed').count()===0,entry.event_id+' unexpectedly failed closed');
 }

 // Missing event must fail closed.
 await page.goto(base+'/viewer/?watchalong_event=missing00000',{waitUntil:'domcontentloaded'});
 await page.waitForSelector('.watchalong-failed');
 assert((await page.locator('.player-card').count())===0,'missing event did not fail closed');

 // Corrupt one event response while keeping the manifest SHA unchanged.
 const corruptId=manifest.events[0].event_id;
 const corruptPath=manifest.events[0].path;
 await page.route('**'+corruptPath,async route=>{
  const raw=fs.readFileSync(new URL('../site/'+corruptPath.replace(/^\//,''),import.meta.url),'utf8');
  await route.fulfill({status:200,contentType:'application/json',body:raw+' '});
 });
 await page.goto(base+'/viewer/?watchalong_event='+encodeURIComponent(corruptId),{waitUntil:'domcontentloaded'});
 await page.waitForSelector('.watchalong-failed');
 assert((await page.locator('.watchalong-failed').textContent()).includes('sha256 mismatch'),'corrupted event did not fail on SHA');

 if(errors.length)throw new Error('browser errors:\n'+errors.join('\n'));
 console.log('WATCHALONG_ADAPTER_BROWSER_SMOKE_PASS');
 console.log(JSON.stringify({
  events:manifest.events.map(entry=>({event_id:entry.event_id,segments:entry.source_count,cues:entry.cue_count})),
  host_remount:false,
  manual_only_transition:false,
  missing_event:'fail-closed',
  corrupted_sha:'fail-closed'
 }));
} finally {
 await browser?.close();
 server.kill('SIGTERM');
}
