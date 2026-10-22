'use strict';

const API_BASE=String(window.HOLOVIEWER_CONFIG?.apiBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_MONTHS=window.HOLOVIEWER_CONFIG?.pttArchiveMonths||{};
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
const PTT_ARCHIVE_SCHEMA='ptt-r2-archive-v1';
const PTT_POLL_MS=60000;
const VOD_PTT_HISTORY_PAGE_CAP=20;
const params=new URLSearchParams(location.search);
const MAX_STREAMS=16;
const FOCUS_VISIBLE_SLOTS=4;
const HOME_FILTER_KEY='holoviewer-live-filter';
const HOME_FILTERS=new Set(['hololive','holostars','mekpark','all']);
const streams=[...new Set(params.getAll('stream').filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))].slice(0,MAX_STREAMS).map(id=>({videoId:id,label:id,channelId:''}));
let layout=['equal','primary'].includes(params.get('layout'))?params.get('layout'):'equal';
let workspaceLayout=['sidebar','focus'].includes(params.get('workspace'))?params.get('workspace'):'sidebar';
let primaryIndex=Math.max(0,Math.min(Math.max(0,streams.length-1),Number(params.get('primary'))||0));
let audioMaster=primaryIndex;
let watchMode=params.get('mode')==='multi'||streams.length>1?'multi':'single';
const requestedPttMode=params.get('ptt')||'live';
const collabEventId=String(params.get('collab_event')||'');
const collabKind=['live','vod'].includes(params.get('collab_kind'))?params.get('collab_kind'):'';
const collabDay=/^\d{4}-\d{2}-\d{2}$/.test(String(params.get('collab_day')||''))?String(params.get('collab_day')):'';
const collabSyncVerified=collabKind==='vod'&&params.get('collab_sync')==='verified';
const collabManaged=Boolean(collabEventId&&collabKind);
function parseArchiveWindows(){
 const map=new Map();
 for(const raw of params.getAll('ptt_window')){
  const parts=String(raw).split('|');
  if(parts.length!==4&&parts.length!==5)continue;
  const [videoId,start,end,anchorSource,scheduledStart='']=parts;
  const startMs=Date.parse(start),endMs=Date.parse(end),scheduledMs=Date.parse(scheduledStart);
  if(!/^[A-Za-z0-9_-]{11}$/.test(videoId)||anchorSource!==PTT_ARCHIVE_ANCHOR||
     !Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)continue;
  map.set(videoId,{videoId,start,end,anchorSource,
   scheduledStart:Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000?scheduledStart:''});
 }
 return map;
}
const archiveWindows=parseArchiveWindows();
const archiveVodEntry=requestedPttMode==='video';

const stage=document.getElementById('stage');
const workspace=document.querySelector('.viewer-workspace');
const liveRail=document.getElementById('viewerLiveRail');
const liveList=document.getElementById('viewerLiveList');
const controls=document.getElementById('viewerControls');
const persistentPlaybackControls=document.getElementById('persistentPlaybackControls');
const settingsButton=document.getElementById('viewerSettings');
const callModeButton=document.getElementById('viewerCallMode');
const fullscreenButton=document.getElementById('viewerFullscreen');
const multiModeSwitch=document.getElementById('multiModeSwitch');
const focusChoices=document.getElementById('focusChoices');
const focusCarouselStatus=document.getElementById('focusCarouselStatus');
const syncPlayback=document.getElementById('syncPlayback');
const playAll=document.getElementById('playAll');
const pauseAll=document.getElementById('pauseAll');
const carousel=document.getElementById('focusCarousel');
const carouselControl=document.getElementById('carouselControl');
const carouselIntervalGroup=document.getElementById('carouselIntervalGroup');
const carouselInterval=document.getElementById('focusCarouselInterval');
const carouselOutput=document.getElementById('focusCarouselIntervalOutput');
const pttPanel=document.getElementById('pttPanel');
const pttFeed=document.getElementById('pttFeed');
const pttMeta=document.getElementById('pttMeta');
const pttTitle=document.getElementById('pttTitle');
const pttShowFloor=document.getElementById('pttShowFloor');
const pttNewest=document.getElementById('pttNewest');
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');

const players=[];
const playerCards=[];
let catalogRows=[];
const syncExpected=new WeakMap();
const timelineGapPovs=new Set();
let carouselTimer=null;
let lockedIndex=workspaceLayout==='focus'?primaryIndex:null;
// "focus" is accepted only as a legacy URL marker for Lock. Runtime geometry
// stays sidebar for both Carousel and Lock so PTT never changes containers/rows.
workspaceLayout='sidebar';
let secondaryOffset=0;
let pttFollowing=true;
let pttLoaded=false;
let pttLayoutRepinTimer=null;
let pttResizeFrame=null;
let pttLayoutTransitionDepth=0;
let pttUserScrollIntentUntil=0;
let pttResizeObserver=null;
let pttContext={mode:'unresolved',videoId:'',start:'',end:'',day:''};
let pttResolveToken=0;
let pttVodRows=[];
let pttVodPresentationTimes=[];
let pttVodVisibleCount=0;
let pttVodPollTimer=null;
let pttVodLastSample=null;
let pttVodHasPlayed=false;
let confirmedLiveIds=new Set();
let draggedLiveId='';
let collabEvent=null;
let collabRoster=new Map();
let collabPollTimer=null;
let collabVodTimer=null;
let collabAbsoluteMs=null;
let collabReconciling=false;
let viewingSession=null;
let viewingAdapter=null;
let viewingTimer=null;
let viewingReconciling=false;
let viewingLastUrlSecond=-1;
let viewingClockPovId='';
let viewingClockPolicy=null;
let viewingClockSample=null;
let viewingResyncPending=false;
let viewingVisiblePovs=null;
let viewingRunIntent=false;
const viewingTimelineCore=window.HoloViewerViewingTimeline||null;
// PARKED: share-link timeline restore is intentionally disabled because browser\n// autoplay/user-gesture rules can make URL-restored master time diverge from\n// the actual YouTube player clock. Keep timeline runtime, but never serialize/restore it.\nconst viewingShareState=null;
const viewingAdapterFactory=window.HoloViewerTimelineViewerAdapter||null;
function viewingTimelineActive(){return Boolean(viewingSession&&viewingAdapter)}

const CALL_DEFAULT_BEAT_MS=500;
let callEnabled=false;
let callBeatMs=CALL_DEFAULT_BEAT_MS;
let callTapTimes=[];
let callOverlay=null;
let callHud=null;
let callHeldDirection='';
let callDirectionStartedAt=0;
let callLastDirection='';
let callLastDirectionAt=0;
let callWaveTimer=null;
let callSpaceHeld=false;
let callWakeTaps=[];
let callAutoBeatTimer=null;
let callHintTimer=null;

function api(path){
 if(!API_BASE||!/^https:\/\//.test(API_BASE))return Promise.reject(new Error('正式 API 未設定'));
 return fetch(API_BASE+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}}).then(response=>{
  if(!response.ok)throw new Error('API HTTP '+response.status);
  return response.json();
 });
}
async function videoMetadata(id){
 const result=await window.HoloViewerVideoMetadata?.resolve(id,{
  apiBase:API_BASE,preferCatalog:true,waitForRecovery:true,maxAttempts:6
 });
 if(result?.status==='ready')return result.row;
 const error=new Error(result?.status||'metadata unavailable');
 error.metadataResult=result||null;
 throw error;
}
function node(tag,text,className){
 const el=document.createElement(tag);
 if(text!==undefined&&text!==null)el.textContent=String(text);
 if(className)el.className=className;
 return el;
}
function safeAvatar(raw){
 try{
  const u=new URL(String(raw||''));
  return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&['yt3.ggpht.com','i.ytimg.com'].includes(u.hostname)?u.href:'';
 }catch{return ''}
}
function catalogName(row){return String(row?.channel_title||row?.channel_name||row?.title||row?.video_id||'Hololive')}
function homeLiveFilter(){try{const value=localStorage.getItem(HOME_FILTER_KEY);return HOME_FILTERS.has(value)?value:'hololive'}catch{return 'hololive'}}
function catalogGroup(row){return String(row?.group||row?.channel_group||'other').toLowerCase()}
function accentFor(row){
 const audited=String(row?.member_accent||'');
 return /^#[0-9a-fA-F]{6}$/.test(audited)?audited:'#9ab8c4';
}
function streamCatalogRow(stream){
 return catalogRows.find(row=>String(row?.video_id||'')===String(stream?.videoId||''))||null;
}
function streamAvatarUrl(stream){
 return safeAvatar(stream?.avatarUrl||streamCatalogRow(stream)?.avatar_url||'');
}
function applyFocusAccent(button,stream){
 const row=streamCatalogRow(stream)||{};
 const accent=accentFor(row);
 button.style.setProperty('--member-accent',accent);
 const dual=Array.isArray(row?.member_accent_dual)?row.member_accent_dual:[];
 if(String(row?.support_mode||'')==='dual_color'&&dual.length===2&&dual.every(value=>/^#[0-9a-fA-F]{6}$/.test(String(value)))){
  button.dataset.supportMode='dual_color';
  button.style.setProperty('--member-accent-dual','linear-gradient(135deg,'+dual[0]+' 0 50%,'+dual[1]+' 50% 100%)');
 }
}
function currentLayoutPreset(){
 if(layout==='equal')return 'equal';
 return lockedIndex!==null?'focus':'primary';
}
function setLayoutPreset(preset){
 // Snapshot follow before ANY lock/carousel geometry mutation. renderControls()
 // changes focus classes before applyLayout(), which can fire a synthetic scroll
 // and falsely mark a live PTT feed as "not following".
 const wasFollowing=pttFollowing||pttAtBottom();
 pttLayoutTransitionDepth+=1;
 try{
  if(preset==='equal'){layout='equal';lockedIndex=null}
  else if(preset==='focus'){layout='primary';lockedIndex=primaryIndex}
  else{layout='primary';lockedIndex=null}
  workspaceLayout='sidebar';
  carousel.checked=preset!=='equal';
  secondaryOffset=0;
  renderControls();
  applyLayout();
  startCarousel();
 }finally{
  pttLayoutTransitionDepth=Math.max(0,pttLayoutTransitionDepth-1);
 }
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
}
function hideSettings(){
 document.body.classList.remove('settings-open');
 controls.hidden=true;
 settingsButton.classList.remove('active');
 settingsButton.setAttribute('aria-expanded','false');
}
function applyModeClass(){
 document.body.classList.toggle('mode-single',watchMode==='single');
 document.body.classList.toggle('mode-multi',watchMode==='multi');
 if(watchMode==='single'){
  hideSettings();
 }
}
function updateUrl(){
 const q=new URLSearchParams();
 streams.forEach(stream=>q.append('stream',stream.videoId));
 q.set('layout',layout);
 q.set('workspace',currentLayoutPreset()==='focus'?'focus':'sidebar');
 const resolvedPttMode=pttContext.mode==='live'?'live':(pttContext.mode==='vod'?'video':requestedPttMode);
 q.set('ptt',resolvedPttMode);
 archiveWindows.forEach(window=>q.append('ptt_window',[window.videoId,window.start,window.end,window.anchorSource,window.scheduledStart||''].join('|')));
 q.set('primary',String(primaryIndex));
 q.set('audio',String(primaryIndex));
 q.set('mode',watchMode);
 if(collabManaged){
  q.set('collab_event',collabEventId);
  q.set('collab_kind',collabKind);
  if(collabDay)q.set('collab_day',collabDay);
  if(collabSyncVerified)q.set('collab_sync','verified');
 }
 history.replaceState(null,'','/viewer/?'+q.toString());
}

function callEditableTarget(target){
 if(!(target instanceof Element))return false;
 return Boolean(target.closest('input,textarea,select,[contenteditable="true"]'));
}
function callBpm(){return Math.round(60000/Math.max(240,Math.min(1200,callBeatMs)))}
function callUpdateHud(label='待機'){
 if(!callOverlay)return;
 const beat=Math.round(callBeatMs);
 callOverlay.style.setProperty('--call-beat',beat+'ms');
 callOverlay.style.setProperty('--call-beat-2',beat*2+'ms');
 callOverlay.style.setProperty('--call-beat-4',beat*4+'ms');
 if(callHud)callHud.textContent='Call · '+callBpm()+' BPM · '+label;
}
function callHint(label){
 callUpdateHud(label);
 if(!callHud)return;
 callHud.classList.add('call-hint');
 clearTimeout(callHintTimer);
 callHintTimer=setTimeout(()=>callHud?.classList.remove('call-hint'),1300);
}
function stopCallAutoBeat(){
 clearInterval(callAutoBeatTimer);callAutoBeatTimer=null;
}
function startCallAutoBeat(){
 stopCallAutoBeat();
 if(callTapTimes.length<4)return;
 callPulseChest();
 callAutoBeatTimer=setInterval(()=>{
  if(!callEnabled)return;
  callPulseChest();
 },Math.max(240,Math.round(callBeatMs)));
 callHint('已鎖定 '+callBpm()+' BPM');
}
function callClearMotion(){
 if(!callOverlay)return;
 callOverlay.classList.remove('side-two-left','side-two-right','side-fast-left','side-fast-right','side-wave-left','side-wave-right','space-pump');
}
function ensureCallOverlay(){
 if(callOverlay&&callOverlay.isConnected)return callOverlay;
 const overlay=node('div',undefined,'call-overlay');
 overlay.id='viewerCallOverlay';
 overlay.setAttribute('aria-hidden','true');
 const hands=node('div',undefined,'call-hands');
 const left=node('div',undefined,'call-hand left');
 const right=node('div',undefined,'call-hand right');
 left.append(node('span',undefined,'call-stick'));
 right.append(node('span',undefined,'call-stick'));
 hands.append(left,right);
 callHud=node('div','Call · 120 BPM · 待機','call-hud');
 overlay.append(hands,callHud);
 callOverlay=overlay;
 callUpdateHud();
 mountCallOverlay();
 return overlay;
}
function mountCallOverlay(){
 if(!callOverlay)return;
 const card=playerCards[primaryIndex]||playerCards[0];
 if(card&&callOverlay.parentElement!==card)card.append(callOverlay);
}
function setCallMode(on,{hint=false}={}){
 callEnabled=Boolean(on);
 document.body.classList.toggle('call-mode',callEnabled);
 callModeButton.hidden=!callEnabled;
 callModeButton.classList.toggle('active',callEnabled);
 callModeButton.setAttribute('aria-pressed',String(callEnabled));
 if(callEnabled){
  ensureCallOverlay();mountCallOverlay();
  if(hint)callHint('隱藏 Call 已啟動 · 再按 ↓↓ 校拍');
  else callUpdateHud('待機');
 }else{
  stopCallAutoBeat();
  clearTimeout(callWaveTimer);callWaveTimer=null;
  callHeldDirection='';callSpaceHeld=false;callWakeTaps=[];callTapTimes=[];callClearMotion();callUpdateHud('待機');
 }
}
function callTapTempo(now=performance.now()){
 if(callTapTimes.length&&now-callTapTimes[callTapTimes.length-1]>2500){
  callTapTimes=[];stopCallAutoBeat();
 }
 callTapTimes.push(now);
 if(callTapTimes.length>4)callTapTimes.shift();
 if(callTapTimes.length>=2){
  const gaps=[];
  for(let i=1;i<callTapTimes.length;i++)gaps.push(callTapTimes[i]-callTapTimes[i-1]);
  const avg=gaps.reduce((a,b)=>a+b,0)/gaps.length;
  if(avg>=240&&avg<=1200)callBeatMs=avg;
 }
 callUpdateHud('胸前拍 '+callTapTimes.length+'/4');
 if(callTapTimes.length===4)startCallAutoBeat();
}
function callPulseChest(){
 if(!callOverlay)return;
 const hands=callOverlay.querySelector('.call-hands');
 hands?.animate([
  {transform:'translate(-50%,0) scale(1)'},
  {transform:'translate(-50%,5%) scale(.98)',offset:.34},
  {transform:'translate(-50%,-4%) scale(1.02)',offset:.62},
  {transform:'translate(-50%,0) scale(1)'}
 ],{duration:Math.max(180,callBeatMs*.72),easing:'cubic-bezier(.22,.8,.3,1)'});
}
function callFlickUp(){
 if(!callOverlay)return;
 const hands=callOverlay.querySelector('.call-hands');
 hands?.animate([
  {transform:'translate(-50%,0) rotate(0)'},
  {transform:'translate(-50%,-104%) rotate(0)',offset:.58},
  {transform:'translate(-50%,-94%) rotate(0)',offset:.76},
  {transform:'translate(-50%,0) rotate(0)'}
 ],{duration:Math.max(420,callBeatMs*1.35),easing:'cubic-bezier(.2,.68,.3,1)'});
 callUpdateHud('上甩');
}
function callSetSideMotion(direction,mode){
 if(!callOverlay)return;
 callClearMotion();
 const suffix=direction==='left'?'left':'right';
 callOverlay.classList.add(mode==='fast'?'side-fast-'+suffix:mode==='wave'?'side-wave-'+suffix:'side-two-'+suffix);
 callUpdateHud(mode==='fast'?'一拍雨刷':mode==='wave'?'大波浪':'兩拍搖');
}
function callDirectionDown(direction,now=performance.now()){
 if(callHeldDirection===direction)return;
 stopCallAutoBeat();
 clearTimeout(callWaveTimer);
 const switched=callLastDirection&&callLastDirection!==direction&&(now-callLastDirectionAt)<=callBeatMs*2.05;
 callHeldDirection=direction;
 callDirectionStartedAt=now;
 callLastDirection=direction;
 callLastDirectionAt=now;
 callSetSideMotion(direction,switched?'fast':'two');
 callWaveTimer=setTimeout(()=>{
  if(callEnabled&&callHeldDirection===direction&&performance.now()-callDirectionStartedAt>=callBeatMs*1.9){
   callSetSideMotion(direction,'wave');
  }
 },Math.max(160,callBeatMs*1.92));
}
function callDirectionUp(direction){
 if(callHeldDirection!==direction)return;
 clearTimeout(callWaveTimer);callWaveTimer=null;
 callHeldDirection='';
 callClearMotion();
 callUpdateHud('待機');
}
function callSpaceDown(){
 if(callSpaceHeld)return;
 stopCallAutoBeat();
 callSpaceHeld=true;
 callClearMotion();
 callOverlay?.classList.add('space-pump');
 callUpdateHud('連續上舉');
}
function callSpaceUp(){
 if(!callSpaceHeld)return;
 callSpaceHeld=false;
 callOverlay?.classList.remove('space-pump');
 callUpdateHud('待機');
}
function handleCallKeyDown(event){
 if(callEditableTarget(event.target))return;
 const key=event.key;
 if(!callEnabled){
  if(key!=='ArrowDown'||event.repeat)return;
  const now=performance.now();
  callWakeTaps=callWakeTaps.filter(t=>now-t<=800);
  callWakeTaps.push(now);
  if(callWakeTaps.length<2)return;
  event.preventDefault();
  const wake=[...callWakeTaps.slice(-2)];
  setCallMode(true,{hint:true});
  callTapTimes=[];
  wake.forEach(t=>callTapTempo(t));
  callPulseChest();
  callWakeTaps=[];
  return;
 }
 if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight',' '].includes(key))return;
 event.preventDefault();
 if(key==='ArrowDown'){
  if(event.repeat)return;
  callTapTempo();callPulseChest();return;
 }
 if(key==='ArrowUp'){
  if(event.repeat)return;
  stopCallAutoBeat();callFlickUp();return;
 }
 if(key==='ArrowLeft'){if(!event.repeat)callDirectionDown('left');return}
 if(key==='ArrowRight'){if(!event.repeat)callDirectionDown('right');return}
 if(key===' ')callSpaceDown();
}
function handleCallKeyUp(event){
 if(!callEnabled||callEditableTarget(event.target))return;
 if(!['ArrowLeft','ArrowRight',' '].includes(event.key))return;
 event.preventDefault();
 if(event.key==='ArrowLeft')callDirectionUp('left');
 else if(event.key==='ArrowRight')callDirectionUp('right');
 else callSpaceUp();
}

function playerHostId(stream){return 'viewer-player-'+String(stream?.videoId||'').replace(/[^A-Za-z0-9_-]/g,'')}
function playerDisplayLabel(stream){
 const label=String(stream?.label||'').trim();
 const videoId=String(stream?.videoId||'').trim();
 if(!label||label===videoId||/^[A-Za-z0-9_-]{11}$/.test(label))return '';
 return label;
}
function createPlayerCard(index){
 const stream=streams[index];
 const card=node('section',undefined,'player-card');
 card.dataset.index=String(index);
 const label=node('div',playerDisplayLabel(stream),'player-label');
 const remove=node('button','×','player-remove');
 remove.type='button';
 remove.title='移除此直播';
 remove.setAttribute('aria-label','移除此直播');
 remove.addEventListener('click',event=>{
  event.stopPropagation();
  removeMultiStream(Number(card.dataset.index));
 });
 const host=node('div',undefined,'player-host');
 host.id=playerHostId(stream);
 card.append(label,remove,host);
 playerCards[index]=card;
 return card;
}
function renderShell(){
 stage.replaceChildren();
 playerCards.splice(0,playerCards.length);
 if(!streams.length){
  stage.append(node('div','沒有可播放的 YouTube 影片。','ptt-empty'));
  controls.hidden=true;
  return;
 }
 streams.forEach((_,index)=>stage.append(createPlayerCard(index)));
 ensureDragDropOverlay();
 renderControls();
 applyLayout();
 mountCallOverlay();
}
function renderControls(){
 focusChoices.replaceChildren();
 streams.forEach((stream,index)=>{
  const button=node('button',undefined,'focus-avatar-button');
  button.type='button';
  button.dataset.focusIndex=String(index);
  const lockedHere=currentLayoutPreset()==='focus'&&index===lockedIndex;
  button.title=(lockedHere?'解除鎖定並回到輪播：':currentLayoutPreset()==='focus'?'改鎖定主視角：':'鎖定主視角：')+stream.label;
  button.setAttribute('aria-label',button.title);
  applyFocusAccent(button,stream);
  const avatar=streamAvatarUrl(stream);
  if(avatar){
   const img=document.createElement('img');
   img.src=avatar;
   img.alt='';
   button.append(img);
  }else{
   button.append(node('span',[...String(stream.label||'H')][0]||'H','focus-avatar-fallback'));
  }
  button.addEventListener('click',()=>handleFocusAvatarClick(index));
  focusChoices.append(button);
 });
 const multi=watchMode==='multi'&&streams.length>1;
 const focusMode=multi&&currentLayoutPreset()!=='equal';
 playerCards.forEach(card=>{const remove=card?.querySelector('.player-remove');if(remove)remove.hidden=!multi});
 document.getElementById('layoutGroup').hidden=!multi;
 document.getElementById('focusGroup').hidden=!focusMode;
 persistentPlaybackControls.hidden=!multi;
 const carouselVisible=multi&&currentLayoutPreset()!=='equal';
 focusCarouselStatus.hidden=!carouselVisible;
 focusCarouselStatus.textContent=currentLayoutPreset()==='focus'?'鎖定':carouselVisible?'↻ '+carouselInterval.value+'s':'';
 carouselControl.hidden=true;
 carouselIntervalGroup.hidden=!focusMode;
 multiModeSwitch.checked=watchMode==='multi';
 applyModeClass();
 settingsButton.classList.toggle('active',!controls.hidden);
 refreshControlState();
}
function refreshControlState(){
 document.querySelectorAll('[data-layout-preset]').forEach(button=>{
  const preset=currentLayoutPreset();
  const active=button.dataset.layoutPreset===preset||(button.dataset.layoutPreset==='primary'&&preset==='focus');
  button.classList.toggle('active',active);
  button.setAttribute('aria-pressed',String(active));
 });
 [...focusChoices.children].forEach((button,index)=>{
  button.hidden=!viewingPovVisible(index);
  const locked=currentLayoutPreset()==='focus'&&index===lockedIndex;
  button.classList.toggle('active',locked);
  button.setAttribute('aria-pressed',String(locked));
  const label=streams[index]?.label||'Hololive';
  button.title=(locked?'解除鎖定並回到輪播：':currentLayoutPreset()==='focus'?'改鎖定主視角：':'鎖定主視角：')+label;
  button.setAttribute('aria-label',button.title);
 });
 const preset=currentLayoutPreset();
 playerCards.forEach((card,index)=>{
  if(!card)return;
  card.hidden=!viewingPovVisible(index);
  card.classList.remove('primary','secondary-1','secondary-2','secondary-3','viewer-hidden');
  if(preset!=='equal'&&viewingPovVisible(index))card.classList.toggle('primary',index===primaryIndex);
 });
 if(preset!=='equal'){
  const secondaryIndexes=playerCards.map((card,index)=>card&&viewingPovVisible(index)&&index!==primaryIndex?index:-1).filter(index=>index>=0);
  const visibleCount=Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryIndexes.length);
  const offset=secondaryIndexes.length?secondaryOffset%secondaryIndexes.length:0;
  const visible=new Set(Array.from({length:visibleCount},(_,slot)=>secondaryIndexes[(offset+slot)%secondaryIndexes.length]));
  secondaryIndexes.forEach(index=>playerCards[index]?.classList.toggle('viewer-hidden',!visible.has(index)));
  [...visible].forEach((index,slot)=>playerCards[index]?.classList.add('secondary-'+(slot+1)));
 }
}
function applyLayout(){
 const wasFollowing=pttFollowing||pttAtBottom();
 const count=Math.max(0,streams.filter((_,index)=>viewingPovVisible(index)).length);
 const effective=watchMode==='multi'&&count>1?layout:'equal';
 stage.className='viewer-stage layout-'+effective+' count-'+Math.max(1,count);
 workspace.className='viewer-workspace workspace-sidebar layout-'+effective+' count-'+Math.max(1,count);
 const cols=count<=1?1:count<=4?2:count<=9?3:4;
 const rows=Math.max(1,Math.ceil(count/cols));
 const focusSecondaryCount=Math.min(FOCUS_VISIBLE_SLOTS-1,Math.max(0,count-1));
 stage.style.setProperty('--viewer-cols',String(cols));
 stage.style.setProperty('--viewer-rows',String(rows));
 stage.style.setProperty('--focus-rows',String(Math.max(1,focusSecondaryCount)));
 workspace.style.setProperty('--focus-secondary-count',String(Math.max(1,focusSecondaryCount)));
 workspace.style.setProperty('--ptt-grid-row',String(focusSecondaryCount+1));
 // Layout changes are CSS-only. Never re-append live iframe cards: moving
 // YouTube iframe DOM nodes can interrupt active playback.
 refreshControlState();
 updateUrl();
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
}
function setAudioMaster(index){
 if(index<0||index>=streams.length)return;
 audioMaster=index;
 players.forEach((player,i)=>{
  if(!player)return;
  try{if(i===audioMaster)player.unMute();else player.mute();}catch{}
 });
 updateUrl();
}
function setPrimary(index){
 if(index<0||index>=streams.length)return;
 const previousIndex=primaryIndex;
 const primaryChanged=index!==previousIndex;
 const wasFollowing=pttFollowing||pttAtBottom();
 primaryIndex=index;
 secondaryOffset=0;
 if(currentLayoutPreset()==='focus')lockedIndex=index;
 if(viewingTimelineActive()&&streams[index]?.povId){
  try{viewingAdapter.setPrimaryPov(streams[index].povId)}catch{}
 }
 setAudioMaster(index);
 applyLayout();
 mountCallOverlay();
 // Shared-session PTT follows the session absolute clock, never the selected POV.
 if(primaryChanged&&!viewingTimelineActive())resolvePrimaryPtt();
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
}
function handleFocusAvatarClick(index){
 if(index<0||index>=streams.length)return;
 if(currentLayoutPreset()==='focus'&&lockedIndex===index){
  setLayoutPreset('primary');
  return;
 }
 if(currentLayoutPreset()!=='focus'){
  // Entering Lock on the current carousel primary must not reload or re-resolve PTT.
  if(index!==primaryIndex)setPrimary(index);
  setLayoutPreset('focus');
  return;
 }
 setPrimary(index);
}
function syncPlayers(state,sourceIndex){
 if(watchMode!=='multi'||!syncPlayback.checked||streams.length<2)return;
 players.forEach((player,index)=>{
  if(!player||index===sourceIndex)return;
  try{
   syncExpected.set(player,{state,until:Date.now()+900});
   if(state===YT.PlayerState.PLAYING)player.playVideo();
   else if(state===YT.PlayerState.PAUSED)player.pauseVideo();
  }catch{}
 });
}
function handlePlayerStateChange(player,state){
 if(players[primaryIndex]===player&&pttVodMode()){
  if(state===YT.PlayerState.PLAYING)pttVodHasPlayed=true;
  syncVodPttTimeline();
 }
 if(state!==YT.PlayerState.PLAYING&&state!==YT.PlayerState.PAUSED)return;
 const expected=syncExpected.get(player);
 if(expected&&Date.now()<expected.until&&expected.state===state){
  syncExpected.delete(player);
  return;
 }
 if(viewingTimelineActive()){
  if(state===YT.PlayerState.PLAYING)viewingRunIntent=true;
  else if(state===YT.PlayerState.PAUSED)viewingRunIntent=false;
 }
 const sourceIndex=players.indexOf(player);
 if(sourceIndex>=0)syncPlayers(state,sourceIndex);
}
function mountPlayerAt(index,autoplay=false,seekSeconds=null){
 if(!window.YT?.Player||players[index]||!streams[index])return;
 const host=document.getElementById(playerHostId(streams[index]));
 if(!host)return;
 players[index]=new YT.Player(host,{
  videoId:streams[index].videoId,
  playerVars:{playsinline:1,rel:0,enablejsapi:1,origin:location.origin},
  events:{
   onReady:event=>{
    if(Number.isFinite(seekSeconds)){try{event.target.seekTo(Math.max(0,seekSeconds),true)}catch{}}
    if(index===primaryIndex&&pttVodMode())setTimeout(()=>syncVodPttTimeline({forceFollow:true}),0);
    if(autoplay){
     try{if(index!==audioMaster)event.target.mute()}catch{}
     try{event.target.playVideo()}catch{}
    }else{
     setAudioMaster(primaryIndex);
    }
   },
   onStateChange:event=>handlePlayerStateChange(event.target,event.data)
  }
 });
}
function mountPlayers(){
 streams.forEach((stream,index)=>{
  if(viewingTimelineActive()&&stream?.povId){
   const resolved=viewingAdapter.resolution(stream.povId);
   const seek=resolved?.status==='READY'?resolved.source_time_ms/1000:null;
   mountPlayerAt(index,false,seek);
  }else mountPlayerAt(index,confirmedLiveIds.has(stream.videoId));
 });
}
function destroyPlayers(){
 players.forEach(player=>{try{player?.destroy()}catch{}});
 players.splice(0,players.length);
}

function switchWatchMode(nextMode){
 if(nextMode===watchMode)return;
 watchMode=nextMode;
 applyModeClass();
 clearInterval(carouselTimer);
 carouselTimer=null;
 carousel.checked=false;
 lockedIndex=null;
 secondaryOffset=0;
 if(watchMode==='single'&&streams.length>1){
  const selected={...(streams[primaryIndex]||streams[0])};
  destroyPlayers();
  streams.splice(0,streams.length,selected);
  primaryIndex=0;
  audioMaster=0;
  renderShell();
  if(window.YT?.Player)mountPlayerAt(0,false);
  resolvePrimaryPtt();
 }else{
  renderControls();
  applyLayout();
 }
 renderLiveRail(catalogRows);
 updateUrl();
}
function commitSingleStream(row,id){
 if(!streams.length)streams.push({videoId:id,label:catalogName(row),channelId:String(row?.channel_id||'')});
 else{
  streams[0].videoId=id;
  streams[0].label=catalogName(row);
  streams[0].channelId=String(row?.channel_id||'');
  streams[0].avatarUrl=safeAvatar(row?.avatar_url);
 }
 primaryIndex=0;
 audioMaster=0;
 const label=playerCards[0]?.querySelector('.player-label');
 if(label)label.textContent=playerDisplayLabel(streams[0]);
 renderControls();
 applyLayout();
 renderLiveRail(catalogRows);
 resolvePrimaryPtt();
}
function replaceSingleStream(row){
 const id=String(row?.video_id||'');
 if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
 if(streams[0]?.videoId===id)return;

 const card=playerCards[0];
 if(!card||!window.YT?.Player)return;

 let wasMuted=false;
 try{wasMuted=Boolean(players[0]?.isMuted?.())}catch{}
 try{players[0]?.destroy()}catch{}
 players[0]=null;
 card.querySelector('iframe')?.remove();
 card.querySelector('.player-host')?.remove();

 // Commit the selected live first, then create one fresh, paused player.
 // No autoplay fallback and no surprise mute: the user presses Play once.
 commitSingleStream(row,id);
 const host=node('div',undefined,'player-host');
 host.id=playerHostId(streams[0]);
 card.append(host);
 players[0]=new YT.Player(host,{
  videoId:id,
  playerVars:{playsinline:1,rel:0,enablejsapi:1,autoplay:0,origin:location.origin},
  events:{
   onReady:event=>{
    try{if(wasMuted)event.target.mute();else event.target.unMute()}catch{}
   },
   onStateChange:event=>handlePlayerStateChange(event.target,event.data)
  }
 });
}
function appendMultiStream(row,{focusExisting=true,seekSeconds=null,autoplay=null}={}){
 const id=String(row?.video_id||'');
 if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
 const existing=streams.findIndex(stream=>stream.videoId===id);
 if(existing>=0){if(focusExisting)setPrimary(existing);return existing}
 if(streams.length>=MAX_STREAMS)return -1;
 stage.querySelector('.collab-waiting')?.remove();
 const index=streams.length;
 streams.push({videoId:id,label:catalogName(row),channelId:String(row?.channel_id||''),avatarUrl:safeAvatar(row?.avatar_url)});
 const card=createPlayerCard(index);
 stage.append(card);
 players[index]=null;
 if(streams.length===1){primaryIndex=0;audioMaster=0}
 renderControls();
 applyLayout();
 let shouldPlay=Boolean(autoplay);
 if(autoplay===null){try{shouldPlay=players[primaryIndex]?.getPlayerState()===YT.PlayerState.PLAYING}catch{}}
 if(window.YT?.Player)mountPlayerAt(index,shouldPlay,seekSeconds);
 renderLiveRail(catalogRows);
 updateUrl();
 return index;
}
function showCollabWaiting(message='目前沒有符合這個多人連動狀態的 POV。'){
 if(streams.length)return;
 stage.replaceChildren(node('div',message,'ptt-empty collab-waiting'));
 controls.hidden=true;
}
function removeMultiStreamInternal(index,{allowEmpty=false}={}){
 if(watchMode!=='multi'||(!allowEmpty&&streams.length<=1)||index<0||index>=streams.length)return;
 const removedWasPrimary=index===primaryIndex;
 const removedPlayer=players[index];
 const removedCard=playerCards[index];

 streams.splice(index,1);
 players.splice(index,1);
 playerCards.splice(index,1);
 removedCard?.remove();
 try{removedPlayer?.destroy()}catch{}

 if(!streams.length){
  primaryIndex=0;audioMaster=0;lockedIndex=null;secondaryOffset=0;
  renderControls();renderLiveRail(catalogRows);showCollabWaiting();
  updateUrl();
  return;
 }
 if(index<primaryIndex)primaryIndex-=1;
 else if(removedWasPrimary)primaryIndex=Math.min(index,streams.length-1);
 audioMaster=primaryIndex;
 if(currentLayoutPreset()==='focus')lockedIndex=primaryIndex;
 secondaryOffset=0;

 playerCards.forEach((card,i)=>{if(card)card.dataset.index=String(i)});
 renderControls();
 applyLayout();
 setAudioMaster(primaryIndex);
 renderLiveRail(catalogRows);
 updateUrl();
 if(removedWasPrimary)resolvePrimaryPtt();
}
function removeMultiStream(index){removeMultiStreamInternal(index,{allowEmpty:false})}
function addDraggedLive(row){
 const id=String(row?.video_id||'');
 if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
 if(streams.some(stream=>stream.videoId===id))return;
 if(watchMode==='single')switchWatchMode('multi');
 appendMultiStream(row);
}

function ensureDragDropOverlay(){
 let overlay=document.getElementById('viewerDragDropOverlay');
 if(overlay)return overlay;
 overlay=node('div','放開以加入多人觀看','viewer-drag-drop-overlay');
 overlay.id='viewerDragDropOverlay';
 overlay.hidden=true;
 overlay.addEventListener('dragover',event=>{
  if(!/^[A-Za-z0-9_-]{11}$/.test(draggedLiveId))return;
  event.preventDefault();
  if(event.dataTransfer)event.dataTransfer.dropEffect='copy';
  overlay.classList.add('is-active');
 });
 overlay.addEventListener('dragleave',()=>overlay.classList.remove('is-active'));
 overlay.addEventListener('drop',event=>{
  event.preventDefault();
  const id=String(event.dataTransfer?.getData('text/plain')||draggedLiveId||'');
  draggedLiveId='';
  overlay.classList.remove('is-active');
  overlay.hidden=true;
  const row=catalogRows.find(item=>String(item?.video_id||'')===id);
  if(row)addDraggedLive(row);
 });
 workspace.append(overlay);
 return overlay;
}
function showDragDropOverlay(){
 const overlay=ensureDragDropOverlay();
 overlay.hidden=false;
 overlay.classList.add('is-active');
}
function hideDragDropOverlay(){
 const overlay=document.getElementById('viewerDragDropOverlay');
 if(!overlay)return;
 overlay.classList.remove('is-active');
 overlay.hidden=true;
}
function handleLiveRailClick(row){
 if(watchMode==='multi')appendMultiStream(row);
 else replaceSingleStream(row);
}
function collabStreams(event){
 return Array.isArray(event?.streams)
  ?event.streams.filter(row=>row&&/^[A-Za-z0-9_-]{11}$/.test(String(row.video_id||'')))
  :[];
}
function collabState(row){return String(row?.lifecycle_state||row?.state||'unknown').toLowerCase()}
function collabStartMs(row){const ms=Date.parse(String(row?.actual_start||''));return Number.isFinite(ms)?ms:null}
function collabEndMs(row){const ms=Date.parse(String(row?.actual_end||''));return Number.isFinite(ms)?ms:null}
function collabRowFor(id){return collabRoster.get(id)||catalogRows.find(row=>String(row?.video_id||'')===id)||{video_id:id,title:id}}
function applyCollabEvent(event){
 collabEvent=event||null;
 collabRoster=new Map(collabStreams(event).map(row=>[String(row.video_id),row]));
}
async function fetchCollabEvent(){
 if(!collabManaged)return null;
 try{
  const data=await api('/v1/collab/events/'+encodeURIComponent(collabEventId)+(collabDay?'?day='+encodeURIComponent(collabDay):''));
  return data?.event||null;
 }catch{
  try{
   const data=await api('/v1/collab/live');
   const events=Array.isArray(data?.events)?data.events:[];
   const activeIds=new Set([...collabRoster.keys(),...streams.map(stream=>stream.videoId)]);
   return events.find(event=>collabStreams(event).some(row=>activeIds.has(String(row.video_id))))||null;
  }catch{return null}
 }
}
function currentPrimaryAbsoluteMs(){
 if(viewingTimelineActive())return viewingAdapter.absoluteTimeMs();
 if(!streams.length)return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:null;
 const row=collabRowFor(streams[primaryIndex]?.videoId);
 const start=collabStartMs(row);
 if(start===null)return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:null;
 let seconds=null;
 try{seconds=players[primaryIndex]?.getCurrentTime?.()}catch{}
 if(!Number.isFinite(seconds))return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:start;
 return start+Math.max(0,seconds)*1000;
}
function collabTimelinePovId(row){
 const channel=String(row?.channel_id||'');
 return channel||String(row?.video_id||'');
}
function buildCollabViewingSession(event){
 if(!viewingTimelineCore||!viewingAdapterFactory||collabKind!=='vod'||event?.sync?.available!==true)return null;
 if(event?.viewing_timeline&&typeof event.viewing_timeline==='object'){
  try{viewingTimelineCore.validateSession(event.viewing_timeline);return event.viewing_timeline}catch{return null}
 }
 const rows=collabStreams(event).map(row=>({
  row,start:collabStartMs(row),end:collabEndMs(row)
 })).filter(item=>item.start!==null&&item.end!==null&&item.end>item.start);
 if(rows.length<2)return null;
 const absoluteStart=Math.min(...rows.map(item=>item.start));
 const absoluteEnd=Math.max(...rows.map(item=>item.end));
 const session={
  schema_version:viewingTimelineCore.SCHEMA,
  session_id:String(event?.event_id||collabEventId),
  absolute_start_ms:absoluteStart,
  master_end_ms:absoluteEnd-absoluteStart,
  povs:rows.map(item=>({
   pov_id:collabTimelinePovId(item.row),
   segments:[{
    segment_id:'source:'+String(item.row.video_id),
    master_start_ms:item.start-absoluteStart,
    master_end_ms:item.end-absoluteStart,
    video_id:String(item.row.video_id),
    source_start_ms:0
   }]
  }))
 };
 const revision=String(event?.sync?.revision||event?.source_revision||'');
 if(revision)session.revision=revision;
 try{viewingTimelineCore.validateSession(session);return session}catch{return null}
}
function mapViewingPovsToStreams(session){
 const assigned=new Set();
 for(const pov of session.povs){
  const ids=new Set(pov.segments.map(segment=>String(segment.video_id)));
  const index=streams.findIndex((stream,i)=>!assigned.has(i)&&ids.has(String(stream.videoId)));
  if(index<0)return false;
  streams[index].povId=String(pov.pov_id);assigned.add(index);
 }
 return assigned.size===session.povs.length&&assigned.size===streams.length;
}
function viewingSharedStateFor(_session){
 // Share-link timeline restore is parked; runtime always starts from its own session origin.
 return null;
}
function replaceTimelinePovSource(index,resolved){
 if(index<0||index>=streams.length||resolved?.status!=='READY')return false;
 const stream=streams[index];
 if(String(stream.videoId)===String(resolved.video_id))return false;
 const player=players[index],card=playerCards[index];
 let playing=false,muted=index!==audioMaster;
 try{playing=player?.getPlayerState?.()===YT.PlayerState.PLAYING}catch{}
 if(viewingTimelineActive()&&viewingSessionPlaying())playing=true;
 try{muted=Boolean(player?.isMuted?.())}catch{}
 try{player?.destroy()}catch{}
 players[index]=null;
 stream.videoId=String(resolved.video_id);
 const row=collabRowFor(stream.videoId);
 stream.label=catalogName(row);
 const label=card?.querySelector('.player-label');if(label)label.textContent=playerDisplayLabel(stream);
 const oldHost=card?.querySelector('.player-host');oldHost?.remove();
 if(card){
  const host=node('div',undefined,'player-host');host.id=playerHostId(stream);card.append(host);
 }
 if(window.YT?.Player&&card){
  mountPlayerAt(index,playing,resolved.source_time_ms/1000);
  if(muted){try{players[index]?.mute?.()}catch{}}
 }
 renderControls();
 return true;
}
function viewingClockStream(){
 if(!viewingTimelineActive()||!viewingClockPovId)return null;
 const index=streams.findIndex(stream=>String(stream?.povId||'')===String(viewingClockPovId));
 return index>=0?{index,stream:streams[index],player:players[index]}:null;
}
function viewingSessionPlaying(){
 if(viewingTimelineActive()&&viewingRunIntent)return true;
 return players.some(player=>{
  try{return player?.getPlayerState?.()===YT.PlayerState.PLAYING}catch{return false}
 });
}
function viewingPovVisible(index){
 if(!viewingTimelineActive()||!collabManaged||collabKind!=='vod'||!viewingVisiblePovs)return true;
 const povId=String(streams[index]?.povId||'');
 return Boolean(povId&&viewingVisiblePovs.has(povId));
}
function applyViewingCoverage(plan){
 if(!viewingTimelineActive()||!collabManaged||collabKind!=='vod')return false;
 const next=new Set(plan.filter(item=>item.status==='READY').map(item=>String(item.pov_id)));
 const previous=viewingVisiblePovs||new Set();
 const changed=next.size!==previous.size||[...next].some(id=>!previous.has(id));
 viewingVisiblePovs=next;
 if(!changed)return false;

 playerCards.forEach((card,index)=>{if(card)card.hidden=!viewingPovVisible(index)});
 [...focusChoices.children].forEach((button,index)=>{button.hidden=!viewingPovVisible(index)});

 if(!viewingPovVisible(primaryIndex)){
  const nextPrimary=streams.findIndex((_,index)=>viewingPovVisible(index));
  if(nextPrimary>=0){
   primaryIndex=nextPrimary;
   audioMaster=nextPrimary;
   try{viewingAdapter.setPrimaryPov(streams[nextPrimary].povId)}catch{}
   players.forEach((player,index)=>{
    if(!player)return;
    try{if(index===audioMaster)player.unMute();else player.mute()}catch{}
   });
  }
 }
 applyLayout();
 mountCallOverlay();
 return true;
}
function sampleViewingMasterClock(){
 const now=performance.now();
 const owner=viewingClockStream();
 let mapped=null,ownerState=null;
 if(owner?.stream){
  const resolved=viewingAdapter.resolution(owner.stream.povId);
  try{ownerState=owner.player?.getPlayerState?.()}catch{}
  if(resolved?.status==='READY'&&
     [YT.PlayerState.PLAYING,YT.PlayerState.PAUSED,YT.PlayerState.BUFFERING].includes(ownerState)){
   let seconds=null;try{seconds=owner.player?.getCurrentTime?.()}catch{}
   if(Number.isFinite(seconds)){
    const candidate=viewingAdapter.masterFromSource(owner.stream.povId,owner.stream.videoId,seconds*1000);
    if(Number.isFinite(candidate)){
     if(viewingClockSample){
      const elapsed=Math.max(0,now-viewingClockSample.wallMs);
      const expected=viewingClockSample.masterMs+
       (ownerState===YT.PlayerState.PLAYING?elapsed:0);
      if(Math.abs(candidate-expected)>2500)viewingResyncPending=true;
     }
     viewingClockSample={wallMs:now,masterMs:candidate};
     mapped=candidate;
    }
   }
  }
 }
 if(viewingClockPolicy){
  return viewingClockPolicy.step({nowMs:now,running:viewingSessionPlaying(),mappedMasterMs:mapped});
 }
 if(Number.isFinite(mapped))viewingAdapter.setMasterTimeMs(mapped);
 return viewingAdapter.masterTimeMs;
}
function reconcileViewingTimeline({sampleClock=true}={}){
 if(!viewingTimelineActive()||viewingReconciling)return;
 viewingReconciling=true;
 try{
  if(sampleClock)sampleViewingMasterClock();
  const current={};streams.forEach(stream=>{if(stream?.povId)current[stream.povId]=stream.videoId});
  const plan=viewingAdapter.plan(current);
  applyViewingCoverage(plan);
  const resyncOthers=viewingResyncPending;
  viewingResyncPending=false;
  for(const resolved of plan){
   const povId=String(resolved.pov_id);
   const index=streams.findIndex(stream=>String(stream?.povId||'')===povId);
   if(index<0)continue;
   if(resolved.status!=='READY'){
    timelineGapPovs.add(povId);
    const player=players[index];
    if(player){
     try{
      if(player.getPlayerState?.()===YT.PlayerState.PLAYING){
       syncExpected.set(player,{state:YT.PlayerState.PAUSED,until:Date.now()+900});
       player.pauseVideo?.();
      }
     }catch{}
    }
    continue;
   }
   const resumedFromGap=timelineGapPovs.delete(povId);
   if(resolved.replace){
    replaceTimelinePovSource(index,resolved);
    continue;
   }
   const player=players[index];
   const target=resolved.source_time_ms/1000;
   if(player&&resumedFromGap){
    try{player.seekTo(target,true)}catch{}
    if(viewingSessionPlaying()){
     try{
      syncExpected.set(player,{state:YT.PlayerState.PLAYING,until:Date.now()+900});
      player.playVideo?.();
     }catch{}
    }
    continue;
   }
   if(player&&resyncOthers&&povId!==viewingClockPovId){
    let currentSeconds=null;try{currentSeconds=player.getCurrentTime?.()}catch{}
    if(!Number.isFinite(currentSeconds)||Math.abs(currentSeconds-target)>1.2){
     try{player.seekTo(target,true)}catch{}
    }
   }
  }
  collabAbsoluteMs=viewingAdapter.absoluteTimeMs();
  if(pttVodMode()&&pttLoaded)syncVodPttTimeline();
 }finally{viewingReconciling=false}
}
function initViewingTimeline(event){
 const session=buildCollabViewingSession(event);
 if(!session||!mapViewingPovsToStreams(session))return false;
 const restored=viewingSharedStateFor(session);
 const fallbackPrimary=streams[primaryIndex]?.povId||session.povs[0].pov_id;
 const primary=restored?.primaryPovId||fallbackPrimary;
 try{
  viewingSession=session;
  viewingAdapter=viewingAdapterFactory.create(session,{
   timeline:viewingTimelineCore,
   initialMasterTimeMs:restored?.masterTimeMs||0,
   primaryPovId:primary
  });
  viewingClockPovId=String(session.povs[0]?.pov_id||'');
  viewingClockPolicy=viewingAdapterFactory.createClock(viewingAdapter,{nowMs:performance.now()});
  viewingClockSample=null;viewingResyncPending=false;viewingRunIntent=false;
  viewingVisiblePovs=new Set(viewingAdapter.plan({}).filter(item=>item.status==='READY').map(item=>String(item.pov_id)));
 }catch{
  viewingSession=null;viewingAdapter=null;viewingClockPovId='';viewingClockPolicy=null;viewingVisiblePovs=null;viewingRunIntent=false;return false;
 }
 const restoredIndex=streams.findIndex(stream=>String(stream.povId)===String(viewingAdapter.primaryPovId));
 if(restoredIndex>=0){primaryIndex=restoredIndex;audioMaster=restoredIndex}
 const current={};streams.forEach(stream=>{if(stream?.povId)current[stream.povId]=stream.videoId});
 for(const resolved of viewingAdapter.plan(current)){
  if(resolved.status!=='READY')continue;
  const index=streams.findIndex(stream=>String(stream?.povId||'')===String(resolved.pov_id));
  if(index>=0)streams[index].videoId=String(resolved.video_id);
 }
 collabAbsoluteMs=viewingAdapter.absoluteTimeMs();
 // Safe here: init runs before YouTube players are mounted.
 renderShell();
 clearInterval(viewingTimer);
 viewingTimer=setInterval(()=>{if(!document.hidden)reconcileViewingTimeline()},500);
 return true;
}

function desiredVodRowsAt(absoluteMs){
 if(!Number.isFinite(absoluteMs))return [];
 return [...collabRoster.values()].filter(row=>{
  const start=collabStartMs(row),end=collabEndMs(row);
  return start!==null&&end!==null&&end>start&&absoluteMs>=start&&absoluteMs<end;
 }).sort((a,b)=>collabStartMs(a)-collabStartMs(b)||String(a.video_id).localeCompare(String(b.video_id)));
}
function seekVodPlayers(absoluteMs){
 streams.forEach((stream,index)=>{
  const row=collabRowFor(stream.videoId),start=collabStartMs(row);
  if(start===null)return;
  const target=(absoluteMs-start)/1000;
  if(target<0)return;
  const player=players[index];if(!player)return;
  let current=null;try{current=player.getCurrentTime()}catch{}
  if(!Number.isFinite(current)||Math.abs(current-target)>1.2){try{player.seekTo(target,true)}catch{}}
 });
}
function reconcileCollabRows(desired,{absoluteMs=null}={}){
 if(collabReconciling)return;
 collabReconciling=true;
 try{
  const desiredIds=new Set(desired.map(row=>String(row.video_id)));
  for(let i=streams.length-1;i>=0;i--){
   if(!desiredIds.has(streams[i].videoId))removeMultiStreamInternal(i,{allowEmpty:true});
  }
  let playing=false;
  try{playing=players[primaryIndex]?.getPlayerState?.()===YT.PlayerState.PLAYING}catch{}
  for(const row of desired){
   const id=String(row.video_id);
   if(streams.some(stream=>stream.videoId===id))continue;
   const start=collabStartMs(row);
   const seek=Number.isFinite(absoluteMs)&&start!==null?Math.max(0,(absoluteMs-start)/1000):null;
   appendMultiStream(row,{focusExisting:false,seekSeconds:seek,autoplay:playing});
  }
  if(Number.isFinite(absoluteMs)&&streams.length)seekVodPlayers(absoluteMs);
  if(!streams.length)showCollabWaiting(collabKind==='live'?'等待同一多人連動的新直播開始…':'這個時間點沒有進行中的 POV。');
 }finally{collabReconciling=false}
}
async function reconcileLiveCollab(){
 const event=await fetchCollabEvent();
 if(!event)return;
 applyCollabEvent(event);
 const live=collabStreams(event).filter(row=>collabState(row)==='live').slice(0,MAX_STREAMS);
 reconcileCollabRows(live);
}
function reconcileVodCollab(){
 if(viewingTimelineActive()){reconcileViewingTimeline();return}
 if(!collabEvent?.sync?.available)return;
 const absolute=currentPrimaryAbsoluteMs();
 if(!Number.isFinite(absolute))return;
 collabAbsoluteMs=absolute;
 reconcileCollabRows(desiredVodRowsAt(absolute),{absoluteMs:absolute});
}
async function initCollabManager(){
 if(!collabManaged)return;
 if(collabKind==='vod'&&archiveWindows.size){
  const localRows=streams.map(stream=>{
   const window=archiveWindows.get(stream.videoId);
   return window?{video_id:stream.videoId,lifecycle_state:'ended',
    actual_start:window.start,actual_end:window.end}:null;
  }).filter(Boolean);
  if(localRows.length){
   const event={event_id:collabEventId,sync:{available:collabSyncVerified},streams:localRows};
   applyCollabEvent(event);
   if(collabSyncVerified&&localRows.length===streams.length&&initViewingTimeline(event))return;
   if(collabSyncVerified&&localRows.length===streams.length){
    const starts=localRows.map(collabStartMs).filter(Number.isFinite);
    if(starts.length){
     collabAbsoluteMs=Math.min(...starts);
     reconcileCollabRows(desiredVodRowsAt(collabAbsoluteMs),{absoluteMs:collabAbsoluteMs});
    }
    collabVodTimer=setInterval(()=>{if(!document.hidden)reconcileVodCollab()},500);
   }
   return;
  }
 }
 const event=await fetchCollabEvent();
 if(!event)return;
 applyCollabEvent(event);
 if(collabKind==='vod'&&event?.sync?.available===true&&initViewingTimeline(event))return;
 if(collabKind==='live'){
  await reconcileLiveCollab();
  collabPollTimer=setInterval(()=>{if(!document.hidden)reconcileLiveCollab()},10000);
  return;
 }
 if(event?.sync?.available===true){
  const starts=[...collabRoster.values()].map(collabStartMs).filter(Number.isFinite);
  if(starts.length){
   collabAbsoluteMs=Math.min(...starts);
   reconcileCollabRows(desiredVodRowsAt(collabAbsoluteMs),{absoluteMs:collabAbsoluteMs});
  }
  collabVodTimer=setInterval(()=>{if(!document.hidden)reconcileVodCollab()},500);
 }
}

function supportStyle(button,row){
 const accent=accentFor(row);
 button.style.setProperty('--member-accent',accent);
 const dual=Array.isArray(row?.member_accent_dual)?row.member_accent_dual:[];
 if(String(row?.support_mode||'')==='dual_color'&&dual.length===2&&dual.every(value=>/^#[0-9a-fA-F]{6}$/.test(String(value)))){
  button.dataset.supportMode='dual_color';
  button.style.setProperty('--member-accent-dual','linear-gradient(135deg,'+dual[0]+' 0 50%,'+dual[1]+' 50% 100%)');
 }
}
function renderLiveRail(rows){
 const activeIds=new Set(streams.map(stream=>stream.videoId));
 const filter=homeLiveFilter();
 const live=rows.filter(row=>{
  const id=String(row?.video_id||'');
  if(String(row?.lifecycle_state||row?.state||'').toLowerCase()!=='live'||!/^[A-Za-z0-9_-]{11}$/.test(id))return false;
  if(filter!=='all'&&catalogGroup(row)!==filter)return false;
  return watchMode!=='multi'||!activeIds.has(id);
 });
 liveList.replaceChildren();
 live.forEach(row=>{
  const button=node('button',undefined,'viewer-live-item');
  button.type='button';
  button.draggable=true;
  button.dataset.videoId=String(row.video_id);
  button.title=catalogName(row);
  supportStyle(button,row);
  button.classList.toggle('is-active',streams.some(stream=>stream.videoId===row.video_id));
  const avatar=node('span',undefined,'viewer-live-avatar');
  const url=safeAvatar(row.avatar_url);
  if(url){
   const img=document.createElement('img');
   img.src=url;
   img.alt='';
   img.loading='lazy';
   avatar.append(img);
  }else{
   avatar.append(node('span',[...catalogName(row)][0]||'H'));
  }
  avatar.append(node('i'));
  button.append(avatar,node('strong',catalogName(row)));
  button.addEventListener('click',()=>handleLiveRailClick(row));
  button.addEventListener('dragstart',event=>{
   draggedLiveId=String(row.video_id);
   event.dataTransfer?.setData('text/plain',draggedLiveId);
   if(event.dataTransfer)event.dataTransfer.effectAllowed='copy';
   button.classList.add('is-dragging');
   showDragDropOverlay();
  });
  button.addEventListener('dragend',()=>{
   draggedLiveId='';
   button.classList.remove('is-dragging');
   hideDragDropOverlay();
  });
  liveList.append(button);
 });
 liveRail.hidden=!liveList.childElementCount;
}
window.addEventListener('storage',event=>{if(event.key===HOME_FILTER_KEY)renderLiveRail(catalogRows)});
async function loadCatalog(){
 try{
  const data=await api('/v1/catalog/today');
  const rows=data.streams||data.items;
  if(!Array.isArray(rows))throw new Error('資料格式錯誤');
  catalogRows=rows;
  const byId=new Map(rows.map(row=>[String(row.video_id||''),row]));
  streams.forEach((stream,index)=>{
   const row=byId.get(stream.videoId);
   if(!row)return;
   stream.label=catalogName(row);
   stream.channelId=String(row.channel_id||'');
   stream.avatarUrl=safeAvatar(row.avatar_url);
   const label=playerCards[index]?.querySelector('.player-label');
   if(label)label.textContent=playerDisplayLabel(stream);
  });
  renderControls();
  renderLiveRail(rows);
 }catch{
  liveRail.hidden=true;
 }
}

function taipeiDay(){
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
 const out=Object.fromEntries(parts.filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function taipeiDayForDate(value){
 const date=value instanceof Date?value:new Date(value);
 if(!Number.isFinite(date.getTime()))return '';
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
 const out=Object.fromEntries(parts.filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function pttKey(row){return String(row?.source_record_key||row?.push_id||row?.aid+':'+row?.source_line)}
function pttRow(row){
 const el=node('div',undefined,'ptt-row');
 el.dataset.pushId=pttKey(row);
 const kind=String(row?.kind||'→');
 const kindEl=node('span',kind,'ptt-kind'+(kind==='噓'?' boo':kind==='→'?' arrow':''));
 const when=new Date(String(row?.occurred_at||''));
 let clock='';
 if(Number.isFinite(when.getTime()))clock=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(when);
 const time=node('span',clock,'ptt-time');
 const floor=Number.isInteger(row?.floor)&&row.floor>0?row.floor:null;
 const floorEl=node('span',floor===null?'':floor+'樓','ptt-floor');
 if(floor!==null)el.classList.add('has-floor');
 else floorEl.setAttribute('aria-hidden','true');
 const body=node('span',undefined,'ptt-body');
 body.append(node('span',String(row?.author||'unknown')+':','ptt-author'),node('span',String(row?.content||''),'ptt-content'));
 el.append(kindEl,time,floorEl,body);
 return el;
}
function setPttFloorVisible(show){
 pttPanel.classList.toggle('ptt-floor-hidden',!show);
 pttShowFloor.checked=Boolean(show);
}
pttShowFloor.addEventListener('change',()=>setPttFloorVisible(pttShowFloor.checked));
setPttFloorVisible(false);

function pttAtBottom(){return pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48}
function markPttUserScrollIntent(ms=1800){pttUserScrollIntentUntil=performance.now()+ms}
function hasPttUserScrollIntent(){return performance.now()<=pttUserScrollIntentUntil}
function repinPttAfterLayout({force=false}={}){
 const shouldFollow=force||pttFollowing;
 clearTimeout(pttLayoutRepinTimer);
 cancelAnimationFrame(pttResizeFrame);
 if(!shouldFollow||pttPanel.hidden)return;
 pttLayoutRepinTimer=setTimeout(()=>{
  pttResizeFrame=requestAnimationFrame(()=>{
   if(pttVodMode())syncVodPttTimeline({forceFollow:true});
   else{
    pttFeed.scrollTop=pttFeed.scrollHeight;
    pttNewest.hidden=true;
    pttFollowing=true;
   }
  });
 },80);
}
function preservePttFollowDuringLayout(change){
 const wasFollowing=pttFollowing||pttAtBottom();
 change();
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
}
function pttVodMode(){return pttContext.mode==='vod'}
function pttTimelineClock(ms){
 const date=new Date(ms);
 if(!Number.isFinite(date.getTime()))return '';
 return new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(date);
}
function vodPttCutoffMs(context,seconds,hasPlayed){
 const startMs=Date.parse(String(context?.start||''));
 if(!Number.isFinite(startMs)||!Number.isFinite(seconds))return null;
 const scheduledMs=Date.parse(String(context?.scheduledStart||''));
 if(!hasPlayed&&seconds<=3&&Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000)return scheduledMs;
 const endMs=Date.parse(String(context?.end||''));
 const raw=startMs+Math.max(0,seconds)*1000;
 return Number.isFinite(endMs)?Math.min(raw,endMs):raw;
}
function vodPttFetchStartMs(context){
 const startMs=Date.parse(String(context?.start||''));
 const scheduledMs=Date.parse(String(context?.scheduledStart||''));
 if(!Number.isFinite(startMs))return null;
 const hasScheduled=Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000;
 const anchorMs=hasScheduled?Math.min(startMs,scheduledMs):startMs;
 return anchorMs-3600000;
}
function pttVodPlaybackMs(){
 if(!pttVodMode())return null;
 if(viewingTimelineActive())return viewingAdapter.absoluteTimeMs();
 let seconds=null;
 try{seconds=players[primaryIndex]?.getCurrentTime?.()}catch{}
 return vodPttCutoffMs(pttContext,seconds,pttVodHasPlayed);
}
function pttToLatest(){
 if(pttVodMode())syncVodPttTimeline({forceFollow:true});
 pttFeed.scrollTop=pttFeed.scrollHeight;
 pttNewest.hidden=true;
 pttFollowing=true;
}
function resetPttFeed(){
 pttLoaded=false;
 pttFollowing=true;
 pttNewest.hidden=true;
 pttNewest.textContent='最新';
 pttVodRows=[];
 pttVodPresentationTimes=[];
 pttVodVisibleCount=0;
 pttVodLastSample=null;
 pttVodHasPlayed=false;
 pttFeed.replaceChildren();
}
function showPttUnavailable(message,meta='無可用專串'){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 專串';
 pttMeta.textContent=meta;
 pttFeed.replaceChildren(node('div',message,'ptt-empty'));
 pttNewest.hidden=true;
}
async function loadLivePtt(){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 今日專串';
 const day=taipeiDay();
 const beforeAtBottom=pttFollowing||pttAtBottom();
 try{
  const data=await api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=300');
  if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes))throw new Error('資料格式錯誤');
  const rows=data.pushes.filter(row=>row&&typeof row.content==='string');
  if(!pttLoaded){
   pttFeed.replaceChildren(...rows.map(pttRow));
   pttLoaded=true;
  }else{
   const seen=new Set([...pttFeed.children].map(el=>el.dataset.pushId));
   rows.forEach(row=>{
    const key=pttKey(row);
    if(!seen.has(key)){pttFeed.append(pttRow(row));seen.add(key)}
   });
   while(pttFeed.children.length>300)pttFeed.firstElementChild?.remove();
  }
  const freshness=String(data.freshness?.status||'unknown');
  pttMeta.textContent=day.replaceAll('-','/')+' · '+pttFeed.children.length+' 則 · '+(freshness==='fresh'?'即時':freshness==='stale'?'資料稍舊':'狀態未知');
  if(beforeAtBottom)requestAnimationFrame(pttToLatest);
 }catch{
  pttMeta.textContent=day.replaceAll('-','/')+' · 讀取失敗';
  if(!pttLoaded)pttFeed.replaceChildren(node('div','PTT 暫時無法讀取，稍後會自動重試。','ptt-empty'));
 }
}
function verifiedEndedVodWindow(row){
 const lifecycle=String(row?.lifecycle_state||row?.state||'').toLowerCase();
 const start=String(row?.actual_start||''),end=String(row?.actual_end||'');
 const startMs=Date.parse(start),endMs=Date.parse(end);
 if(lifecycle!=='ended'||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)return null;
 const scheduledStart=String(row?.scheduled_start||'');
 const scheduledMs=Date.parse(scheduledStart);
 return {start,end,day:taipeiDayForDate(start),anchorSource:PTT_ARCHIVE_ANCHOR,
  scheduledStart:Number.isFinite(scheduledMs)&&Math.abs(scheduledMs-startMs)<=43200000?scheduledStart:''};
}
async function loadTodayPttPayload(day){
 return api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=300');
}
async function loadPttDayWindowRows(day,startMs,endMs){
 if(day===taipeiDay()){
  try{
   const latest=await loadTodayPttPayload(day);
   if(latest?.schema_version==='public-consumer-v1'&&Array.isArray(latest.pushes)){
    const timed=latest.pushes.map(row=>({row,ms:Date.parse(String(row?.occurred_at||''))}))
     .filter(item=>item.row&&typeof item.row.content==='string'&&Number.isFinite(item.ms))
     .sort((a,b)=>a.ms-b.ms);
    if(timed.length&&timed[0].ms<=startMs&&timed[timed.length-1].ms>=endMs){
     return {
      rows:dedupeArchiveRows(timed.filter(item=>item.ms>=startMs&&item.ms<endMs).map(item=>item.row)),
      pages:0,incomplete:false,envelope:latest,source:'today-tail'
     };
    }
   }
  }catch{}
 }
 const rows=[],seenCheckpoints=new Set();
 let after='',pages=0,lastEnvelope=null,reachedEnd=false;
 while(pages<VOD_PTT_HISTORY_PAGE_CAP){
  const path='/v1/ptt/history?day='+encodeURIComponent(day)+'&limit=200'+
   (after?'&after='+encodeURIComponent(after):'');
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
 const incomplete=!reachedEnd&&Boolean(lastEnvelope?.page?.has_more);
 return {rows:dedupeArchiveRows(rows),pages,incomplete,envelope:lastEnvelope,source:'history'};
}
function buildVodPttPresentationTimes(rows){
 const times=new Array(rows.length);
 let index=0;
 while(index<rows.length){
  const raw=Date.parse(String(rows[index]?.occurred_at||''));
  const minuteStart=Math.floor(raw/60000)*60000;
  let end=index+1;
  while(end<rows.length){
   const next=Date.parse(String(rows[end]?.occurred_at||''));
   if(Math.floor(next/60000)*60000!==minuteStart)break;
   end+=1;
  }
  const count=end-index;
  const minuteOnly=Array.from({length:count},(_,offset)=>
   Date.parse(String(rows[index+offset]?.occurred_at||''))===minuteStart
  ).every(Boolean);
  for(let offset=0;offset<count;offset++){
   const occurred=Date.parse(String(rows[index+offset]?.occurred_at||''));
   times[index+offset]=minuteOnly
    ?minuteStart+Math.floor(offset*60000/Math.max(1,count))
    :occurred;
  }
  index=end;
 }
 return times;
}
function vodPttVisibleCountAt(rows,absoluteMs,presentationTimes=null){
 const times=Array.isArray(presentationTimes)&&presentationTimes.length===rows.length
  ?presentationTimes:buildVodPttPresentationTimes(rows);
 let low=0,high=rows.length;
 while(low<high){
  const mid=(low+high)>>1;
  if(times[mid]<=absoluteMs)low=mid+1;
  else high=mid;
 }
 return low;
}
function setVodPttRows(rows){
 pttVodRows=(Array.isArray(rows)?rows:[]).filter(row=>
  row&&typeof row.content==='string'&&Number.isFinite(Date.parse(String(row.occurred_at||'')))
 ).slice().sort((a,b)=>
  Date.parse(String(a.occurred_at||''))-Date.parse(String(b.occurred_at||''))||
  String(pttKey(a)).localeCompare(String(pttKey(b))));
 pttVodPresentationTimes=buildVodPttPresentationTimes(pttVodRows);
 pttVodVisibleCount=0;
 pttVodLastSample=null;
 pttFeed.replaceChildren();
}
function syncVodPttTimeline({forceFollow=false}={}){
 if(!pttVodMode()||!pttLoaded)return;
 const absoluteMs=pttVodPlaybackMs();
 if(!Number.isFinite(absoluteMs))return;
 const now=performance.now();
 let seeked=forceFollow;
 if(pttVodLastSample){
  const elapsed=Math.max(0,now-pttVodLastSample.wallMs)/1000;
  const expected=pttVodLastSample.seconds+(pttVodLastSample.playing?elapsed:0);
  const currentSeconds=Math.max(0,(absoluteMs-Date.parse(pttContext.start))/1000);
  if(currentSeconds<pttVodLastSample.seconds-.75||Math.abs(currentSeconds-expected)>2.5)seeked=true;
 }
 let playing=false;
 try{playing=players[primaryIndex]?.getPlayerState?.()===YT.PlayerState.PLAYING}catch{}
 const currentSeconds=Math.max(0,(absoluteMs-Date.parse(pttContext.start))/1000);
 pttVodLastSample={seconds:currentSeconds,wallMs:now,playing};

 const visible=vodPttVisibleCountAt(pttVodRows,absoluteMs,pttVodPresentationTimes);
 if(visible!==pttVodVisibleCount){
  if(visible>pttVodVisibleCount){
   const fragment=document.createDocumentFragment();
   for(let i=pttVodVisibleCount;i<visible;i++)fragment.append(pttRow(pttVodRows[i]));
   if(pttFeed.querySelector('.ptt-empty'))pttFeed.replaceChildren();
   pttFeed.append(fragment);
  }else{
   pttFeed.replaceChildren(...pttVodRows.slice(0,visible).map(pttRow));
  }
  pttVodVisibleCount=visible;
 }
 if(!visible&&!pttFeed.children.length){
  pttFeed.replaceChildren(node('div','目前播放位置之前尚無 PTT 推文。','ptt-empty'));
 }
 const clock=pttTimelineClock(absoluteMs);
 pttNewest.textContent=clock?'最新 · '+clock:'最新';
 if(seeked){
  pttFollowing=true;
  requestAnimationFrame(()=>{
   pttFeed.scrollTop=pttFeed.scrollHeight;
   pttNewest.hidden=true;
  });
 }else if(pttFollowing||pttAtBottom()){
  requestAnimationFrame(()=>{
   pttFeed.scrollTop=pttFeed.scrollHeight;
   pttNewest.hidden=true;
  });
 }else{
  pttNewest.hidden=false;
 }
}
function startVodPttTimeline(){
 clearInterval(pttVodPollTimer);
 pttVodPollTimer=setInterval(()=>syncVodPttTimeline(),500);
 syncVodPttTimeline({forceFollow:true});
}
const archiveManifestCache=new Map();
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
 const first=taipeiDayForDate(new Date(startMs));
 const last=taipeiDayForDate(new Date(endMs-1));
 if(!first||!last)return [];
 const days=[];for(let day=first;day&&day<=last;day=nextIsoDay(day))days.push(day);
 return days;
}
function archiveMonthKeys(startMs,endMs){
 const firstDay=taipeiDayForDate(new Date(startMs));
 const lastDay=taipeiDayForDate(new Date(endMs-1));
 const first=/^\d{4}-\d{2}-\d{2}$/.test(firstDay)?firstDay.slice(0,7):'';
 const last=/^\d{4}-\d{2}-\d{2}$/.test(lastDay)?lastDay.slice(0,7):'';
 if(!first||!last)return [];
 const cursor=new Date(first+'-01T00:00:00Z');
 const stop=new Date(last+'-01T00:00:00Z');
 const months=[];
 while(cursor<=stop){
  months.push(cursor.toISOString().slice(0,7));
  cursor.setUTCMonth(cursor.getUTCMonth()+1);
 }
 return months;
}
function archiveSourceForMonth(month){
 const raw=PTT_ARCHIVE_MONTHS?.[month];
 const base=String(raw?.base||'').replace(/\/$/,'');
 const manifest=String(raw?.manifest||'');
 if(!/^\d{4}-\d{2}$/.test(month)||!/^https:\/\//.test(base)||!manifest.startsWith('/'))return null;
 return {month,base,manifest};
}
function archiveSourcesForWindow(startMs,endMs){
 const months=archiveMonthKeys(startMs,endMs);
 if(!months.length)throw archiveUnavailableError('歷史 PTT 無法判定 VOD 的 Asia/Taipei 月份');
 const missing=months.filter(month=>!archiveSourceForMonth(month));
 if(missing.length)throw archiveUnavailableError('歷史 PTT 月份來源未設定：'+missing.join(', '));
 return months.map(month=>archiveSourceForMonth(month));
}
function archiveObjectRange(item){
 const startRaw=item?.partition_start??item?.range_start??item?.bucket_start;
 const endRaw=item?.partition_end??item?.range_end??item?.bucket_end;
 const startMs=Date.parse(String(startRaw||'')),endMs=Date.parse(String(endRaw||''));
 if(!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)return null;
 return {startMs,endMs,start:String(startRaw),end:String(endRaw)};
}
function archiveObjectPushCount(item){
 const value=item?.push_count??item?.pushes;
 return Number.isInteger(value)&&value>=0?value:null;
}
function archiveRangesIntersect(aStart,aEnd,bStart,bEnd){
 return Number.isFinite(aStart)&&Number.isFinite(aEnd)&&Number.isFinite(bStart)&&Number.isFinite(bEnd)&&
  aStart<bEnd&&bStart<aEnd;
}
async function archiveSha256Hex(buffer){
 if(!globalThis.crypto?.subtle)throw new Error('瀏覽器不支援歷史檔案完整性驗證');
 const digest=await crypto.subtle.digest('SHA-256',buffer);
 return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
function validateArchiveManifest(manifest){
 if(manifest?.schema_version!==PTT_ARCHIVE_SCHEMA||manifest?.precision!=='minute'||
    manifest?.timezone!=='UTC'||!Array.isArray(manifest?.objects)||!Array.isArray(manifest?.days))
  throw new Error('歷史 PTT manifest 格式不支援');
 const seen=new Set();
 for(const item of manifest.objects){
  const range=archiveObjectRange(item),pushCount=archiveObjectPushCount(item);
  if(!item||typeof item.key!=='string'||!item.key.endsWith('.json')||seen.has(item.key)||
     !/^[0-9a-f]{64}$/.test(String(item.sha256||''))||!range||pushCount===null)
    throw new Error('歷史 PTT manifest 物件索引無效');
  seen.add(item.key);
 }
 return manifest;
}
async function fetchArchiveManifest(source,force=false){
 const cacheKey=source.month+'|'+source.base+'|'+source.manifest;
 if(archiveManifestCache.has(cacheKey)&&!force)return archiveManifestCache.get(cacheKey);
 const url=source.base+source.manifest;
 let response;
 try{
  response=await fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}});
 }catch(error){
  throw archiveUnavailableError('歷史 PTT '+source.month+' manifest 無法讀取：'+url+' · '+String(error?.message||error));
 }
 if(!response.ok)throw archiveUnavailableError('歷史 PTT '+source.month+' manifest HTTP '+response.status+'：'+url);
 const manifest=validateArchiveManifest(await response.json());
 archiveManifestCache.set(cacheKey,manifest);
 return manifest;
}
async function fetchArchiveObject(source,item){
 const url=source.base+'/'+item.key;
 let response;
 try{
  response=await fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}});
 }catch(error){
  throw archiveUnavailableError('歷史 PTT '+source.month+' object 無法讀取：'+url+' · '+String(error?.message||error));
 }
 if(!response.ok)throw archiveUnavailableError('歷史 PTT '+source.month+' object HTTP '+response.status+'：'+url);
 const contentType=String(response.headers.get('content-type')||'').toLowerCase();
 if(!contentType.startsWith('application/json'))throw archiveIntegrityError('歷史 PTT '+source.month+' object Content-Type 不符：'+url);
 const buffer=await response.arrayBuffer();
 const digest=await archiveSha256Hex(buffer);
 if(digest!==String(item.sha256))throw archiveIntegrityError('歷史 PTT '+source.month+' object SHA 不符：'+url);
 let payload;
 try{payload=JSON.parse(new TextDecoder().decode(buffer))}catch{throw archiveIntegrityError('歷史 PTT '+source.month+' object JSON 無效：'+url)}
 const expectedRange=archiveObjectRange(item);
 const payloadRange=archiveObjectRange(payload);
 const expectedPushCount=archiveObjectPushCount(item);
 if(payload?.schema_version!==PTT_ARCHIVE_SCHEMA||!Array.isArray(payload?.pushes)||
    payload.pushes.length!==expectedPushCount)throw archiveIntegrityError('歷史 PTT '+source.month+' object push count 不符：'+url);
 if(!expectedRange||!payloadRange||payloadRange.startMs!==expectedRange.startMs||
    payloadRange.endMs!==expectedRange.endMs)throw archiveIntegrityError('歷史 PTT '+source.month+' object range 不符：'+url);
 return payload.pushes;
}
function taipeiDayStartMs(day){
 const ms=Date.parse(String(day||'')+'T00:00:00+08:00');
 return Number.isFinite(ms)?ms:null;
}
function archiveDayCoverageStatus(manifest,day){
 const row=Array.isArray(manifest?.days)?manifest.days.find(item=>String(item?.day||'')===String(day||'')):null;
 const status=String(row?.coverage_status||'MISSING');
 return ['COMPLETE','PARTIAL','MISSING','UNKNOWN'].includes(status)?status:'UNKNOWN';
}
async function resolveArchiveDaySlice(day,rangeStart,rangeEnd){
 const month=String(day||'').slice(0,7);
 const source=archiveSourceForMonth(month);
 if(!source)throw archiveUnavailableError('歷史 PTT 月份來源未設定：'+month);
 let lastError=null;
 for(let attempt=0;attempt<2;attempt++){
  try{
   const manifest=await fetchArchiveManifest(source,attempt===1);
   const coverageStatus=archiveDayCoverageStatus(manifest,day);
   const plan=archiveObjectPlan([{source,manifest}],rangeStart,rangeEnd);
   const rows=[];
   for(const entry of plan){
    const pushes=await fetchArchiveObject(entry.source,entry.item);
    for(const row of pushes){
     const occurred=Date.parse(String(row?.occurred_at||''));
     if(Number.isFinite(occurred)&&occurred>=rangeStart&&occurred<rangeEnd)rows.push(row);
    }
   }
   return {day,source,coverageStatus,rows:dedupeArchiveRows(rows),
           objectRequests:plan.map(entry=>entry.source.base+'/'+entry.item.key)};
  }catch(error){
   lastError=error;
   if(attempt===0&&error?.archiveIntegrity){
    archiveManifestCache.clear();
    continue;
   }
   break;
  }
 }
 throw lastError||archiveUnavailableError('歷史 PTT '+day+' 無法讀取');
}
async function resolveCoverageDrivenVodPtt(context){
 const startMs=Date.parse(String(context?.start||'')),endMs=Date.parse(String(context?.end||''));
 if(context?.anchorSource!==PTT_ARCHIVE_ANCHOR||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)
  throw new Error('缺少可信的 YouTube actualStartTime / actualEndTime');
 const fetchStartMs=vodPttFetchStartMs(context)??startMs;
 const days=archiveCoverageDays(fetchStartMs,endMs);
 if(!days.length)throw new Error('VOD PTT 無法判定 Asia/Taipei 日期');
 const rows=[],dayResults=[];
 for(const day of days){
  const dayStart=taipeiDayStartMs(day),nextStart=taipeiDayStartMs(nextIsoDay(day));
  if(!Number.isFinite(dayStart)||!Number.isFinite(nextStart))continue;
  const rangeStart=Math.max(fetchStartMs,dayStart);
  const rangeEnd=Math.min(endMs,nextStart);
  if(rangeEnd<=rangeStart)continue;
  let archive=null,archiveError=null,d1=null,d1Error=null;
  try{archive=await resolveArchiveDaySlice(day,rangeStart,rangeEnd)}
  catch(error){archiveError=error}
  if(!archive||archive.coverageStatus!=='COMPLETE'){
   try{d1=await loadPttDayWindowRows(day,rangeStart,rangeEnd)}
   catch(error){d1Error=error}
  }
  if(archive?.rows?.length)rows.push(...archive.rows);
  if(d1?.rows?.length)rows.push(...d1.rows);
  dayResults.push({day,rangeStart,rangeEnd,archive,archiveError,d1,d1Error});
 }
 const merged=dedupeArchiveRows(rows);
 const allArchiveComplete=dayResults.length>0&&dayResults.every(item=>item.archive?.coverageStatus==='COMPLETE');
 const d1Days=dayResults.filter(item=>item.d1).map(item=>item.day);
 const d1IncompleteDays=dayResults.filter(item=>item.d1?.incomplete).map(item=>item.day);
 const archiveUnavailableDays=dayResults.filter(item=>!item.archive).map(item=>item.day);
 const unresolvedDays=dayResults.filter(item=>!item.archive&&!item.d1).map(item=>item.day);
 const nonCompleteDays=dayResults.filter(item=>item.archive&&item.archive.coverageStatus!=='COMPLETE').map(item=>item.day);
 return {
  rows:merged,days:dayResults.map(item=>item.day),
  allArchiveComplete,authoritativeZero:allArchiveComplete&&merged.length===0,
  d1Days,d1IncompleteDays,archiveUnavailableDays,unresolvedDays,nonCompleteDays
 };
}
function archiveRowIdentity(row){
 const stable=String(row?.source_record_key||row?.push_id||'');
 if(stable)return stable;
 const aid=String(row?.aid||''),line=Number(row?.source_line);
 if(aid&&Number.isInteger(line)&&line>=0)return aid+'|source_line:'+line;
 const occurred=String(row?.occurred_at||''),author=String(row?.author||row?.user||''),body=String(row?.content||row?.text||'');
 return occurred+'|'+author+'|'+body;
}
function dedupeArchiveRows(rows){
 const sorted=rows.slice().sort((a,b)=>Date.parse(String(a.occurred_at||''))-Date.parse(String(b.occurred_at||''))||
  String(a.aid||'').localeCompare(String(b.aid||''))||
  (Number(a.source_line)||0)-(Number(b.source_line)||0)||
  String(a.push_id||'').localeCompare(String(b.push_id||''))||
  (Number(a.floor)||0)-(Number(b.floor)||0));
 const seen=new Set(),deduped=[];
 for(const row of sorted){
  const key=archiveRowIdentity(row);
  if(!key||seen.has(key))continue;
  seen.add(key);deduped.push(row);
 }
 return deduped;
}
function archiveObjectPlan(archives,startMs,endMs){
 const plan=[];
 for(const archive of archives){
  for(const item of archive.manifest.objects){
   const range=archiveObjectRange(item);
   if(!range||!archiveRangesIntersect(range.startMs,range.endMs,startMs,endMs))continue;
   plan.push({source:archive.source,item,range});
  }
 }
 return plan.sort((a,b)=>a.range.startMs-b.range.startMs||
  a.range.endMs-b.range.endMs||String(a.item.key).localeCompare(String(b.item.key)));
}
async function loadCoverageDrivenVodPtt(context,token){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 歷史專串';
 pttMeta.textContent='VOD PTT · 判定 Archive coverage / D1 中';
 try{
  const result=await resolveCoverageDrivenVodPtt(context);
  if(token!==pttResolveToken)return;
  setVodPttRows(result.rows);
  pttLoaded=true;pttFollowing=true;pttNewest.hidden=true;
  const dayLabel=result.days.length?result.days.join('～'):(context.day||'').replaceAll('-','/');
  const usedD1=result.d1Days.length>0;
  const archiveUnavailable=result.archiveUnavailableDays.length>0;
  const archiveUnavailableAll=result.days.length>0&&result.archiveUnavailableDays.length===result.days.length;
  const incomplete=result.d1IncompleteDays.length>0;
  let sourceLabel='';
  if(result.allArchiveComplete)sourceLabel='歷史封存完整';
  else if(usedD1&&archiveUnavailableAll)sourceLabel='D1 history · ⚠ Archive 尚不可用';
  else if(usedD1&&!archiveUnavailable)sourceLabel='Archive + D1 · ⚠ 尚未完成封存';
  else if(usedD1&&archiveUnavailable)sourceLabel='Archive + D1 · ⚠ Archive 部分尚不可用';
  else if(archiveUnavailable)sourceLabel='⚠ Archive 尚不可用';
  else sourceLabel='⚠ Archive coverage 尚未 COMPLETE';
  if(incomplete)sourceLabel+=' · ⚠ D1 分頁上限，資料可能不完整';
  if(result.unresolvedDays.length)sourceLabel+=' · ⚠ UNKNOWN / UNAVAILABLE';
  pttMeta.textContent=dayLabel+' · '+result.rows.length+' 則 · VOD · 對齊播放時間 · '+sourceLabel;
  if(!result.rows.length){
   let message='';
   if(result.authoritativeZero)message='這段 VOD 時間範圍內沒有 PTT 推文。';
   else if(result.unresolvedDays.length)message='VOD PTT UNKNOWN / UNAVAILABLE：Archive 與 D1 都無法確認完整資料。';
   else if(incomplete)message='目前沒有取得可顯示推文；D1 分頁達安全上限，資料可能不完整。';
   else message='目前沒有取得可顯示推文；Archive 尚未 COMPLETE，不能宣稱這段真正沒有推文。';
   pttFeed.replaceChildren(node('div',message,'ptt-empty'));
  }
  startVodPttTimeline();
 }catch(error){
  if(token!==pttResolveToken)return;
  const detail=String(error?.message||error);
  pttMeta.textContent='VOD PTT · UNKNOWN / UNAVAILABLE';
  pttFeed.replaceChildren(node('div','VOD PTT UNKNOWN / UNAVAILABLE：'+detail,'ptt-empty'));
 }
}
async function resolveViewingSessionPtt(){
 clearInterval(pttVodPollTimer);pttVodPollTimer=null;
 if(!viewingTimelineActive())return false;
 const token=++pttResolveToken;
 resetPttFeed();pttPanel.hidden=false;pttTitle.textContent='PTT 專串';
 const startMs=viewingSession.absolute_start_ms;
 const endMs=startMs+viewingSession.master_end_ms;
 const start=new Date(startMs).toISOString(),end=new Date(endMs).toISOString();
 pttContext={mode:'vod',videoId:'',start,end,scheduledStart:'',
             day:taipeiDayForDate(start),anchorSource:PTT_ARCHIVE_ANCHOR};
 updateUrl();
 await loadCoverageDrivenVodPtt(pttContext,token);
 return true;
}
async function resolvePrimaryPtt(){
 if(viewingTimelineActive()){await resolveViewingSessionPtt();return}
 clearInterval(pttVodPollTimer);pttVodPollTimer=null;
 const stream=streams[primaryIndex];
 if(!stream){showPttUnavailable('沒有可判定的影片。');return}
 const token=++pttResolveToken;
 const id=stream.videoId;
 resetPttFeed();
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 專串';

 const suppliedWindow=archiveWindows.get(id);
 if(suppliedWindow){
  pttContext={mode:'vod',videoId:id,start:suppliedWindow.start,end:suppliedWindow.end,
              scheduledStart:suppliedWindow.scheduledStart||'',
              day:taipeiDayForDate(suppliedWindow.start),anchorSource:suppliedWindow.anchorSource};
  updateUrl();
  await loadCoverageDrivenVodPtt(pttContext,token);
  return;
 }

 pttMeta.textContent='判定影片狀態中';
 try{
  const row=await videoMetadata(id);
  if(token!==pttResolveToken)return;
  const lifecycle=String(row?.lifecycle_state||row?.state||'').toLowerCase();
  if(lifecycle==='live'){
   pttContext={mode:'live',videoId:id,start:'',end:'',day:taipeiDay()};
   updateUrl();
   await loadLivePtt();
   return;
  }
  if(['upcoming','waiting'].includes(lifecycle)){
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable('這支影片尚未開始，沒有可連接的 PTT 時間軸。','尚未開始');
   return;
  }
  if(lifecycle==='ended'){
   const vodWindow=verifiedEndedVodWindow(row);
   if(vodWindow){
    const cached={videoId:id,start:vodWindow.start,end:vodWindow.end,
                  anchorSource:vodWindow.anchorSource,scheduledStart:vodWindow.scheduledStart||''};
    archiveWindows.set(id,cached);
    pttContext={mode:'vod',videoId:id,start:cached.start,end:cached.end,
                scheduledStart:cached.scheduledStart,day:vodWindow.day,anchorSource:cached.anchorSource};
    updateUrl();
    await loadCoverageDrivenVodPtt(pttContext,token);
    return;
   }
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable('這支已結束影片缺少可信的 actualStartTime / actualEndTime，因此不會猜測 PTT 時間軸。','VOD 時間窗不足');
   return;
  }
  pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
  updateUrl();
  showPttUnavailable('目前無法判定這支影片的直播狀態，因此不會連接可能錯誤的 PTT。','狀態無法判定');
 }catch{
  if(token!==pttResolveToken)return;
  const todayRow=catalogRows.find(row=>String(row?.video_id||'')===id);
  const todayState=String(todayRow?.lifecycle_state||todayRow?.state||'').toLowerCase();
  if(todayState==='live'){
   pttContext={mode:'live',videoId:id,start:'',end:'',day:taipeiDay()};
   updateUrl();
   await loadLivePtt();
   return;
  }
  const vodWindow=verifiedEndedVodWindow(todayRow);
  if(vodWindow){
   pttContext={mode:'vod',videoId:id,start:vodWindow.start,end:vodWindow.end,
               scheduledStart:vodWindow.scheduledStart||'',
               day:vodWindow.day,anchorSource:vodWindow.anchorSource};
   updateUrl();
   await loadCoverageDrivenVodPtt(pttContext,token);
   return;
  }
  pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
  updateUrl();
  showPttUnavailable('暫時無法取得這支影片的可信 lifecycle / actual time，因此不會誤接其他日期的 PTT。','無法判定');
 }
}
async function loadPtt(){
 if(pttContext.mode==='live')await loadLivePtt();
}

function startCarousel(){
 clearInterval(carouselTimer);
 carouselTimer=null;
 if(currentLayoutPreset()==='equal'||watchMode!=='multi'||streams.length<2)return;
 const ms=Math.max(30,Math.min(60,Number(carouselInterval.value)||30))*1000;
 if(currentLayoutPreset()==='primary'){
  carouselTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length),ms);
 }else{
  carouselTimer=setInterval(()=>{
   const secondaryCount=Math.max(0,streams.length-1);
   if(!secondaryCount)return;
   secondaryOffset=(secondaryOffset+Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryCount))%secondaryCount;
   refreshControlState();
  },ms);
 }
}
function readSettings(){
 try{
  const font=Math.max(12,Math.min(26,Number(localStorage.getItem('holoviewer-viewer-ptt-font'))||14));
  pttFontSize.value=String(font);
  pttFontValue.textContent=font+'px';
  document.documentElement.style.setProperty('--ptt-font-size',font+'px');
 }catch{}
}

stage.addEventListener('drop',event=>{
 // Fallback for drops that land outside the overlay.
 if(!/^[A-Za-z0-9_-]{11}$/.test(draggedLiveId))return;
 event.preventDefault();
 const id=String(event.dataTransfer?.getData('text/plain')||draggedLiveId||'');
 draggedLiveId='';
 hideDragDropOverlay();
 const row=catalogRows.find(item=>String(item?.video_id||'')===id);
 if(row)addDraggedLive(row);
});

callModeButton.addEventListener('click',()=>setCallMode(false));
document.addEventListener('keydown',handleCallKeyDown);
document.addEventListener('keyup',handleCallKeyUp);

settingsButton.addEventListener('click',()=>{
 if(watchMode==='single')return;
 const open=controls.hidden;
 if(open){
  document.body.classList.add('settings-open');
  controls.hidden=false;
  settingsButton.classList.add('active');
  settingsButton.setAttribute('aria-expanded','true');
 }else{
  hideSettings();
 }
});
multiModeSwitch.addEventListener('change',()=>switchWatchMode(multiModeSwitch.checked?'multi':'single'));
syncPlayback.addEventListener('change',()=>{
 if(!syncPlayback.checked||watchMode!=='multi'||streams.length<2)return;
 let state=null;
 try{state=players[primaryIndex]?.getPlayerState()}catch{}
 if(state===YT.PlayerState.PLAYING||state===YT.PlayerState.PAUSED)syncPlayers(state,primaryIndex);
});
document.querySelectorAll('[data-layout-preset]').forEach(button=>button.addEventListener('click',()=>{
 setLayoutPreset(button.dataset.layoutPreset);
}));
function flashTransport(button){button.classList.add('is-feedback');clearTimeout(button._feedbackTimer);button._feedbackTimer=setTimeout(()=>button.classList.remove('is-feedback'),300)}
playAll.addEventListener('click',()=>{flashTransport(playAll);players.forEach(player=>{try{player?.playVideo()}catch{}})});
pauseAll.addEventListener('click',()=>{flashTransport(pauseAll);players.forEach(player=>{try{player?.pauseVideo()}catch{}})});
carousel.addEventListener('change',()=>{
 carouselIntervalGroup.hidden=!carousel.checked;
 startCarousel();
});
carouselInterval.addEventListener('input',()=>{
 carouselOutput.textContent=carouselInterval.value+'s';
 if(focusCarouselStatus&&!focusCarouselStatus.hidden&&currentLayoutPreset()==='primary')focusCarouselStatus.textContent='↻ '+carouselInterval.value+'s';
 startCarousel();
});
pttFontSize.addEventListener('input',()=>{
 const size=Math.max(12,Math.min(26,Number(pttFontSize.value)||14));
 pttFontValue.textContent=size+'px';
 document.documentElement.style.setProperty('--ptt-font-size',size+'px');
 try{localStorage.setItem('holoviewer-viewer-ptt-font',String(size))}catch{}
});
pttFeed.addEventListener('scroll',()=>{
 // Layout/fullscreen/ResizeObserver can change scrollTop without user intent.
 // Only explicit user scroll gestures are allowed to change follow state.
 if(pttLayoutTransitionDepth>0||!hasPttUserScrollIntent())return;
 pttFollowing=pttAtBottom();
 pttNewest.hidden=pttFollowing;
 if(!pttFollowing&&pttVodMode()){
  const ms=pttVodPlaybackMs(),clock=pttTimelineClock(ms);
  pttNewest.textContent=clock?'最新 · '+clock:'最新';
 }
},{passive:true});
pttFeed.addEventListener('wheel',event=>{
 markPttUserScrollIntent();
 if(event.deltaY<0){pttFollowing=false;pttNewest.hidden=false}
},{passive:true});
pttFeed.addEventListener('touchstart',()=>markPttUserScrollIntent(2400),{passive:true});
pttFeed.addEventListener('pointerdown',()=>markPttUserScrollIntent(2400),{passive:true});
if('ResizeObserver' in window){
 pttResizeObserver=new ResizeObserver(()=>{
  if(pttFollowing)repinPttAfterLayout({force:true});
 });
 pttResizeObserver.observe(pttFeed);
 pttResizeObserver.observe(pttPanel);
}
pttFeed.addEventListener('dblclick',event=>{
 event.preventDefault();
 window.open('/ptt-today','_blank','noopener,noreferrer');
});
pttNewest.addEventListener('click',pttToLatest);
fullscreenButton.addEventListener('click',async()=>{
 const wasFollowing=pttFollowing||pttAtBottom();
 try{
  if(document.fullscreenElement)await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
 }catch{}
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
});
window.addEventListener('resize',()=>{
 const wasFollowing=pttFollowing||pttAtBottom();
 if(!wasFollowing)return;
 pttFollowing=true;
 repinPttAfterLayout({force:true});
},{passive:true});
window.addEventListener('orientationchange',()=>{
 const wasFollowing=pttFollowing||pttAtBottom();
 if(!wasFollowing)return;
 pttFollowing=true;
 repinPttAfterLayout({force:true});
});
window.addEventListener('blur',()=>{
 if(!callEnabled)return;
 clearTimeout(callWaveTimer);callWaveTimer=null;callHeldDirection='';callSpaceHeld=false;callClearMotion();callUpdateHud('待機');
});
document.addEventListener('visibilitychange',()=>{
 if(!document.hidden&&pttContext.mode==='live')loadPtt();
});
window.addEventListener('pagehide',()=>{
 clearInterval(collabPollTimer);clearInterval(collabVodTimer);clearInterval(viewingTimer);clearInterval(pttVodPollTimer);clearInterval(pttPollTimer);
 clearTimeout(pttLayoutRepinTimer);cancelAnimationFrame(pttResizeFrame);
 pttResizeObserver?.disconnect();
});
document.addEventListener('fullscreenchange',()=>{
 const wasFollowing=pttFollowing||pttAtBottom();
 const on=Boolean(document.fullscreenElement);
 document.body.classList.toggle('immersive',on);
 fullscreenButton.textContent=on?'退出沉浸模式':'沉浸模式';
 if(wasFollowing){
  pttFollowing=true;
  repinPttAfterLayout({force:true});
 }
});

readSettings();
carousel.checked=currentLayoutPreset()!=='equal';
renderShell();
applyModeClass();
startCarousel();

let viewerReadyForPlayers=false;
function tryMountPlayers(){
 if(!viewerReadyForPlayers||!window.YT?.Player)return;
 mountPlayers();
}
(async()=>{
 if(!archiveVodEntry)await loadCatalog();
 else{liveRail.hidden=true}
 if(collabManaged)await initCollabManager();
 viewerReadyForPlayers=true;
 tryMountPlayers();
 resolvePrimaryPtt();
})();
const pttPollTimer=setInterval(()=>{if(!document.hidden)loadPtt()},PTT_POLL_MS);

if(window.YT?.Player)tryMountPlayers();
else window.onYouTubeIframeAPIReady=tryMountPlayers;
