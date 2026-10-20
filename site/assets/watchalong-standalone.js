'use strict';

const config=window.HOLOVIEWER_CONFIG||{};
const API_BASE=String(config.apiBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_BASE=String(config.pttArchiveBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_MANIFEST=String(config.pttArchiveManifest||'/ptt/v1/manifests/static-assets-full-2026-10.json');
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
const PTT_ARCHIVE_SCHEMA='ptt-r2-archive-v1';
const params=new URLSearchParams(location.search);
const HOST_ID=validVideoId(params.get('host'));
const SOURCE_ID=validVideoId(params.get('source'));
const PLAYLIST_ID=validPlaylistId(params.get('playlist'));
const EVENT_ID=String(params.get('event')||'').trim();

const workspace=document.getElementById('watchalongWorkspace');
const linkedPlayback=document.getElementById('linkedPlayback');
const offsetValue=document.getElementById('offsetValue');
const hostStatus=document.getElementById('hostStatus');
const sourceStatus=document.getElementById('sourceStatus');
const pttPanel=document.getElementById('pttPanel');
const pttTitle=document.getElementById('pttTitle');
const pttMeta=document.getElementById('pttMeta');
const pttFeed=document.getElementById('pttFeed');
const pttNewest=document.getElementById('pttNewest');
const pttShowFloor=document.getElementById('pttShowFloor');
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');
const offsetMinus=document.getElementById('offsetMinus');
const offsetPlus=document.getElementById('offsetPlus');
const previousSegment=document.getElementById('previousSegment');
const nextSegment=document.getElementById('nextSegment');
const mobileSwapHost=document.getElementById('mobileSwapHost');
const mobileSwapSource=document.getElementById('mobileSwapSource');
const segmentStatus=document.getElementById('segmentStatus');
const immersiveToolbarTrigger=document.getElementById('immersiveToolbarTrigger');
const topbar=document.querySelector('.watchalong-topbar');
const sourceStandby=document.getElementById('sourceStandby');
const subtitleOverlay=document.getElementById('subtitleOverlay');
const subtitleOriginal=document.getElementById('subtitleOriginal');
const subtitleTranslation=document.getElementById('subtitleTranslation');

let hostPlayer=null;
let sourcePlayer=null;
let timelineAligned=params.has('offset')&&Number.isFinite(Number(params.get('offset')));
let sourceOffsetSeconds=timelineAligned?Number(params.get('offset')):0;
let suppressLinkedCommand=false;
let syncTimer=null;
let subtitleTimer=null;
let pttTimer=null;
let hostWindow=null;
let pttRows=[];
let pttVisible=0;
let pttFollowing=true;
let archiveManifestCache=null;
let segments=[];
let subtitles=[];
let activeSegmentIndex=-1;
let activeSourceVideoId=SOURCE_ID||'';
let sourceStandbyActive=false;
let immersiveToolbarTimer=null;

function validVideoId(value){const id=String(value||'');return /^[A-Za-z0-9_-]{11}$/.test(id)?id:''}
function validPlaylistId(value){const id=String(value||'');return /^[A-Za-z0-9_-]{10,64}$/.test(id)?id:''}
function api(path){
 if(!API_BASE||!/^https:\/\//.test(API_BASE))return Promise.reject(new Error('正式 API 未設定'));
 return fetch(API_BASE+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}}).then(r=>{if(!r.ok)throw new Error('API HTTP '+r.status);return r.json()});
}
function taipeiDay(value=new Date()){
 const date=value instanceof Date?value:new Date(value);
 if(!Number.isFinite(date.getTime()))return '';
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
 const out=Object.fromEntries(parts.filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function clock(seconds){
 const s=Math.max(0,Math.floor(Number(seconds)||0)),m=Math.floor(s/60),r=s%60,h=Math.floor(m/60);
 return h?String(h).padStart(2,'0')+':'+String(m%60).padStart(2,'0')+':'+String(r).padStart(2,'0'):String(m).padStart(2,'0')+':'+String(r).padStart(2,'0');
}
function refreshOffsetUi(){
 offsetValue.textContent=timelineAligned?'Offset '+(sourceOffsetSeconds>=0?'+':'')+sourceOffsetSeconds.toFixed(1)+'s':'尚未對齊';
 offsetMinus.disabled=!timelineAligned;
 offsetPlus.disabled=!timelineAligned;
}
function setOffset(value,{persist=true}={}){
 sourceOffsetSeconds=Math.round((Number(value)||0)*10)/10;
 timelineAligned=true;
 refreshOffsetUi();
 if(persist){
  const q=new URLSearchParams(location.search);q.set('offset',String(sourceOffsetSeconds));history.replaceState(null,'',location.pathname+'?'+q.toString());
 }
}
refreshOffsetUi();

function setMobilePrimary(kind){
 const primary=kind==='host'?'host':'source';
 workspace.classList.toggle('mobile-primary-host',primary==='host');
 workspace.classList.toggle('mobile-primary-source',primary==='source');
 mobileSwapHost.setAttribute('aria-pressed',String(primary==='host'));
 mobileSwapSource.setAttribute('aria-pressed',String(primary==='source'));
}
document.querySelectorAll('[data-watch-layout]').forEach(button=>button.addEventListener('click',()=>{
 const mode=button.dataset.watchLayout==='source'?'source':'equal';
 workspace.classList.toggle('layout-source',mode==='source');
 workspace.classList.toggle('layout-equal',mode==='equal');
 document.querySelectorAll('[data-watch-layout]').forEach(item=>{
  const active=item===button;item.classList.toggle('active',active);item.setAttribute('aria-pressed',String(active));
 });
}));
mobileSwapHost.onclick=()=>setMobilePrimary('host');
mobileSwapSource.onclick=()=>setMobilePrimary('source');
setMobilePrimary('source');
offsetMinus.onclick=()=>{if(timelineAligned)setOffset(sourceOffsetSeconds-1)};
offsetPlus.onclick=()=>{if(timelineAligned)setOffset(sourceOffsetSeconds+1)};
document.getElementById('captureOffset').onclick=()=>{
 try{
  const host=hostPlayer?.getCurrentTime?.(),source=sourcePlayer?.getCurrentTime?.();
  if(Number.isFinite(host)&&Number.isFinite(source))setOffset(source-host);
 }catch{}
};
pttShowFloor.onchange=()=>pttPanel.classList.toggle('ptt-floor-hidden',!pttShowFloor.checked);
pttFontSize.addEventListener('input',()=>{
 const size=Math.max(12,Math.min(26,Number(pttFontSize.value)||14));
 pttFontValue.textContent=size+'px';
 document.documentElement.style.setProperty('--ptt-font-size',size+'px');
 try{localStorage.setItem('holoviewer-viewer-ptt-font',String(size))}catch{}
});
try{
 const font=Math.max(12,Math.min(26,Number(localStorage.getItem('holoviewer-viewer-ptt-font'))||14));
 pttFontSize.value=String(font);pttFontValue.textContent=font+'px';
 document.documentElement.style.setProperty('--ptt-font-size',font+'px');
}catch{}
pttNewest.onclick=()=>{pttFollowing=true;pttFeed.scrollTop=pttFeed.scrollHeight;pttNewest.hidden=true};
pttFeed.addEventListener('scroll',()=>{
 pttFollowing=pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48;
 pttNewest.hidden=pttFollowing;
},{passive:true});
function clearImmersiveToolbarTimer(){clearTimeout(immersiveToolbarTimer);immersiveToolbarTimer=null}
function hideImmersiveToolbar(){
 clearImmersiveToolbarTimer();
 if(!document.fullscreenElement)return;
 document.body.classList.remove('toolbar-visible');
}
function scheduleImmersiveToolbarHide(delay=3000){
 clearImmersiveToolbarTimer();
 if(!document.fullscreenElement)return;
 immersiveToolbarTimer=setTimeout(hideImmersiveToolbar,delay);
}
function showImmersiveToolbar({sticky=false}={}){
 if(!document.fullscreenElement)return;
 document.body.classList.add('toolbar-visible');
 clearImmersiveToolbarTimer();
 if(!sticky)scheduleImmersiveToolbarHide();
}
const fullscreenButton=document.getElementById('fullscreen');
fullscreenButton.onclick=async()=>{
 try{
  if(document.fullscreenElement)await document.exitFullscreen();
  else{
   await document.documentElement.requestFullscreen();
   fullscreenButton.blur();
  }
 }catch{}
};
immersiveToolbarTrigger.addEventListener('mouseenter',()=>showImmersiveToolbar({sticky:true}));
topbar.addEventListener('mouseenter',()=>showImmersiveToolbar({sticky:true}));
topbar.addEventListener('mouseleave',()=>scheduleImmersiveToolbarHide());
topbar.addEventListener('focusin',()=>showImmersiveToolbar({sticky:true}));
topbar.addEventListener('focusout',()=>scheduleImmersiveToolbarHide());
topbar.addEventListener('click',()=>scheduleImmersiveToolbarHide());
topbar.addEventListener('input',()=>scheduleImmersiveToolbarHide());
document.addEventListener('fullscreenchange',()=>{
 const immersive=Boolean(document.fullscreenElement);
 document.body.classList.toggle('immersive',immersive);
 if(immersive){
  document.body.classList.add('toolbar-visible');
  scheduleImmersiveToolbarHide();
 }else{
  clearImmersiveToolbarTimer();
  document.body.classList.remove('toolbar-visible');
 }
});

function sourceExpectedTime(hostSeconds){
 if(!timelineAligned||!Number.isFinite(hostSeconds))return null;
 return hostSeconds+sourceOffsetSeconds;
}
function setSourceStandby(active){
 const next=Boolean(active);
 if(sourceStandbyActive===next)return;
 sourceStandbyActive=next;
 sourceStandby.hidden=!next;
 if(next){
  subtitleOverlay.hidden=true;
  try{
   const state=sourcePlayer?.getPlayerState?.();
   if(state===YT.PlayerState.PLAYING||state===YT.PlayerState.BUFFERING)sourcePlayer.pauseVideo();
   const current=sourcePlayer?.getCurrentTime?.();
   if(Number.isFinite(current)&&current>0.75)sourcePlayer.seekTo(0,true);
  }catch{}
 }
}
function onHostStateChange(event){
 if(!linkedPlayback.checked||!timelineAligned||!sourcePlayer||suppressLinkedCommand)return;
 let host=null;try{host=hostPlayer?.getCurrentTime?.()}catch{}
 if(Number.isFinite(host)&&sourceExpectedTime(host)<0){setSourceStandby(true);return}
 setSourceStandby(false);
 try{
  suppressLinkedCommand=true;
  if(event.data===YT.PlayerState.PLAYING)sourcePlayer.playVideo();
  else if(event.data===YT.PlayerState.PAUSED)sourcePlayer.pauseVideo();
 }catch{}finally{setTimeout(()=>{suppressLinkedCommand=false},0)}
}
function mountPlayers(){
 if(!window.YT?.Player)return;
 if(HOST_ID&&!hostPlayer){
  hostPlayer=new YT.Player('hostPlayer',{
   videoId:HOST_ID,playerVars:{playsinline:1,rel:0,enablejsapi:1,origin:location.origin},
   events:{onStateChange:onHostStateChange,onReady:()=>{hostStatus.textContent='已就緒';startSyncLoop()}}
  });
 }else if(!HOST_ID){
  hostStatus.textContent='缺少 Hololive 主影片';
 }
 if(!sourcePlayer&&(SOURCE_ID||PLAYLIST_ID)){
  const vars={playsinline:1,rel:0,enablejsapi:1,origin:location.origin};
  if(PLAYLIST_ID){
   vars.listType='playlist';vars.list=PLAYLIST_ID;
   const playlistStart=Math.max(1,Number(params.get('playlist_start'))||1);
   vars.index=playlistStart-1;
  }
  sourcePlayer=new YT.Player('sourcePlayer',{
   videoId:SOURCE_ID||undefined,playerVars:vars,
   events:{onReady:()=>{sourceStatus.textContent=PLAYLIST_ID?'Playlist 已就緒':'片源已就緒';startSyncLoop();startSubtitleLoop()}}
  });
 }else if(!SOURCE_ID&&!PLAYLIST_ID){
  sourceStatus.textContent='缺少 YouTube 片源';
 }
}
window.onYouTubeIframeAPIReady=mountPlayers;
if(window.YT?.Player)mountPlayers();

function startSyncLoop(){
 if(syncTimer||!hostPlayer||!sourcePlayer)return;
 syncTimer=setInterval(()=>{
  let host=null;
  try{host=hostPlayer.getCurrentTime()}catch{return}
  if(!Number.isFinite(host))return;
  syncPttToHost(host);
  if(!linkedPlayback.checked||!timelineAligned){setSourceStandby(false);return}
  const expected=sourceExpectedTime(host);
  if(!Number.isFinite(expected))return;
  if(expected<0){
   setSourceStandby(true);
   return;
  }
  setSourceStandby(false);
  let source,state;
  try{source=sourcePlayer.getCurrentTime();state=hostPlayer.getPlayerState()}catch{return}
  if(!Number.isFinite(source))return;
  if(Math.abs(source-expected)>2.5){
   try{sourcePlayer.seekTo(expected,true)}catch{}
  }
  if(state===YT.PlayerState.PLAYING){
   try{if(sourcePlayer.getPlayerState()!==YT.PlayerState.PLAYING)sourcePlayer.playVideo()}catch{}
  }else if(state===YT.PlayerState.PAUSED){
   try{if(sourcePlayer.getPlayerState()===YT.PlayerState.PLAYING)sourcePlayer.pauseVideo()}catch{}
  }
 },500);
}
function startSubtitleLoop(){
 if(subtitleTimer)return;
 subtitleTimer=setInterval(()=>{
  let current=null;try{current=sourcePlayer?.getCurrentTime?.()}catch{}
  if(sourceStandbyActive||!Number.isFinite(current)||!subtitles.length){subtitleOverlay.hidden=true;return}
  const row=subtitles.find(item=>current>=item.start&&current<item.end);
  if(!row){subtitleOverlay.hidden=true;return}
  subtitleOriginal.textContent=row.original||'';
  subtitleTranslation.textContent=row.translation||'';
  subtitleOriginal.hidden=!row.original;subtitleTranslation.hidden=!row.translation;
  subtitleOverlay.hidden=!row.original&&!row.translation;
 },250);
}

function normalizeSegments(payload){
 const raw=payload?.segments||payload?.sync_segments||payload?.artifacts?.segments||[];
 return Array.isArray(raw)?raw.map((item,index)=>({
  id:String(item?.segment_id||item?.id||index+1),
  label:String(item?.label||item?.episode||item?.title||('段點 '+(index+1))),
  host:Number(item?.host_start_seconds??item?.host_start??item?.master_start_seconds),
  source:Number(item?.source_start_seconds??item?.source_start),
  sourceVideoId:validVideoId(item?.source_video_id||item?.video_id||'')
 })).filter(item=>Number.isFinite(item.host)&&Number.isFinite(item.source)):[];
}
function normalizeSubtitles(payload){
 const raw=payload?.subtitles||payload?.transcript||payload?.artifacts?.subtitles||[];
 return Array.isArray(raw)?raw.map(item=>({
  start:Number(item?.start??item?.start_seconds),end:Number(item?.end??item?.end_seconds),
  original:String(item?.original||item?.text||''),translation:String(item?.translation||item?.translated||'')
 })).filter(item=>Number.isFinite(item.start)&&Number.isFinite(item.end)&&item.end>item.start):[];
}
function renderSegments(){
 if(!segments.length){
  activeSegmentIndex=-1;
  segmentStatus.textContent='無段點';
  previousSegment.disabled=true;
  nextSegment.disabled=true;
  return;
 }
 if(activeSegmentIndex<0||activeSegmentIndex>=segments.length)activeSegmentIndex=0;
 segmentStatus.textContent=segments[activeSegmentIndex].label+' · '+(activeSegmentIndex+1)+'/'+segments.length;
 previousSegment.disabled=activeSegmentIndex<=0;
 nextSegment.disabled=activeSegmentIndex>=segments.length-1;
}
function jumpToSegmentIndex(index){
 if(index<0||index>=segments.length)return;
 activeSegmentIndex=index;
 const segment=segments[index];
 try{hostPlayer?.seekTo?.(Math.max(0,segment.host),true)}catch{}
 try{
  if(segment.sourceVideoId&&segment.sourceVideoId!==activeSourceVideoId){
   activeSourceVideoId=segment.sourceVideoId;
   sourcePlayer?.loadVideoById?.({videoId:segment.sourceVideoId,startSeconds:Math.max(0,segment.source)});
  }else sourcePlayer?.seekTo?.(Math.max(0,segment.source),true);
 }catch{}
 setOffset(segment.source-segment.host);
 renderSegments();
 if(linkedPlayback.checked){try{hostPlayer?.playVideo?.();sourcePlayer?.playVideo?.()}catch{}}
}
previousSegment.onclick=()=>jumpToSegmentIndex(activeSegmentIndex-1);
nextSegment.onclick=()=>jumpToSegmentIndex(activeSegmentIndex+1);
async function loadReadOnlyArtifacts(){
 if(!EVENT_ID)return;
 try{
  const data=await api('/v1/watchalong/events/'+encodeURIComponent(EVENT_ID));
  const payload=data?.event||data;
  segments=normalizeSegments(payload);
  subtitles=normalizeSubtitles(payload);
  renderSegments();
 }catch{
  segments=[];subtitles=[];activeSegmentIndex=-1;renderSegments();
  segmentStatus.textContent='段點資料不可用';
 }
}
renderSegments();
loadReadOnlyArtifacts();

function pttKey(row){return String(row?.source_record_key||row?.push_id||row?.aid+':'+row?.source_line)}
function pttRow(row){
 const el=document.createElement('div');el.className='ptt-row';
 const kind=String(row?.kind||'→'),kindEl=document.createElement('span');kindEl.className='ptt-kind'+(kind==='噓'?' boo':kind==='→'?' arrow':'');kindEl.textContent=kind;
 const when=new Date(String(row?.occurred_at||'')),time=document.createElement('span');time.className='ptt-time';
 if(Number.isFinite(when.getTime()))time.textContent=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(when);
 const floor=document.createElement('span');floor.className='ptt-floor';floor.textContent=Number.isInteger(row?.floor)&&row.floor>0?row.floor+'樓':'';
 const body=document.createElement('span');body.className='ptt-body';
 const author=document.createElement('span');author.className='ptt-author';author.textContent=String(row?.author||'unknown')+':';
 const content=document.createElement('span');content.className='ptt-content';content.textContent=String(row?.content||'');
 body.append(author,content);el.append(kindEl,time,floor,body);el.dataset.pushId=pttKey(row);return el;
}
function setPttRows(rows){
 pttRows=(Array.isArray(rows)?rows:[]).filter(row=>row&&typeof row.content==='string'&&Number.isFinite(Date.parse(String(row.occurred_at||'')))).sort((a,b)=>Date.parse(a.occurred_at)-Date.parse(b.occurred_at)||pttKey(a).localeCompare(pttKey(b)));
 pttVisible=0;pttFeed.replaceChildren();
}
function syncPttToHost(hostSeconds){
 if(!hostWindow||!pttRows.length||!Number.isFinite(hostSeconds))return;
 const absolute=Date.parse(hostWindow.start)+Math.max(0,hostSeconds)*1000;
 let low=0,high=pttRows.length;
 while(low<high){const mid=(low+high)>>1;if(Date.parse(pttRows[mid].occurred_at)<=absolute)low=mid+1;else high=mid}
 if(low===pttVisible)return;
 if(low>pttVisible){const frag=document.createDocumentFragment();for(let i=pttVisible;i<low;i++)frag.append(pttRow(pttRows[i]));pttFeed.append(frag)}
 else pttFeed.replaceChildren(...pttRows.slice(0,low).map(pttRow));
 pttVisible=low;
 if(pttFollowing)requestAnimationFrame(()=>{pttFeed.scrollTop=pttFeed.scrollHeight});
}
async function loadTodayPtt(day,windowInfo=null){
 pttTitle.textContent=windowInfo?'PTT 今日專串 · VOD':'PTT 今日專串';
 try{
  let data;try{data=await api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=1000')}catch{data=await api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=300')}
  if(!Array.isArray(data?.pushes))throw new Error('資料格式錯誤');
  const rows=windowInfo?data.pushes.filter(row=>{const t=Date.parse(String(row?.occurred_at||''));return Number.isFinite(t)&&t>=Date.parse(windowInfo.start)-3600000&&t<Date.parse(windowInfo.end)}):data.pushes;
  setPttRows(rows);pttMeta.textContent=day.replaceAll('-','/')+' · '+rows.length+' 則'+(windowInfo?' · 對齊播放時間':' · 即時');
  if(!windowInfo){pttFeed.replaceChildren(...pttRows.slice(-300).map(pttRow));pttFollowing=true;requestAnimationFrame(()=>{pttFeed.scrollTop=pttFeed.scrollHeight})}
 }catch(e){pttFeed.replaceChildren();const m=document.createElement('div');m.className='ptt-empty';m.textContent='PTT 暫時無法讀取：'+String(e?.message||e);pttFeed.append(m)}
}
function archiveHourKey(ms){const d=new Date(ms);return 'ptt/v1/chunks/'+d.getUTCFullYear()+'/'+String(d.getUTCMonth()+1).padStart(2,'0')+'/'+String(d.getUTCDate()).padStart(2,'0')+'/'+String(d.getUTCHours()).padStart(2,'0')+'00.json'}
function archiveHourKeys(startMs,endMs){const out=[];for(let t=Math.floor(startMs/3600000)*3600000;t<endMs;t+=3600000)out.push(archiveHourKey(t));return out}
async function archiveSha256Hex(buffer){const digest=await crypto.subtle.digest('SHA-256',buffer);return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('')}
async function fetchArchiveManifest(){
 if(archiveManifestCache)return archiveManifestCache;
 const r=await fetch(PTT_ARCHIVE_BASE+PTT_ARCHIVE_MANIFEST,{mode:'cors',credentials:'omit',cache:'no-cache'});
 if(!r.ok)throw new Error('歷史 PTT manifest HTTP '+r.status);
 const m=await r.json();if(m?.schema_version!==PTT_ARCHIVE_SCHEMA||!Array.isArray(m.objects))throw new Error('歷史 PTT manifest 格式不支援');
 archiveManifestCache=m;return m;
}
async function fetchArchiveChunk(item){
 const r=await fetch(PTT_ARCHIVE_BASE+'/'+item.key,{mode:'cors',credentials:'omit',cache:'no-cache'});
 if(!r.ok)throw new Error('歷史 PTT chunk HTTP '+r.status);
 const buffer=await r.arrayBuffer(),digest=await archiveSha256Hex(buffer);
 if(digest!==String(item.sha256||''))throw new Error('歷史 PTT chunk SHA 不符');
 const data=JSON.parse(new TextDecoder().decode(buffer));if(!Array.isArray(data?.pushes))throw new Error('歷史 PTT chunk 格式錯誤');return data.pushes;
}
async function loadArchivePtt(windowInfo){
 pttTitle.textContent='PTT 歷史專串';pttMeta.textContent='歷史資料 · 讀取中';
 try{
  const manifest=await fetchArchiveManifest(),objects=new Map(manifest.objects.map(item=>[item.key,item]));
  const startMs=Date.parse(windowInfo.start),endMs=Date.parse(windowInfo.end),rows=[];
  for(const key of archiveHourKeys(startMs-3600000,endMs)){const item=objects.get(key);if(!item)continue;for(const row of await fetchArchiveChunk(item)){const t=Date.parse(String(row?.occurred_at||''));if(Number.isFinite(t)&&t>=startMs-3600000&&t<endMs)rows.push(row)}}
  setPttRows(rows);pttMeta.textContent=taipeiDay(windowInfo.start).replaceAll('-','/')+' · '+rows.length+' 則 · VOD · 對齊播放時間';
 }catch(e){pttFeed.replaceChildren();const m=document.createElement('div');m.className='ptt-empty';m.textContent='歷史 PTT 暫時無法讀取：'+String(e?.message||e);pttFeed.append(m)}
}
async function resolveHostPtt(){
 if(!HOST_ID){pttMeta.textContent='缺少 Hololive 主影片';return}
 try{
  const row=await api('/v1/catalog/videos/'+encodeURIComponent(HOST_ID));
  const state=String(row?.lifecycle_state||row?.state||'').toLowerCase();
  hostStatus.textContent=state||'unknown';
  if(state==='live'){hostWindow=null;await loadTodayPtt(taipeiDay());pttTimer=setInterval(()=>{if(!document.hidden)loadTodayPtt(taipeiDay())},10000);return}
  const start=String(row?.actual_start||''),end=String(row?.actual_end||'');
  const startMs=Date.parse(start),endMs=Date.parse(end);
  if(state==='ended'&&Number.isFinite(startMs)&&Number.isFinite(endMs)&&endMs>startMs){
   hostWindow={start,end,anchorSource:PTT_ARCHIVE_ANCHOR};
   if(taipeiDay(start)===taipeiDay()&&taipeiDay(new Date(endMs-1))===taipeiDay())await loadTodayPtt(taipeiDay(),hostWindow);
   else await loadArchivePtt(hostWindow);
   return;
  }
  pttMeta.textContent=state==='upcoming'||state==='waiting'?'尚未開始':'無法取得可信直播時間';
 }catch{
  pttMeta.textContent='無法取得可信 lifecycle / actual time';
 }
}
resolveHostPtt();

window.addEventListener('pagehide',()=>{clearInterval(syncTimer);clearInterval(subtitleTimer);clearInterval(pttTimer)});
