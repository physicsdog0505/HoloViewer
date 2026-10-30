'use strict';

const config=window.HOLOVIEWER_CONFIG||{};
const API_BASE=String(config.apiBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_MONTHS=config.pttArchiveMonths||{};
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
const PTT_ARCHIVE_SCHEMA='ptt-r2-archive-v1';
const PTT_POLL_MS=60000;
const VOD_PTT_HISTORY_PAGE_CAP=20;
const params=new URLSearchParams(location.search);
let hostVideoId=validVideoId(params.get('host'));
let sourceVideoId=validVideoId(params.get('source'));
const PLAYLIST_ID=validPlaylistId(params.get('playlist'));
const EVENT_ID=String(params.get('watchalong_event')||params.get('event')||'').trim();
const STATIC_EVENT_MODE=Boolean(EVENT_ID);
const WATCHALONG_STATIC_BASE=String(config.watchalongStaticBase||'').replace(/\/$/,'');
const WATCHALONG_MANIFEST_PATH=WATCHALONG_STATIC_BASE+'/data/watchalong/manifest.json';

const workspace=document.getElementById('watchalongWorkspace');
const linkedPlayback=document.getElementById('linkedPlayback');
const offsetValue=document.getElementById('offsetValue');
const hostStatus=document.getElementById('hostStatus');
const hostMuteToggle=document.getElementById('hostMuteToggle');
const hostVolume=document.getElementById('hostVolume');
const hostVolumeValue=document.getElementById('hostVolumeValue');
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
const mobileControlsToggle=document.getElementById('mobileControlsToggle');
const mobileControlsPanel=document.getElementById('mobileControlsPanel');
const mobileControlsClose=document.getElementById('mobileControlsClose');
const mobilePrimarySource=document.getElementById('mobilePrimarySource');
const mobilePrimaryHost=document.getElementById('mobilePrimaryHost');
const mobileLinkedPlayback=document.getElementById('mobileLinkedPlayback');
const mobileStartSync=document.getElementById('mobileStartSync');
const mobileAlignNow=document.getElementById('mobileAlignNow');
const mobilePrevSegment=document.getElementById('mobilePrevSegment');
const mobileNextSegment=document.getElementById('mobileNextSegment');
const mobileSubtitleMode=document.getElementById('mobileSubtitleMode');
const mobileFullscreen=document.getElementById('mobileFullscreen');
const resumeStatus=document.getElementById('resumeStatus');
const segmentStatus=document.getElementById('segmentStatus');
const immersiveToolbarTrigger=document.getElementById('immersiveToolbarTrigger');
const topbar=document.querySelector('.watchalong-topbar');
const sourceStandby=document.getElementById('sourceStandby');
const subtitleOverlay=document.getElementById('subtitleOverlay');
const subtitleTranslation=document.getElementById('subtitleTranslation');
const sourceSubtitleOverlay=document.getElementById('sourceSubtitleOverlay');
const sourceSubtitleTranslation=document.getElementById('sourceSubtitleTranslation');
const subtitleComparison=document.getElementById('subtitleComparison');
const subtitleTranslationA=document.getElementById('subtitleTranslationA');
const subtitleTranslationB=document.getElementById('subtitleTranslationB');
const sourceSubtitleComparison=document.getElementById('sourceSubtitleComparison');
const sourceSubtitleTranslationA=document.getElementById('sourceSubtitleTranslationA');
const sourceSubtitleTranslationB=document.getElementById('sourceSubtitleTranslationB');
const localSubtitleFileA=document.getElementById('localSubtitleFileA');
const localSubtitleFileB=document.getElementById('localSubtitleFileB');
const localSubtitleNameA=document.getElementById('localSubtitleNameA');
const localSubtitleNameB=document.getElementById('localSubtitleNameB');
const localSubtitleClearA=document.getElementById('localSubtitleClearA');
const localSubtitleClearB=document.getElementById('localSubtitleClearB');
const localSubtitleStatus=document.getElementById('localSubtitleStatus');
const localSubtitleFontSize=document.getElementById('localSubtitleFontSize');
const localSubtitleFontValue=document.getElementById('localSubtitleFontValue');
const danmakuLayer=document.getElementById('danmakuLayer');

let hostPlayer=null;
let sourcePlayer=null;
let timelineAligned=false;
let segmentBaseOffsetSeconds=0;
let userOffsetSeconds=0;
let hostPlayerReady=false;
let sourcePlayerReady=false;
let suppressLinkedCommand=false;
let syncTimer=null;
let subtitleTimer=null;
let pttTimer=null;
let pttPrimeTimers=[];
let hostWindow=null;
let pttRows=[];
let pttVisible=0;
let pttFollowing=true;
let pttUserScrollIntentUntil=0;
const archiveManifestCache=new Map();
let segments=[];
let subtitles=[];
const localSubtitleSlots={A:null,B:null};
let localSubtitleMode='holodocchi';
let activeSegmentIndex=-1;
let activeSourceVideoId=sourceVideoId||'';
let sourceStandbyActive=false;
let sourceGapUntilHostSeconds=null;
let staticArtifactsReady=!STATIC_EVENT_MODE;
let staticArtifactsFailed=false;
let watchalongSessionDay='';
let subtitleTimeline='source';
let subtitleEnabled=true;
let danmakuEnabled=true;
let activeSubtitleCueId='';
let lastDanmakuCueId='';
let immersiveToolbarTimer=null;
let checkpointTimer=null;
let resumeApplied=false;
let resumePending=false;
const mobileWatchMedia=window.matchMedia('(max-width:760px)');
// PARKED: URL time restore/share is disabled. Local progress resume remains available.
let pendingResumeSeconds=null;

function validVideoId(value){const id=String(value||'');return /^[A-Za-z0-9_-]{11}$/.test(id)?id:''}
function validPlaylistId(value){const id=String(value||'');return /^[A-Za-z0-9_-]{10,64}$/.test(id)?id:''}
function api(path){
 if(!API_BASE||!/^https:\/\//.test(API_BASE))return Promise.reject(new Error('正式 API 未設定'));
 return fetch(API_BASE+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}}).then(r=>{if(!r.ok)throw new Error('API HTTP '+r.status);return r.json()});
}
async function metadataRead(videoId){
 const result=await window.HoloViewerVideoMetadata?.resolve(videoId,{
  apiBase:API_BASE,preferCatalog:true,waitForRecovery:true,maxAttempts:6,
  pttDay:/^\d{4}-\d{2}-\d{2}$/.test(watchalongSessionDay)?watchalongSessionDay:''
 });
 if(result?.status==='ready')return {status:200,payload:result.row};
 if(result?.status==='pending')return {status:202,payload:result.row||{status:'metadata_pending'}};
 if(result?.status==='not-found')return {status:404,payload:result.row||{error:'metadata_not_found_cached'}};
 return {status:result?.httpStatus||500,payload:result?.row||{error:result?.status||'metadata_error'}};
}
const WATCHALONG_MEMBER_ACCENTS=[
 [['ロボ子','ROBOCO'],'#d85a8a'],
 [['ときのそら','TOKINO SORA'],'#397fc4'],
 [['AZKI'],'#c94a52'],
 [['さくらみこ','SAKURA MIKO'],'#dc6f9f'],
 [['アキ・ローゼンタール','AKI ROSENTHAL'],'#69a56f'],
 [['白上フブキ','SHIRAKAMI FUBUKI'],'#4b97c8'],
 [['夏色まつり','NATSUIRO MATSURI'],'#d87932'],
 [['百鬼あやめ','NAKIRI AYAME'],'#c84b55'],
 [['癒月ちょこ','YUZUKI CHOCO','CHOCO CH.'],'#d85a8a'],
 [['大空スバル','OOZORA SUBARU'],'#a68118'],
 [['大神ミオ','OOKAMI MIO'],'#69a56f'],
 [['兎田ぺこら','USADA PEKORA','PEKORA CH.'],'#4b97c8'],
 [['不知火フレア','SHIRANUI FLARE'],'#d87932'],
 [['白銀ノエル','SHIROGANE NOEL'],'#7d7d7d'],
 [['宝鐘マリン','HOUSHOU MARINE'],'#c84b55'],
 [['天音かなた','AMANE KANATA'],'#4b97c8'],
 [['常闇トワ','TOKOYAMI TOWA'],'#7751a8'],
 [['雪花ラミィ','YUKIHANA LAMY'],'#4b97c8'],
 [['獅白ぼたん','SHISHIRO BOTAN'],'#7d7d7d'],
 [['尾丸ポルカ','OMARU POLKA'],'#c84b55']
];
function watchalongHostAccent(row){
 const audited=String(row?.member_accent||'');
 if(/^#[0-9a-fA-F]{6}$/.test(audited))return audited;
 const title=String(row?.channel_title||row?.channel_name||'').toUpperCase();
 for(const [needles,accent] of WATCHALONG_MEMBER_ACCENTS){
  if(needles.some(word=>title.includes(word.toUpperCase())))return accent;
 }
 return '#4b97c8';
}
function applyWatchalongHostAccent(row){
 document.documentElement.style.setProperty('--watchalong-host-accent',watchalongHostAccent(row));
}
function watchalongSubtitleSpeaker(row){
 return String(row?.speakerKey||row?.speakerId||row?.speaker||'').trim();
}
function watchalongSubtitleColor(row){
 const explicit=String(row?.speakerAccent||'');
 if(/^#[0-9a-fA-F]{6}$/.test(explicit))return explicit;
 const speaker=watchalongSubtitleSpeaker(row);
 if(speaker){
  const upper=speaker.toUpperCase();
  for(const [needles,accent] of WATCHALONG_MEMBER_ACCENTS){
   if(needles.some(word=>upper.includes(word.toUpperCase())))return accent;
  }
 }
 return 'var(--watchalong-host-accent,#4b97c8)';
}
function refreshHostVolumeUi(){
 let volume=Number(hostVolume?.value)||0,muted=false;
 try{
  const current=hostPlayer?.getVolume?.();
  if(Number.isFinite(current))volume=Math.max(0,Math.min(100,Math.round(current)));
  muted=Boolean(hostPlayer?.isMuted?.());
 }catch{}
 if(hostVolume)hostVolume.value=String(volume);
 if(hostVolumeValue)hostVolumeValue.textContent=volume+'%';
 if(hostMuteToggle){
  hostMuteToggle.textContent=muted||volume===0?'🔇':'🔊';
  hostMuteToggle.setAttribute('aria-pressed',String(muted));
 }
}
function setHostVolume(value){
 const volume=Math.max(0,Math.min(100,Math.round(Number(value)||0)));
 try{
  hostPlayer?.setVolume?.(volume);
  if(volume>0&&hostPlayer?.isMuted?.())hostPlayer.unMute?.();
 }catch{}
 if(hostVolume)hostVolume.value=String(volume);
 if(hostVolumeValue)hostVolumeValue.textContent=volume+'%';
 refreshHostVolumeUi();
}
hostVolume?.addEventListener('input',()=>setHostVolume(hostVolume.value));
hostMuteToggle?.addEventListener('click',()=>{
 try{
  if(hostPlayer?.isMuted?.())hostPlayer.unMute?.();
  else hostPlayer?.mute?.();
 }catch{}
 refreshHostVolumeUi();
});
function markPttUserScrollIntent(ms=1800){pttUserScrollIntentUntil=performance.now()+ms}
function hasPttUserScrollIntent(){return performance.now()<=pttUserScrollIntentUntil}
function pttAtBottom(){return pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48}
function syncPttFromHostNow(){
 if(!hostPlayer||!hostWindow||!pttRows.length)return false;
 try{
  const host=hostPlayer.getCurrentTime?.();
  if(Number.isFinite(host)){syncPttToHost(host);return true}
 }catch{}
 return false;
}
function primePttToHost(){
 pttPrimeTimers.forEach(clearTimeout);pttPrimeTimers=[];
 const delays=[0,120,400,1000];
 delays.forEach(delay=>{
  pttPrimeTimers.push(setTimeout(()=>{
   if(syncPttFromHostNow()&&pttVisible>0){
    pttPrimeTimers.forEach(clearTimeout);pttPrimeTimers=[];
   }
  },delay));
 });
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
function parseCheckpointSeconds(value){
 if(value==null||String(value).trim()==='')return null;
 const seconds=Number(value);
 return Number.isFinite(seconds)&&seconds>=0&&seconds<=604800?seconds:null;
}
function checkpointIdentity(){
 if(EVENT_ID)return 'event:'+EVENT_ID;
 if(hostVideoId)return 'host:'+hostVideoId;
 return '';
}
function checkpointStorageKey(){
 const identity=checkpointIdentity();
 return identity?'holodocchi-watchalong-progress-v1:'+identity:'';
}
function readSavedCheckpoint(){
 const key=checkpointStorageKey();if(!key)return null;
 try{
  const row=JSON.parse(localStorage.getItem(key)||'null');
  const seconds=parseCheckpointSeconds(row?.t);
  return seconds==null?null:seconds;
 }catch{return null}
}
function currentHostSeconds(){
 try{
  const seconds=hostPlayer?.getCurrentTime?.();
  return Number.isFinite(seconds)?Math.max(0,seconds):null;
 }catch{return null}
}
function saveCheckpoint(){
 const seconds=currentHostSeconds(),key=checkpointStorageKey();
 if(seconds==null||!key||seconds<3)return false;
 try{
  localStorage.setItem(key,JSON.stringify({t:Math.round(seconds*10)/10,updated_at:new Date().toISOString()}));
  return true;
 }catch{return false}
}
// Share-link checkpoint generation is intentionally disabled; browser autoplay/user-gesture
// restrictions can make a URL-restored time diverge from the actual player clock.
function setSegmentBaseOffset(value){
 segmentBaseOffsetSeconds=Math.round((Number(value)||0)*1000)/1000;
 timelineAligned=true;
 refreshOffsetUi();
}
function seekWatchalongToHost(seconds){
 if(!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer||!Number.isFinite(seconds))return false;
 const hostSeconds=Math.max(0,seconds);
 try{hostPlayer.seekTo(hostSeconds,true)}catch{return false}
 if(STATIC_EVENT_MODE&&segments.length){
  const index=segmentIndexForHost(hostSeconds);
  if(index>=0){
   activeSegmentIndex=index;
   const segment=segments[index],baseOffset=segment.source-segment.host;
   setSegmentBaseOffset(baseOffset);renderSegments();
   const target=sourceExpectedTime(hostSeconds);
   try{
    if(segment.sourceVideoId&&segment.sourceVideoId!==activeSourceVideoId){
     activeSourceVideoId=segment.sourceVideoId;sourceVideoId=segment.sourceVideoId;
     sourcePlayer.cueVideoById({videoId:segment.sourceVideoId,startSeconds:Math.max(0,target)});
    }else if(Number.isFinite(target)&&target>=0){
     sourcePlayer.seekTo(Math.max(0,target),true);
    }
   }catch{}
  }
 }else if(timelineAligned){
  const target=sourceExpectedTime(hostSeconds);
  if(Number.isFinite(target)&&target>=0){try{sourcePlayer.seekTo(target,true)}catch{}}
 }
 syncPttToHost(hostSeconds);
 return true;
}
function resumeClockApplied(targetSeconds){
 const actual=currentHostSeconds();
 return actual!=null&&Math.abs(actual-targetSeconds)<=2.5;
}
function verifyResumeClock(target,attempt=0){
 const delays=[120,400,1000];
 const delay=delays[Math.min(attempt,delays.length-1)];
 setTimeout(()=>{
  if(resumeApplied){resumePending=false;return}
  if(resumeClockApplied(target)){
   resumeApplied=true;
   resumePending=false;
   if(resumeStatus)resumeStatus.textContent='繼續上次位置 '+clock(target);
   return;
  }
  if(attempt+1<delays.length){verifyResumeClock(target,attempt+1);return}
  resumePending=false;
 },delay);
}
function maybeApplyResume(){
 if(resumeApplied||resumePending||!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer)return;
 if(pendingResumeSeconds==null){
  pendingResumeSeconds=readSavedCheckpoint();
  if(pendingResumeSeconds==null){resumeApplied=true;return}
 }
 const target=pendingResumeSeconds;
 resumePending=true;
 if(!seekWatchalongToHost(target)){resumePending=false;return}
 verifyResumeClock(target);
}
function startCheckpointLoop(){
 if(checkpointTimer)return;
 checkpointTimer=setInterval(()=>{if(!document.hidden)saveCheckpoint()},5000);
}
function refreshOffsetUi(){
 offsetValue.textContent='Offset '+(userOffsetSeconds>=0?'+':'')+userOffsetSeconds.toFixed(1)+'s';
 offsetMinus.disabled=!timelineAligned;
 offsetPlus.disabled=!timelineAligned;
}
function setOffset(value){
 userOffsetSeconds=Math.round((Number(value)||0)*10)/10;
 timelineAligned=true;
 refreshOffsetUi();
}
refreshOffsetUi();

function subtitleModeLabel(){
 if(subtitleEnabled&&danmakuEnabled)return '字幕＋彈幕';
 if(subtitleEnabled)return '字幕';
 if(danmakuEnabled)return '彈幕';
 return '關閉';
}
function clearDanmaku(){
 danmakuLayer?.replaceChildren();
 lastDanmakuCueId='';
}
function refreshSubtitleModeUi(){
 document.querySelectorAll('[data-subtitle-mode]').forEach(button=>{
  const mode=button.dataset.subtitleMode;
  const active=mode==='standard'?subtitleEnabled:mode==='danmaku'?danmakuEnabled:(!subtitleEnabled&&!danmakuEnabled);
  button.classList.toggle('active',active);
  button.setAttribute('aria-pressed',String(active));
 });
 if(mobileSubtitleMode)mobileSubtitleMode.textContent='字幕：'+subtitleModeLabel();
 if(!subtitleEnabled)subtitleOverlay.hidden=true;
 if(!subtitleEnabled||danmakuEnabled)sourceSubtitleOverlay.hidden=true;
 if(!danmakuEnabled)clearDanmaku();
}
function persistSubtitleMode(){
 try{
  localStorage.setItem('holoviewer-watchalong-subtitle-standard',subtitleEnabled?'1':'0');
  localStorage.setItem('holoviewer-watchalong-subtitle-danmaku',danmakuEnabled?'1':'0');
 }catch{}
}
function setWatchalongSubtitleFontSize(value,{persist=true}={}){
 const size=Math.max(18,Math.min(40,Math.round(Number(value)||28)));
 document.documentElement.style.setProperty('--watchalong-subtitle-font-size',size+'px');
 if(localSubtitleFontSize)localSubtitleFontSize.value=String(size);
 if(localSubtitleFontValue)localSubtitleFontValue.textContent=size+'px';
 if(persist){try{localStorage.setItem('holoviewer-subtitle-font-size',String(size))}catch{}}
 return size;
}
function readWatchalongSubtitleFontSize(){
 let value=28;
 try{value=Number(localStorage.getItem('holoviewer-subtitle-font-size'))||28}catch{}
 setWatchalongSubtitleFontSize(value,{persist:false});
}
function setSubtitleDisplay(mode,{persist=true}={}){
 if(mode==='standard')subtitleEnabled=!subtitleEnabled;
 else if(mode==='danmaku')danmakuEnabled=!danmakuEnabled;
 else if(mode==='off'){subtitleEnabled=false;danmakuEnabled=false}
 activeSubtitleCueId='';
 lastDanmakuCueId='';
 if(persist)persistSubtitleMode();
 refreshSubtitleModeUi();
}
document.querySelectorAll('[data-local-subtitle-mode]').forEach(button=>{
 button.addEventListener('click',()=>setLocalSubtitleMode(button.dataset.localSubtitleMode));
});
localSubtitleFileA?.addEventListener('change',async()=>{const file=localSubtitleFileA.files?.[0];await loadLocalSubtitle('A',file);localSubtitleFileA.value=''});
localSubtitleFileB?.addEventListener('change',async()=>{const file=localSubtitleFileB.files?.[0];await loadLocalSubtitle('B',file);localSubtitleFileB.value=''});
localSubtitleClearA?.addEventListener('click',()=>clearLocalSubtitle('A'));
localSubtitleClearB?.addEventListener('click',()=>clearLocalSubtitle('B'));
localSubtitleFontSize?.addEventListener('input',()=>setWatchalongSubtitleFontSize(localSubtitleFontSize.value));
readWatchalongSubtitleFontSize();
refreshLocalSubtitleUi();
try{
 const standard=localStorage.getItem('holoviewer-watchalong-subtitle-standard');
 const danmaku=localStorage.getItem('holoviewer-watchalong-subtitle-danmaku');
 if(standard==='0'||standard==='1')subtitleEnabled=standard==='1';
 if(danmaku==='0'||danmaku==='1')danmakuEnabled=danmaku==='1';
}catch{}
function closeMobileControls(){
 if(!mobileWatchMedia.matches)return;
 mobileControlsPanel.hidden=true;
 mobileControlsToggle.setAttribute('aria-expanded','false');
}
function refreshMobileControls(){
 if(!mobileWatchMedia.matches)return;
 mobileLinkedPlayback.textContent='連動播放：'+(linkedPlayback.checked?'開':'關');
 mobilePrevSegment.disabled=previousSegment.disabled;
 mobileNextSegment.disabled=nextSegment.disabled;
 if(mobileSubtitleMode)mobileSubtitleMode.textContent='字幕：'+subtitleModeLabel();
}
function openMobileControls(){
 if(!mobileWatchMedia.matches)return;
 refreshMobileControls();
 mobileControlsPanel.hidden=false;
 mobileControlsToggle.setAttribute('aria-expanded','true');
}
function mobileStartSynchronizedPlayback(){
 if(!mobileWatchMedia.matches||!hostPlayer||!sourcePlayer)return;
 let host=null,source=null;
 try{
  host=hostPlayer.getCurrentTime();
  source=sourcePlayer.getCurrentTime();
 }catch{return}
 if(!Number.isFinite(host)||!Number.isFinite(source))return;
 if(!timelineAligned)setOffset(source-host-segmentBaseOffsetSeconds);
 linkedPlayback.checked=true;
 refreshMobileControls();
 const expected=sourceExpectedTime(host);
 if(Number.isFinite(expected)&&expected<0){
  setSourceStandby(true);
  try{hostPlayer.playVideo()}catch{}
  closeMobileControls();
  return;
 }
 setSourceStandby(false);
 try{
  if(Number.isFinite(expected)&&Math.abs(source-expected)>1)sourcePlayer.seekTo(Math.max(0,expected),true);
  hostPlayer.playVideo();
  sourcePlayer.playVideo();
 }catch{}
 closeMobileControls();
}
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
mobileControlsToggle.onclick=()=>{if(mobileControlsPanel.hidden)openMobileControls();else closeMobileControls()};
mobileControlsClose.onclick=closeMobileControls;
mobilePrimarySource.onclick=()=>{if(!mobileWatchMedia.matches)return;setMobilePrimary('source');closeMobileControls()};
mobilePrimaryHost.onclick=()=>{if(!mobileWatchMedia.matches)return;setMobilePrimary('host');closeMobileControls()};
mobileLinkedPlayback.onclick=()=>{
 if(!mobileWatchMedia.matches)return;
 linkedPlayback.checked=!linkedPlayback.checked;
 refreshMobileControls();
};
mobileStartSync.onclick=mobileStartSynchronizedPlayback;
mobileAlignNow.onclick=()=>{if(!mobileWatchMedia.matches)return;document.getElementById('captureOffset').click();refreshMobileControls()};
mobilePrevSegment.onclick=()=>{if(!mobileWatchMedia.matches||previousSegment.disabled)return;previousSegment.click();refreshMobileControls()};
mobileNextSegment.onclick=()=>{if(!mobileWatchMedia.matches||nextSegment.disabled)return;nextSegment.click();refreshMobileControls()};
mobileSubtitleMode.onclick=()=>{
 if(!mobileWatchMedia.matches)return;
 if(subtitleEnabled&&!danmakuEnabled)danmakuEnabled=true;
 else if(subtitleEnabled&&danmakuEnabled)subtitleEnabled=false;
 else if(!subtitleEnabled&&danmakuEnabled)danmakuEnabled=false;
 else subtitleEnabled=true;
 persistSubtitleMode();
 activeSubtitleCueId='';
 lastDanmakuCueId='';
 refreshSubtitleModeUi();
 refreshMobileControls();
};
mobileFullscreen.onclick=()=>{if(!mobileWatchMedia.matches)return;fullscreenButton.click();closeMobileControls()};
document.addEventListener('pointerdown',event=>{
 if(!mobileWatchMedia.matches||mobileControlsPanel.hidden)return;
 if(mobileControlsPanel.contains(event.target)||mobileControlsToggle.contains(event.target))return;
 closeMobileControls();
},{passive:true});
mobileWatchMedia.addEventListener?.('change',event=>{if(!event.matches)mobileControlsPanel.hidden=true});
document.querySelectorAll('[data-subtitle-mode]').forEach(button=>button.addEventListener('click',()=>setSubtitleDisplay(button.dataset.subtitleMode)));
refreshSubtitleModeUi();
setMobilePrimary('source');
refreshMobileControls();
offsetMinus.onclick=()=>{if(timelineAligned)setOffset(userOffsetSeconds-1)};
offsetPlus.onclick=()=>{if(timelineAligned)setOffset(userOffsetSeconds+1)};
document.getElementById('captureOffset').onclick=()=>{
 try{
  const host=hostPlayer?.getCurrentTime?.(),source=sourcePlayer?.getCurrentTime?.();
  if(Number.isFinite(host)&&Number.isFinite(source))setOffset(source-host-segmentBaseOffsetSeconds);
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
 // Seeking can rebuild the PTT DOM and move scrollTop without user intent.
 // Only explicit PTT scroll gestures are allowed to change follow state.
 if(!hasPttUserScrollIntent())return;
 pttFollowing=pttAtBottom();
 pttNewest.hidden=pttFollowing;
},{passive:true});
pttFeed.addEventListener('wheel',event=>{
 markPttUserScrollIntent();
 if(event.deltaY<0){pttFollowing=false;pttNewest.hidden=false}
},{passive:true});
pttFeed.addEventListener('touchstart',()=>markPttUserScrollIntent(2400),{passive:true});
pttFeed.addEventListener('pointerdown',()=>markPttUserScrollIntent(2400),{passive:true});
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
 return hostSeconds+segmentBaseOffsetSeconds+userOffsetSeconds;
}
function staticSegmentStarts(){
 return segments.map(item=>({host_start_ms:item.host*1000}));
}
function sourceGapActive(hostSeconds){
 return Number.isFinite(sourceGapUntilHostSeconds)&&Number.isFinite(hostSeconds)&&hostSeconds<sourceGapUntilHostSeconds;
}
function maybeLatchSourceGap(hostSeconds,sourceState){
 if(!STATIC_EVENT_MODE||!segments.length||!Number.isFinite(hostSeconds))return false;
 if(sourceGapActive(hostSeconds))return true;
 const gapUntil=HoloViewerWatchalongStatic.interSegmentGapUntil(
  staticSegmentStarts(),
  activeSegmentIndex,
  hostSeconds,
  sourceState===YT.PlayerState.ENDED
 );
 if(!Number.isFinite(gapUntil))return false;
 sourceGapUntilHostSeconds=gapUntil;
 setSourceStandby(true,{rewind:false});
 return true;
}
function clearSourceGap(){
 sourceGapUntilHostSeconds=null;
}
function setSourceStandby(active){
 const {rewind=true}=arguments[1]||{};
 const next=Boolean(active);
 if(sourceStandbyActive===next)return;
 sourceStandbyActive=next;
 sourceStandby.hidden=!next;
 if(next){
  clearDanmaku();
  try{
   const state=sourcePlayer?.getPlayerState?.();
   if(state===YT.PlayerState.PLAYING||state===YT.PlayerState.BUFFERING)sourcePlayer.pauseVideo();
   if(rewind){
    const current=sourcePlayer?.getCurrentTime?.();
    if(Number.isFinite(current)&&current>0.75)sourcePlayer.seekTo(0,true);
   }
  }catch{}
 }
}
function onHostStateChange(event){
 if(event.data===YT.PlayerState.PAUSED||event.data===YT.PlayerState.ENDED)saveCheckpoint();
 if(!linkedPlayback.checked||!timelineAligned||!sourcePlayer||suppressLinkedCommand)return;
 let host=null;try{host=hostPlayer?.getCurrentTime?.()}catch{}
 if(Number.isFinite(host)&&sourceGapActive(host)){setSourceStandby(true,{rewind:false});return}
 if(Number.isFinite(host)&&sourceExpectedTime(host)<0){setSourceStandby(true);return}
 setSourceStandby(false);
 try{
  suppressLinkedCommand=true;
  if(event.data===YT.PlayerState.PLAYING)sourcePlayer.playVideo();
  else if(event.data===YT.PlayerState.PAUSED)sourcePlayer.pauseVideo();
 }catch{}finally{setTimeout(()=>{suppressLinkedCommand=false},0)}
}
function onSourceStateChange(event){
 if(event?.data!==YT.PlayerState.ENDED)return;
 let host=null;
 try{host=hostPlayer?.getCurrentTime?.()}catch{}
 if(!Number.isFinite(host))return;
 maybeLatchSourceGap(host,YT.PlayerState.ENDED);
}
function youtubePlayerErrorLabel(code){
 const labels={2:'無效影片參數',5:'播放器 HTML5 錯誤',100:'影片不存在或已設為私人',101:'影片禁止嵌入',150:'影片禁止嵌入'};
 return labels[Number(code)]||('播放器錯誤 '+String(code??'unknown'));
}
function mountPlayers(){
 if(!window.YT?.Player)return;
 if(hostVideoId&&!hostPlayer){
  hostPlayer=new YT.Player('hostPlayer',{
   videoId:hostVideoId,playerVars:{playsinline:1,rel:0,enablejsapi:1,origin:location.origin},
   events:{
    onStateChange:onHostStateChange,
    onReady:()=>{hostPlayerReady=true;hostStatus.textContent='已就緒';refreshHostVolumeUi();startSyncLoop();startCheckpointLoop();maybeApplyResume()},
    onError:event=>{hostPlayerReady=false;hostStatus.textContent=youtubePlayerErrorLabel(event?.data)}
   }
  });
 }else if(!hostVideoId){
  hostStatus.textContent='缺少 Hololive 主影片';
 }
 if(!sourcePlayer&&(sourceVideoId||PLAYLIST_ID)){
  const vars={playsinline:1,rel:0,enablejsapi:1,origin:location.origin};
  if(PLAYLIST_ID){
   vars.listType='playlist';vars.list=PLAYLIST_ID;
   const playlistStart=Math.max(1,Number(params.get('playlist_start'))||1);
   vars.index=playlistStart-1;
  }
  sourcePlayer=new YT.Player('sourcePlayer',{
   videoId:sourceVideoId||undefined,playerVars:vars,
   events:{
    onReady:()=>{sourcePlayerReady=true;sourceStatus.textContent=PLAYLIST_ID?'Playlist 已就緒':'片源已就緒';startSyncLoop();startSubtitleLoop();maybeApplyResume()},
    onStateChange:onSourceStateChange,
    onError:event=>{sourcePlayerReady=false;sourceStatus.textContent=youtubePlayerErrorLabel(event?.data)}
   }
  });
 }else if(!sourceVideoId&&!PLAYLIST_ID){
  sourceStatus.textContent='缺少 YouTube 片源';
 }
}
function maybeMountPlayers(){
 if(staticArtifactsFailed||!staticArtifactsReady)return;
 if(window.YT?.Player)mountPlayers();
}
window.onYouTubeIframeAPIReady=maybeMountPlayers;
if(window.YT?.Player)maybeMountPlayers();

function startSyncLoop(){
 if(syncTimer||!hostPlayerReady||!sourcePlayerReady||!hostPlayer||!sourcePlayer)return;
 syncTimer=setInterval(()=>{
  let host=null;
  try{host=hostPlayer.getCurrentTime()}catch{return}
  if(!Number.isFinite(host))return;
  syncPttToHost(host);
  if(STATIC_EVENT_MODE&&segments.length){
   const nextSegment=segmentIndexForHost(host);
   if(nextSegment>=0&&nextSegment!==activeSegmentIndex)applyStaticSegment(nextSegment,{seek:true});
  }
  if(sourceGapActive(host)){setSourceStandby(true,{rewind:false});return}
  if(!linkedPlayback.checked||!timelineAligned){setSourceStandby(false);return}
  const expected=sourceExpectedTime(host);
  if(!Number.isFinite(expected))return;
  if(expected<0){
   setSourceStandby(true);
   return;
  }
  setSourceStandby(false);
  let source,state,sourceState;
  try{source=sourcePlayer.getCurrentTime();state=hostPlayer.getPlayerState();sourceState=sourcePlayer.getPlayerState()}catch{return}
  if(!Number.isFinite(source))return;
  if(maybeLatchSourceGap(host,sourceState))return;
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
function subtitleCueAt(current){
 if(!Number.isFinite(current)||!subtitles.length)return null;
 let low=0,high=subtitles.length;
 while(low<high){
  const mid=(low+high)>>1;
  if(subtitles[mid].start<=current)low=mid+1;else high=mid;
 }
 const row=subtitles[Math.max(0,low-1)];
 return row&&current>=row.start&&current<row.end?row:null;
}
function localSubtitleTarget(){
 const timeline=subtitleTimeline==='host'?'host':'source';
 const videoId=timeline==='host'?hostVideoId:(activeSourceVideoId||sourceVideoId);
 return {timeline,videoId:validVideoId(videoId)};
}
function localSubtitleCurrentSeconds(timeline){
 try{
  const value=timeline==='host'?hostPlayer?.getCurrentTime?.():sourcePlayer?.getCurrentTime?.();
  return Number.isFinite(value)?value:null;
 }catch{return null}
}
function localSubtitleCue(slot,current){
 if(!slot||!window.HoloViewerLocalSubtitles)return null;
 return HoloViewerLocalSubtitles.cueAt(slot.cues,current);
}
function refreshLocalSubtitleUi(){
 const a=localSubtitleSlots.A,b=localSubtitleSlots.B;
 if(localSubtitleNameA)localSubtitleNameA.textContent=a?a.filename:'未載入';
 if(localSubtitleNameB)localSubtitleNameB.textContent=b?b.filename:'未載入';
 if(localSubtitleClearA)localSubtitleClearA.disabled=!a;
 if(localSubtitleClearB)localSubtitleClearB.disabled=!b;
 document.querySelectorAll('[data-local-subtitle-mode]').forEach(button=>{
  const mode=button.dataset.localSubtitleMode;
  const available=mode==='holodocchi'||mode==='A'&&Boolean(a)||mode==='B'&&Boolean(b)||mode==='A-B'&&Boolean(a&&b&&a.videoId===b.videoId&&a.timeline===b.timeline);
  button.disabled=!available;
  const active=mode===localSubtitleMode;
  button.classList.toggle('active',active);
  button.setAttribute('aria-pressed',String(active));
 });
}
function setLocalSubtitleStatus(message,{error=false}={}){
 if(!localSubtitleStatus)return;
 localSubtitleStatus.textContent=message||'';
 localSubtitleStatus.dataset.state=error?'error':'ok';
}
function setLocalSubtitleMode(mode){
 const a=localSubtitleSlots.A,b=localSubtitleSlots.B;
 if(mode==='A'&&!a)return false;
 if(mode==='B'&&!b)return false;
 if(mode==='A-B'&&(!a||!b||a.videoId!==b.videoId||a.timeline!==b.timeline))return false;
 localSubtitleMode=mode;
 activeSubtitleCueId='';
 lastDanmakuCueId='';
 clearDanmaku();
 refreshLocalSubtitleUi();
 return true;
}
async function loadLocalSubtitle(slotName,file){
 if(!file)return;
 try{
  if(!window.HoloViewerLocalSubtitles)throw new Error('本機字幕 parser 尚未載入');
  const target=localSubtitleTarget();
  if(!target.videoId)throw new Error('目前影片 ID 尚未就緒');
  const body=await file.text();
  const parsed=HoloViewerLocalSubtitles.parseLocalSubtitleFile(file.name,body,{expectedVideoId:target.videoId});
  if(parsed.videoId&&parsed.videoId!==target.videoId)throw new Error('字幕 video_id 與目前影片不符');
  const other=localSubtitleSlots[slotName==='A'?'B':'A'];
  if(other&&(other.videoId!==target.videoId||other.timeline!==target.timeline))
   throw new Error('A/B 必須是同一支影片與同一時間軸');
  localSubtitleSlots[slotName]={filename:file.name,format:parsed.format,cues:parsed.cues,videoId:target.videoId,timeline:target.timeline};
  setLocalSubtitleMode(slotName);
  setLocalSubtitleStatus(slotName+' 已載入：'+file.name+' · '+parsed.cues.length+' 段');
 }catch(error){
  setLocalSubtitleStatus(String(error?.message||error),{error:true});
 }
}
function clearLocalSubtitle(slotName){
 localSubtitleSlots[slotName]=null;
 if(localSubtitleMode===slotName||localSubtitleMode==='A-B')localSubtitleMode='holodocchi';
 activeSubtitleCueId='';lastDanmakuCueId='';clearDanmaku();
 setLocalSubtitleStatus(slotName+' 已清除');
 refreshLocalSubtitleUi();
}

function spawnDanmaku(row){
 if(!danmakuLayer||!row)return;
 const cueId=String(row.id||row.index||row.start);
 if(cueId===lastDanmakuCueId)return;
 lastDanmakuCueId=cueId;
 const text=String(row.translation||'').trim();
 if(!text)return;
 const item=document.createElement('div');
 item.className='danmaku-item';
 item.textContent=text;
 const lane=(Number(row.index)||0)%4;
 item.style.setProperty('--danmaku-top',(8+lane*18)+'%');
 item.style.setProperty('--danmaku-color','var(--watchalong-host-accent,#4b97c8)');
 const duration=Math.max(9,Math.min(18,9+text.length*0.09));
 item.style.setProperty('--danmaku-duration',duration.toFixed(1)+'s');
 item.addEventListener('animationend',()=>item.remove(),{once:true});
 danmakuLayer.append(item);
 while(danmakuLayer.children.length>8)danmakuLayer.firstElementChild?.remove();
}
function renderSubtitleCue(row){
 const cueId=row?String(row.id||row.index||row.start):'';
 if(subtitleTranslation)subtitleTranslation.hidden=false;
 if(sourceSubtitleTranslation)sourceSubtitleTranslation.hidden=false;
 if(subtitleComparison)subtitleComparison.hidden=true;
 if(sourceSubtitleComparison)sourceSubtitleComparison.hidden=true;
 if(subtitleEnabled){
  const text=row?.translation||'';
  subtitleTranslation.textContent=text;
  subtitleTranslation.style.color='#fff';
  subtitleTranslation.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(row));
  subtitleOverlay.hidden=!text;
  sourceSubtitleTranslation.textContent=text;
  sourceSubtitleTranslation.style.color='#fff';
  sourceSubtitleTranslation.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(row));
  sourceSubtitleOverlay.hidden=danmakuEnabled||!text;
 }else{
  subtitleOverlay.hidden=true;
  sourceSubtitleOverlay.hidden=true;
 }
 if(danmakuEnabled){
  if(!row){
   activeSubtitleCueId='';
   lastDanmakuCueId='';
  }else if(cueId!==activeSubtitleCueId){
   activeSubtitleCueId=cueId;
   spawnDanmaku(row);
  }
 }else{
  clearDanmaku();
  activeSubtitleCueId=cueId;
 }
}
function renderSubtitlePair(a,b){
 const aText=String(a?.translation||'').trim(),bText=String(b?.translation||'').trim();
 const hasText=Boolean(aText||bText);
 if(subtitleTranslation)subtitleTranslation.hidden=true;
 if(sourceSubtitleTranslation)sourceSubtitleTranslation.hidden=true;
 if(subtitleComparison)subtitleComparison.hidden=false;
 if(sourceSubtitleComparison)sourceSubtitleComparison.hidden=false;
 if(subtitleTranslationA){subtitleTranslationA.textContent=aText||'—';subtitleTranslationA.style.color='#fff';subtitleTranslationA.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(a))}
 if(subtitleTranslationB){subtitleTranslationB.textContent=bText||'—';subtitleTranslationB.style.color='#fff';subtitleTranslationB.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(b))}
 if(sourceSubtitleTranslationA){sourceSubtitleTranslationA.textContent=aText||'—';sourceSubtitleTranslationA.style.color='#fff';sourceSubtitleTranslationA.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(a))}
 if(sourceSubtitleTranslationB){sourceSubtitleTranslationB.textContent=bText||'—';sourceSubtitleTranslationB.style.color='#fff';sourceSubtitleTranslationB.style.setProperty('--subtitle-stroke-color',watchalongSubtitleColor(b))}
 subtitleOverlay.hidden=!subtitleEnabled||!hasText;
 sourceSubtitleOverlay.hidden=!subtitleEnabled||danmakuEnabled||!hasText;
 clearDanmaku();
 activeSubtitleCueId=(a?String(a.id||a.index||a.start):'')+'|'+(b?String(b.id||b.index||b.start):'');
}
function startSubtitleLoop(){
 if(subtitleTimer)return;
 subtitleTimer=setInterval(()=>{
  if(localSubtitleMode==='holodocchi'){
   let current=null;
   try{current=subtitleTimeline==='host'?hostPlayer?.getCurrentTime?.():sourcePlayer?.getCurrentTime?.()}catch{}
   if(!Number.isFinite(current)||!subtitles.length){renderSubtitleCue(null);return}
   renderSubtitleCue(subtitleCueAt(current));
   return;
  }
  if(localSubtitleMode==='A-B'){
   const a=localSubtitleSlots.A,b=localSubtitleSlots.B;
   const current=localSubtitleCurrentSeconds(a?.timeline);
   if(!Number.isFinite(current)||!a||!b){renderSubtitlePair(null,null);return}
   renderSubtitlePair(localSubtitleCue(a,current),localSubtitleCue(b,current));
   return;
  }
  const slot=localSubtitleSlots[localSubtitleMode];
  const current=localSubtitleCurrentSeconds(slot?.timeline);
  if(!Number.isFinite(current)||!slot){renderSubtitleCue(null);return}
  renderSubtitleCue(localSubtitleCue(slot,current));
 },200);
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
 return Array.isArray(raw)?raw.map((item,index)=>({
  id:String(item?.cue_id||item?.id||index),
  index,
  start:Number(item?.start??item?.start_seconds),end:Number(item?.end??item?.end_seconds),
  original:String(item?.original||item?.text||''),translation:String(item?.translation||item?.translated||''),
  speaker:String(item?.speaker||''),speakerId:String(item?.speaker_id||''),speakerKey:String(item?.speaker_key||''),
  speakerAccent:/^#[0-9a-fA-F]{6}$/.test(String(item?.speaker_accent||''))?String(item.speaker_accent):''
 })).filter(item=>Number.isFinite(item.start)&&Number.isFinite(item.end)&&item.end>item.start):[];
}
function renderSegments(){
 if(!segments.length){
  activeSegmentIndex=-1;
  segmentStatus.textContent='無段點';
  previousSegment.disabled=true;
  nextSegment.disabled=true;
  refreshMobileControls();
  return;
 }
 if(activeSegmentIndex<0||activeSegmentIndex>=segments.length)activeSegmentIndex=0;
 segmentStatus.textContent=segments[activeSegmentIndex].label+' · '+(activeSegmentIndex+1)+'/'+segments.length;
 previousSegment.disabled=activeSegmentIndex<=0;
 nextSegment.disabled=activeSegmentIndex>=segments.length-1;
 refreshMobileControls();
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
 setSegmentBaseOffset(segment.source-segment.host);
 renderSegments();
 if(linkedPlayback.checked){try{hostPlayer?.playVideo?.();sourcePlayer?.playVideo?.()}catch{}}
}
previousSegment.onclick=()=>jumpToSegmentIndex(activeSegmentIndex-1);
nextSegment.onclick=()=>jumpToSegmentIndex(activeSegmentIndex+1);
async function sha256Hex(buffer){
 const digest=await crypto.subtle.digest('SHA-256',buffer);
 return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
async function fetchStaticJson(path){
 const response=await fetch(path,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});
 if(!response.ok)throw new Error('HTTP '+response.status);
 const buffer=await response.arrayBuffer();
 let payload=null;
 try{payload=JSON.parse(new TextDecoder().decode(buffer))}catch{throw new Error('JSON 無效')}
 return {buffer,payload};
}
function failStaticEvent(error){
 staticArtifactsFailed=true;
 staticArtifactsReady=false;
 segments=[];subtitles=[];activeSegmentIndex=-1;
 segmentStatus.textContent='資料驗證失敗';
 hostStatus.textContent='Watchalong 資料無法使用';
 sourceStatus.textContent=String(error?.message||error||'驗證失敗');
 linkedPlayback.checked=false;
 subtitleOverlay.hidden=true;
 clearDanmaku();
 renderSegments();
}
function normalizeStaticSegments(payload){
 return payload.segments.map((item,index)=>({
  id:String(item.segment_id||index+1),
  label:String(item.label||('段點 '+(index+1))),
  host:Number(item.host_start_ms)/1000,
  source:Number(item.source_start_ms)/1000,
  sourceVideoId:validVideoId(item.source_video_id)
 }));
}
function normalizeStaticSubtitles(payload){
 return payload.subtitles.map((item,index)=>({
  id:String(item.cue_id||index),
  index,
  start:Number(item.start_ms)/1000,
  end:Number(item.end_ms)/1000,
  original:String(item.original||''),
  translation:String(item.translation||''),
  speaker:String(item.speaker||''),speakerId:String(item.speaker_id||''),speakerKey:String(item.speaker_key||''),
  speakerAccent:/^#[0-9a-fA-F]{6}$/.test(String(item.speaker_accent||''))?String(item.speaker_accent):''
 }));
}
function segmentIndexForHost(hostSeconds){
 if(!STATIC_EVENT_MODE||!segments.length||!Number.isFinite(hostSeconds))return -1;
 return HoloViewerWatchalongStatic.segmentIndexAt(
  segments.map(item=>({host_start_ms:item.host*1000})),
  hostSeconds
 );
}
function applyStaticSegment(index,{seek=true}={}){
 if(!STATIC_EVENT_MODE||index<0||index>=segments.length)return;
 clearSourceGap();
 setSourceStandby(false);
 activeSegmentIndex=index;
 const segment=segments[index];
 const baseOffset=segment.source-segment.host;
 setSegmentBaseOffset(baseOffset);
 renderSegments();
 if(!sourcePlayer)return;
 const hostNow=(()=>{try{return hostPlayer?.getCurrentTime?.()}catch{return null}})();
 const target=Number.isFinite(hostNow)?sourceExpectedTime(hostNow):segment.source+userOffsetSeconds;
 try{
  if(segment.sourceVideoId&&segment.sourceVideoId!==activeSourceVideoId){
   activeSourceVideoId=segment.sourceVideoId;
   sourceVideoId=segment.sourceVideoId;
   const playing=hostPlayer?.getPlayerState?.()===YT.PlayerState.PLAYING;
   const spec={videoId:segment.sourceVideoId,startSeconds:Math.max(0,target)};
   if(playing)sourcePlayer.loadVideoById(spec);else sourcePlayer.cueVideoById(spec);
  }else if(seek&&Number.isFinite(target)&&target>=0){
   sourcePlayer.seekTo(Math.max(0,target),true);
  }
 }catch{}
}
async function loadReadOnlyArtifacts(){
 if(!STATIC_EVENT_MODE){staticArtifactsReady=true;maybeMountPlayers();return}
 try{
  if(!window.HoloViewerWatchalongStatic)throw new Error('Static verifier missing');
  const manifestResult=await fetchStaticJson(WATCHALONG_MANIFEST_PATH);
  const entry=HoloViewerWatchalongStatic.manifestEntry(manifestResult.payload,EVENT_ID);
  const eventResult=await fetchStaticJson(WATCHALONG_STATIC_BASE+entry.path);
  const digest=await sha256Hex(eventResult.buffer);
  HoloViewerWatchalongStatic.verifyDigest(digest,entry.sha256);
  const payload=HoloViewerWatchalongStatic.validateEvent(entry,eventResult.payload);

  hostVideoId=validVideoId(payload.master_video_id);
  sourceVideoId=validVideoId(payload.segments[0].source_video_id);
  activeSourceVideoId=sourceVideoId;
  segments=normalizeStaticSegments(payload);
  subtitles=normalizeStaticSubtitles(payload);
  watchalongSessionDay=String(payload.session_day||'');
  subtitleTimeline='host';
  if(pendingResumeSeconds==null)pendingResumeSeconds=readSavedCheckpoint();
  activeSegmentIndex=pendingResumeSeconds==null?0:Math.max(0,segmentIndexForHost(pendingResumeSeconds));
  const initialSegment=segments[activeSegmentIndex]||segments[0];
  sourceVideoId=validVideoId(initialSegment.sourceVideoId)||sourceVideoId;
  activeSourceVideoId=sourceVideoId;
  setSegmentBaseOffset(initialSegment.source-initialSegment.host);
  renderSegments();

  staticArtifactsReady=true;
  maybeMountPlayers();
 }catch(error){
  failStaticEvent(error);
 }
}
renderSegments();
const staticArtifactsPromise=loadReadOnlyArtifacts();

function pttKey(row){return String(row?.source_record_key||row?.push_id||row?.aid+':'+row?.source_line)}
function pttRow(row){
 const el=document.createElement('div');el.className='ptt-row';
 const kind=String(row?.kind||'→'),kindEl=document.createElement('span');kindEl.className='ptt-kind'+(kind==='噓'?' boo':kind==='→'?' arrow':'');kindEl.textContent=kind;
 const when=new Date(String(row?.occurred_at||'')),time=document.createElement('span');time.className='ptt-time';
 if(Number.isFinite(when.getTime()))time.textContent=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(when);
 const floor=document.createElement('span');floor.className='ptt-floor';floor.textContent=Number.isInteger(row?.floor)&&row.floor>0?row.floor+'樓':'';
 const body=document.createElement('span');body.className='ptt-body';
 const author=document.createElement('span');author.className='ptt-author';author.textContent=String(row?.author||'unknown')+':';
 const content=document.createElement('span');content.className='ptt-content';
 if(window.HOLOVIEWER_PTT_LINKS?.appendLinkedContent)window.HOLOVIEWER_PTT_LINKS.appendLinkedContent(content,row?.content);
 else content.textContent=String(row?.content||'');
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
  if(windowInfo)primePttToHost();
  if(!windowInfo){pttFeed.replaceChildren(...pttRows.slice(-300).map(pttRow));pttFollowing=true;requestAnimationFrame(()=>{pttFeed.scrollTop=pttFeed.scrollHeight})}
 }catch(e){pttFeed.replaceChildren();const m=document.createElement('div');m.className='ptt-empty';m.textContent='PTT 暫時無法讀取：'+String(e?.message||e);pttFeed.append(m)}
}
async function archiveSha256Hex(buffer){const digest=await crypto.subtle.digest('SHA-256',buffer);return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('')}
function archiveIntegrityError(message){
 const error=new Error(message);error.archiveIntegrity=true;return error;
}
function archiveUnavailableError(message){
 const error=new Error(message);error.archiveUnavailable=true;return error;
}
function nextIsoDay(day){
 const date=new Date(day+'T00:00:00Z');
 if(!Number.isFinite(date.getTime()))return '';
 date.setUTCDate(date.getUTCDate()+1);
 return date.toISOString().slice(0,10);
}
function archiveCoverageDays(startMs,endMs){
 const first=taipeiDay(new Date(startMs));
 const last=taipeiDay(new Date(endMs-1));
 if(!first||!last)return [];
 const days=[];for(let day=first;day&&day<=last;day=nextIsoDay(day))days.push(day);
 return days;
}
function archiveSourceForMonth(month){
 const raw=PTT_ARCHIVE_MONTHS?.[month];
 const base=String(raw?.base||'').replace(/\/$/,'');
 const manifest=String(raw?.manifest||'');
 if(!/^\d{4}-\d{2}$/.test(month)||!/^https:\/\//.test(base)||!manifest.startsWith('/'))return null;
 return {month,base,manifest};
}
function archiveObjectRange(item){
 const startRaw=item?.partition_start??item?.range_start??item?.bucket_start;
 const endRaw=item?.partition_end??item?.range_end??item?.bucket_end;
 const startMs=Date.parse(String(startRaw||'')),endMs=Date.parse(String(endRaw||''));
 if(!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)return null;
 return {startMs,endMs};
}
function archiveObjectPushCount(item){
 const value=item?.push_count??item?.pushes;
 return Number.isInteger(value)&&value>=0?value:null;
}
function archiveRangesIntersect(aStart,aEnd,bStart,bEnd){
 return Number.isFinite(aStart)&&Number.isFinite(aEnd)&&Number.isFinite(bStart)&&Number.isFinite(bEnd)&&
  aStart<bEnd&&bStart<aEnd;
}
function validateArchiveManifest(manifest){
 if(manifest?.schema_version!==PTT_ARCHIVE_SCHEMA||manifest?.precision!=='minute'||
    manifest?.timezone!=='UTC'||!Array.isArray(manifest?.objects)||!Array.isArray(manifest?.days))
  throw archiveIntegrityError('歷史 PTT manifest 格式不支援');
 const seen=new Set();
 for(const item of manifest.objects){
  const range=archiveObjectRange(item),pushCount=archiveObjectPushCount(item);
  if(!item||typeof item.key!=='string'||!item.key.endsWith('.json')||seen.has(item.key)||
     !/^[0-9a-f]{64}$/.test(String(item.sha256||''))||!range||pushCount===null)
    throw archiveIntegrityError('歷史 PTT manifest 物件索引無效');
  seen.add(item.key);
 }
 return manifest;
}
async function fetchArchiveManifest(source,force=false){
 const cacheKey=source.month+'|'+source.base+'|'+source.manifest;
 if(archiveManifestCache.has(cacheKey)&&!force)return archiveManifestCache.get(cacheKey);
 const url=source.base+source.manifest;
 let response;
 try{response=await fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}})}
 catch(error){throw archiveUnavailableError('歷史 PTT '+source.month+' manifest 無法讀取：'+String(error?.message||error))}
 if(!response.ok)throw archiveUnavailableError('歷史 PTT '+source.month+' manifest HTTP '+response.status);
 const contentType=String(response.headers.get('content-type')||'').toLowerCase();
 if(!contentType.startsWith('application/json'))throw archiveIntegrityError('歷史 PTT '+source.month+' manifest Content-Type 不符');
 let manifest;
 try{manifest=validateArchiveManifest(await response.json())}
 catch(error){if(error?.archiveIntegrity)throw error;throw archiveIntegrityError('歷史 PTT '+source.month+' manifest JSON 無效')}
 archiveManifestCache.set(cacheKey,manifest);return manifest;
}
async function fetchArchiveObject(source,item){
 const url=source.base+'/'+item.key;
 let response;
 try{response=await fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}})}
 catch(error){throw archiveUnavailableError('歷史 PTT '+source.month+' object 無法讀取：'+String(error?.message||error))}
 if(!response.ok)throw archiveUnavailableError('歷史 PTT '+source.month+' object HTTP '+response.status);
 const contentType=String(response.headers.get('content-type')||'').toLowerCase();
 if(!contentType.startsWith('application/json'))throw archiveIntegrityError('歷史 PTT '+source.month+' object Content-Type 不符');
 const buffer=await response.arrayBuffer(),digest=await archiveSha256Hex(buffer);
 if(digest!==String(item.sha256||''))throw archiveIntegrityError('歷史 PTT '+source.month+' object SHA 不符');
 let payload;
 try{payload=JSON.parse(new TextDecoder().decode(buffer))}catch{throw archiveIntegrityError('歷史 PTT '+source.month+' object JSON 無效')}
 const expectedRange=archiveObjectRange(item),payloadRange=archiveObjectRange(payload);
 const expectedCount=archiveObjectPushCount(item);
 if(payload?.schema_version!==PTT_ARCHIVE_SCHEMA||!Array.isArray(payload?.pushes)||
    payload.pushes.length!==expectedCount)throw archiveIntegrityError('歷史 PTT '+source.month+' object push count 不符');
 if(!expectedRange||!payloadRange||expectedRange.startMs!==payloadRange.startMs||expectedRange.endMs!==payloadRange.endMs)
  throw archiveIntegrityError('歷史 PTT '+source.month+' object range 不符');
 return payload.pushes;
}
function archiveDayCoverageStatus(manifest,day){
 const row=Array.isArray(manifest?.days)?manifest.days.find(item=>String(item?.day||'')===String(day||'')):null;
 const status=String(row?.coverage_status||'MISSING');
 return ['COMPLETE','PARTIAL','MISSING','UNKNOWN'].includes(status)?status:'UNKNOWN';
}
function taipeiDayStartMs(day){
 const ms=Date.parse(String(day||'')+'T00:00:00+08:00');
 return Number.isFinite(ms)?ms:null;
}
function archiveRowIdentity(row){
 const stable=String(row?.source_record_key||row?.push_id||'');
 if(stable)return stable;
 const aid=String(row?.aid||''),line=Number(row?.source_line);
 if(aid&&Number.isInteger(line)&&line>=0)return aid+'|source_line:'+line;
 return String(row?.occurred_at||'')+'|'+String(row?.author||row?.user||'')+'|'+String(row?.content||row?.text||'');
}
function dedupeArchiveRows(rows){
 const sorted=(Array.isArray(rows)?rows:[]).slice().sort((a,b)=>
  Date.parse(String(a?.occurred_at||''))-Date.parse(String(b?.occurred_at||''))||
  String(a?.aid||'').localeCompare(String(b?.aid||''))||
  (Number(a?.source_line)||0)-(Number(b?.source_line)||0)||
  String(a?.push_id||'').localeCompare(String(b?.push_id||'')));
 const seen=new Set(),out=[];
 for(const row of sorted){const key=archiveRowIdentity(row);if(!key||seen.has(key))continue;seen.add(key);out.push(row)}
 return out;
}
function archiveObjectPlan(source,manifest,startMs,endMs){
 return manifest.objects.map(item=>({source,item,range:archiveObjectRange(item)}))
  .filter(entry=>entry.range&&archiveRangesIntersect(entry.range.startMs,entry.range.endMs,startMs,endMs))
  .sort((a,b)=>a.range.startMs-b.range.startMs||a.range.endMs-b.range.endMs||String(a.item.key).localeCompare(String(b.item.key)));
}
async function resolveArchiveDaySlice(day,rangeStart,rangeEnd){
 const month=String(day||'').slice(0,7),source=archiveSourceForMonth(month);
 if(!source)throw archiveUnavailableError('歷史 PTT 月份來源未設定：'+month);
 let lastError=null;
 for(let attempt=0;attempt<2;attempt++){
  try{
   const manifest=await fetchArchiveManifest(source,attempt===1);
   const coverageStatus=archiveDayCoverageStatus(manifest,day);
   const rows=[];
   for(const entry of archiveObjectPlan(source,manifest,rangeStart,rangeEnd)){
    const pushes=await fetchArchiveObject(entry.source,entry.item);
    for(const row of pushes){
     const occurred=Date.parse(String(row?.occurred_at||''));
     if(Number.isFinite(occurred)&&occurred>=rangeStart&&occurred<rangeEnd)rows.push(row);
    }
   }
   return {day,coverageStatus,rows:dedupeArchiveRows(rows)};
  }catch(error){
   lastError=error;
   if(attempt===0&&error?.archiveIntegrity){archiveManifestCache.clear();continue}
   break;
  }
 }
 throw lastError||archiveUnavailableError('歷史 PTT '+day+' 無法讀取');
}
async function loadPttDayWindowRows(day,startMs,endMs){
 const rows=[],seenCheckpoints=new Set();
 let after='',pages=0,lastEnvelope=null,reachedEnd=false;
 while(pages<VOD_PTT_HISTORY_PAGE_CAP){
  const path='/v1/ptt/history?day='+encodeURIComponent(day)+'&limit=200'+(after?'&after='+encodeURIComponent(after):'');
  const data=await api(path);
  if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes)||
     !data.page||typeof data.page.has_more!=='boolean')throw new Error('PTT history 資料格式錯誤');
  lastEnvelope=data;pages+=1;
  for(const row of data.pushes){
   if(!row||typeof row.content!=='string')continue;
   const occurred=Date.parse(String(row.occurred_at||''));
   if(!Number.isFinite(occurred))continue;
   if(occurred>=endMs){reachedEnd=true;break}
   if(occurred>=startMs)rows.push(row);
  }
  if(reachedEnd||!data.page.has_more)break;
  const next=String(data.page.next_checkpoint||'');
  if(!next||seenCheckpoints.has(next))throw new Error('PTT history continuation 無法前進');
  seenCheckpoints.add(next);after=next;
 }
 return {rows:dedupeArchiveRows(rows),incomplete:!reachedEnd&&Boolean(lastEnvelope?.page?.has_more)};
}
async function resolveCoverageDrivenWatchalongPtt(windowInfo){
 const startMs=Date.parse(windowInfo.start),endMs=Date.parse(windowInfo.end);
 if(!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)throw new Error('PTT VOD 時間範圍無效');
 const fetchStartMs=startMs-3600000;
 const days=archiveCoverageDays(fetchStartMs,endMs),rows=[],results=[];
 for(const day of days){
  const dayStart=taipeiDayStartMs(day),nextStart=taipeiDayStartMs(nextIsoDay(day));
  if(!Number.isFinite(dayStart)||!Number.isFinite(nextStart))continue;
  const rangeStart=Math.max(fetchStartMs,dayStart),rangeEnd=Math.min(endMs,nextStart);
  if(rangeEnd<=rangeStart)continue;
  let archive=null,d1=null,archiveError=null,d1Error=null;
  try{archive=await resolveArchiveDaySlice(day,rangeStart,rangeEnd)}catch(error){archiveError=error}
  if(!archive||archive.coverageStatus!=='COMPLETE'){
   try{d1=await loadPttDayWindowRows(day,rangeStart,rangeEnd)}catch(error){d1Error=error}
  }
  if(archive?.rows?.length)rows.push(...archive.rows);
  if(d1?.rows?.length)rows.push(...d1.rows);
  results.push({day,archive,d1,archiveError,d1Error});
 }
 return {
  rows:dedupeArchiveRows(rows),
  days:results.map(item=>item.day),
  allArchiveComplete:results.length>0&&results.every(item=>item.archive?.coverageStatus==='COMPLETE'),
  d1Days:results.filter(item=>item.d1).map(item=>item.day),
  incompleteDays:results.filter(item=>item.d1?.incomplete).map(item=>item.day),
  unresolvedDays:results.filter(item=>!item.archive&&!item.d1).map(item=>item.day)
 };
}
async function loadArchivePtt(windowInfo){
 pttTitle.textContent='PTT 歷史專串';pttMeta.textContent='歷史資料 · 判定每日 coverage';
 try{
  const result=await resolveCoverageDrivenWatchalongPtt(windowInfo);
  setPttRows(result.rows);
  let sourceLabel=result.allArchiveComplete?'歷史封存完整':
   result.d1Days.length?'Archive + D1':'Archive coverage 尚未 COMPLETE';
  if(result.incompleteDays.length)sourceLabel+=' · ⚠ D1 分頁上限';
  if(result.unresolvedDays.length)sourceLabel+=' · ⚠ UNKNOWN / UNAVAILABLE';
  pttMeta.textContent=result.days.join('～').replaceAll('-','/')+' · '+result.rows.length+' 則 · VOD · '+sourceLabel;
  primePttToHost();
  if(!result.rows.length&&!result.allArchiveComplete){
   pttFeed.replaceChildren();
   const m=document.createElement('div');m.className='ptt-empty';
   m.textContent='目前沒有取得可顯示推文；Archive 尚未 COMPLETE，不能宣稱這段真正沒有推文。';
   pttFeed.append(m);
  }
 }catch(e){
  pttFeed.replaceChildren();const m=document.createElement('div');m.className='ptt-empty';
  m.textContent='歷史 PTT 暫時無法讀取：'+String(e?.message||e);pttFeed.append(m);
 }
}
async function resolveHostPtt(){
 if(!hostVideoId){pttMeta.textContent='缺少 Hololive 主影片';return}
 try{
  const result=await metadataRead(hostVideoId);
  const row=result.payload||{};
  if(result.status===202&&row.status==='metadata_pending'){
   hostStatus.textContent='metadata_pending';
   pttMeta.textContent='影片時間資料補查中，稍後可重新進入或重新整理';
   return;
  }
  if(result.status===404&&row.error==='metadata_not_found_cached'){
   hostStatus.textContent='unknown';
   pttMeta.textContent='找不到可信的 YouTube 直播時間資料';
   return;
  }
  if(result.status!==200)throw new Error(row.error||('metadata HTTP '+result.status));

  const state=String(row?.lifecycle_state||row?.state||'').toLowerCase();
  applyWatchalongHostAccent(row);
  hostStatus.textContent=state||'unknown';
  if(state==='live'){
   hostWindow=null;
   await loadTodayPtt(taipeiDay());
   clearInterval(pttTimer);
   pttTimer=setInterval(()=>{if(!document.hidden)loadTodayPtt(taipeiDay())},PTT_POLL_MS);
   return;
  }
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
staticArtifactsPromise.then(()=>{
 if(!staticArtifactsFailed)resolveHostPtt();
});

document.addEventListener('visibilitychange',()=>{
 if(!document.hidden&&hostStatus.textContent==='live')loadTodayPtt(taipeiDay());
});
window.addEventListener('pagehide',()=>{
 saveCheckpoint();
 clearInterval(syncTimer);clearInterval(subtitleTimer);clearInterval(pttTimer);clearInterval(checkpointTimer);
 pttPrimeTimers.forEach(clearTimeout);pttPrimeTimers=[];
});
