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
const segmentPanel=document.getElementById('segmentPanel');
const segmentList=document.getElementById('segmentList');
const segmentMeta=document.getElementById('segmentMeta');
const subtitleOverlay=document.getElementById('subtitleOverlay');
const subtitleOriginal=document.getElementById('subtitleOriginal');
const subtitleTranslation=document.getElementById('subtitleTranslation');

let hostPlayer=null;
let sourcePlayer=null;
let sourceOffsetSeconds=Number(params.get('offset'))||0;
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
let activeSourceVideoId=SOURCE_ID||'';

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
function setOffset(value){
 sourceOffsetSeconds=Math.round((Number(value)||0)*10)/10;
 offsetValue.textContent='Offset '+(sourceOffsetSeconds>=0?'+':'')+sourceOffsetSeconds.toFixed(1)+'s';
 const q=new URLSearchParams(location.search);q.set('offset',String(sourceOffsetSeconds));history.replaceState(null,'',location.pathname+'?'+q.toString());
}
setOffset(sourceOffsetSeconds);

document.querySelectorAll('[data-watch-layout]').forEach(button=>button.addEventListener('click',()=>{
 const mode=button.dataset.watchLayout==='source'?'source':'equal';
 workspace.className='watchalong-workspace layout-'+mode;
 document.querySelectorAll('[data-watch-layout]').forEach(item=>{
  const active=item===button;item.classList.toggle('active',active);item.setAttribute('aria-pressed',String(active));
 });
}));
document.getElementById('offsetMinus').onclick=()=>setOffset(sourceOffsetSeconds-1);
document.getElementById('offsetPlus').onclick=()=>setOffset(sourceOffsetSeconds+1);
document.getElementById('captureOffset').onclick=()=>{
 try{
  const host=hostPlayer?.getCurrentTime?.(),source=sourcePlayer?.getCurrentTime?.();
  if(Number.isFinite(host)&&Number.isFinite(source))setOffset(source-host);
 }catch{}
};
document.getElementById('segmentToggle').onclick=()=>{
 segmentPanel.classList.toggle('collapsed');
 const expanded=!segmentPanel.classList.contains('collapsed');
 document.getElementById('segmentToggle').setAttribute('aria-expanded',String(expanded));
 document.getElementById('segmentToggle').textContent=expanded?'收合':'展開';
};
pttShowFloor.onchange=()=>pttPanel.classList.toggle('ptt-floor-hidden',!pttShowFloor.checked);
pttNewest.onclick=()=>{pttFollowing=true;pttFeed.scrollTop=pttFeed.scrollHeight;pttNewest.hidden=true};
pttFeed.addEventListener('scroll',()=>{
 pttFollowing=pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48;
 pttNewest.hidden=pttFollowing;
},{passive:true});
document.getElementById('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch{}};
document.addEventListener('fullscreenchange',()=>document.body.classList.toggle('immersive',Boolean(document.fullscreenElement)));

function onHostStateChange(event){
 if(!linkedPlayback.checked||!sourcePlayer||suppressLinkedCommand)return;
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
  if(PLAYLIST_ID){vars.listType='playlist';vars.list=PLAYLIST_ID}
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
  if(!linkedPlayback.checked)return;
  let host,source,state;
  try{host=hostPlayer.getCurrentTime();source=sourcePlayer.getCurrentTime();state=hostPlayer.getPlayerState()}catch{return}
  if(!Number.isFinite(host)||!Number.isFinite(source))return;
  const expected=Math.max(0,host+sourceOffsetSeconds);
  if(Math.abs(source-expected)>2.5){
   try{sourcePlayer.seekTo(expected,true)}catch{}
  }
  if(state===YT.PlayerState.PLAYING){
   try{if(sourcePlayer.getPlayerState()!==YT.PlayerState.PLAYING)sourcePlayer.playVideo()}catch{}
  }else if(state===YT.PlayerState.PAUSED){
   try{if(sourcePlayer.getPlayerState()===YT.PlayerState.PLAYING)sourcePlayer.pauseVideo()}catch{}
  }
  syncPttToHost(host);
 },500);
}
function startSubtitleLoop(){
 if(subtitleTimer)return;
 subtitleTimer=setInterval(()=>{
  let current=null;try{current=sourcePlayer?.getCurrentTime?.()}catch{}
  if(!Number.isFinite(current)||!subtitles.length){subtitleOverlay.hidden=true;return}
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
 segmentList.replaceChildren();
 segmentMeta.textContent=segments.length?segments.length+' 個段點 · 唯讀':'唯讀資料';
 if(!segments.length){const e=document.createElement('div');e.className='segment-empty';e.textContent='目前沒有可用段點；影片仍可正常播放。';segmentList.append(e);return}
 segments.forEach(segment=>{
  const button=document.createElement('button');button.type='button';button.className='segment-button';
  const strong=document.createElement('strong');strong.textContent=segment.label;
  const meta=document.createElement('span');meta.textContent='主持 '+clock(segment.host)+' · 片源 '+clock(segment.source);
  button.append(strong,meta);
  button.onclick=()=>jumpToSegment(segment,button);
  segmentList.append(button);
 });
}
function jumpToSegment(segment,button){
 try{hostPlayer?.seekTo?.(Math.max(0,segment.host),true)}catch{}
 try{
  if(segment.sourceVideoId&&segment.sourceVideoId!==activeSourceVideoId){
   activeSourceVideoId=segment.sourceVideoId;
   sourcePlayer?.loadVideoById?.({videoId:segment.sourceVideoId,startSeconds:Math.max(0,segment.source)});
  }else sourcePlayer?.seekTo?.(Math.max(0,segment.source),true);
 }catch{}
 setOffset(segment.source-segment.host);
 segmentList.querySelectorAll('.segment-button').forEach(item=>item.classList.toggle('active',item===button));
 if(linkedPlayback.checked){try{hostPlayer?.playVideo?.();sourcePlayer?.playVideo?.()}catch{}}
}
async function loadReadOnlyArtifacts(){
 if(!EVENT_ID)return;
 try{
  const data=await api('/v1/watchalong/events/'+encodeURIComponent(EVENT_ID));
  const payload=data?.event||data;
  segments=normalizeSegments(payload);
  subtitles=normalizeSubtitles(payload);
  renderSegments();
 }catch{
  segmentMeta.textContent='資料暫時無法讀取';
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
 const content=document.createElement('span');content.textContent=String(row?.content||'');
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
