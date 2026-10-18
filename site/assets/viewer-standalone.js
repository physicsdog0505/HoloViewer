'use strict';

const API_BASE=String(window.HOLOVIEWER_CONFIG?.apiBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_BASE=String(window.HOLOVIEWER_CONFIG?.pttArchiveBase||'').replace(/\/$/,'');
const PTT_ARCHIVE_MANIFEST=String(window.HOLOVIEWER_CONFIG?.pttArchiveManifest||'/ptt/v1/manifests/static-assets-full-2026-10.json');
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
const PTT_ARCHIVE_SCHEMA='ptt-r2-archive-v1';
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
  if(parts.length!==4)continue;
  const [videoId,start,end,anchorSource]=parts;
  const startMs=Date.parse(start),endMs=Date.parse(end);
  if(!/^[A-Za-z0-9_-]{11}$/.test(videoId)||anchorSource!==PTT_ARCHIVE_ANCHOR||
     !Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)continue;
  map.set(videoId,{videoId,start,end,anchorSource});
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
const pttNewest=document.getElementById('pttNewest');
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');

const players=[];
const playerCards=[];
let catalogRows=[];
const syncExpected=new WeakMap();
let carouselTimer=null;
let lockedIndex=null;
let secondaryOffset=0;
let pttFollowing=true;
let pttLoaded=false;
let pttContext={mode:'unresolved',videoId:'',start:'',end:'',day:''};
let pttResolveToken=0;
let confirmedLiveIds=new Set();
let draggedLiveId='';
let collabEvent=null;
let collabRoster=new Map();
let collabPollTimer=null;
let collabVodTimer=null;
let collabAbsoluteMs=null;
let collabReconciling=false;

function api(path){
 if(!API_BASE||!/^https:\/\//.test(API_BASE))return Promise.reject(new Error('正式 API 未設定'));
 return fetch(API_BASE+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}}).then(response=>{
  if(!response.ok)throw new Error('API HTTP '+response.status);
  return response.json();
 });
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
 return workspaceLayout==='focus'?'focus':'primary';
}
function setLayoutPreset(preset){
 if(preset==='equal'){layout='equal';workspaceLayout='sidebar'}
 else if(preset==='focus'){layout='primary';workspaceLayout='focus'}
 else{layout='primary';workspaceLayout='sidebar'}
 carousel.checked=preset!=='equal';
 lockedIndex=preset==='focus'?primaryIndex:null;
 secondaryOffset=0;
 renderControls();
 applyLayout();
 startCarousel();
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
 q.set('workspace',workspaceLayout);
 q.set('ptt',pttContext.mode==='live'?'live':requestedPttMode);
 archiveWindows.forEach(window=>q.append('ptt_window',[window.videoId,window.start,window.end,window.anchorSource].join('|')));
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

function playerHostId(stream){return 'viewer-player-'+String(stream?.videoId||'').replace(/[^A-Za-z0-9_-]/g,'')}
function createPlayerCard(index){
 const stream=streams[index];
 const card=node('section',undefined,'player-card');
 card.dataset.index=String(index);
 const label=node('div',stream.label,'player-label');
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
  card.classList.remove('primary','secondary-1','secondary-2','secondary-3','viewer-hidden');
  if(preset!=='equal')card.classList.toggle('primary',index===primaryIndex);
 });
 if(preset!=='equal'){
  const secondaryIndexes=playerCards.map((card,index)=>card&&index!==primaryIndex?index:-1).filter(index=>index>=0);
  const visibleCount=Math.min(FOCUS_VISIBLE_SLOTS-1,secondaryIndexes.length);
  const offset=secondaryIndexes.length?secondaryOffset%secondaryIndexes.length:0;
  const visible=new Set(Array.from({length:visibleCount},(_,slot)=>secondaryIndexes[(offset+slot)%secondaryIndexes.length]));
  secondaryIndexes.forEach(index=>playerCards[index]?.classList.toggle('viewer-hidden',!visible.has(index)));
  [...visible].forEach((index,slot)=>playerCards[index]?.classList.add('secondary-'+(slot+1)));
 }
}
function applyLayout(){
 const effective=watchMode==='multi'&&streams.length>1?layout:'equal';
 stage.className='viewer-stage layout-'+effective+' count-'+streams.length;
 workspace.className='viewer-workspace workspace-'+workspaceLayout+' layout-'+effective+' count-'+streams.length;
 const count=streams.length;
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
 primaryIndex=index;
 secondaryOffset=0;
 if(currentLayoutPreset()==='focus')lockedIndex=index;
 setAudioMaster(index);
 applyLayout();
 resolvePrimaryPtt();
}
function handleFocusAvatarClick(index){
 if(index<0||index>=streams.length)return;
 if(currentLayoutPreset()==='focus'&&lockedIndex===index){
  setLayoutPreset('primary');
  return;
 }
 if(currentLayoutPreset()!=='focus'){
  setPrimary(index);
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
 if(state!==YT.PlayerState.PLAYING&&state!==YT.PlayerState.PAUSED)return;
 const expected=syncExpected.get(player);
 if(expected&&Date.now()<expected.until&&expected.state===state){
  syncExpected.delete(player);
  return;
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
function mountPlayers(){streams.forEach((stream,index)=>mountPlayerAt(index,confirmedLiveIds.has(stream.videoId)))}
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
 if(label)label.textContent=streams[0].label;
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
 if(!streams.length)return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:null;
 const row=collabRowFor(streams[primaryIndex]?.videoId);
 const start=collabStartMs(row);
 if(start===null)return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:null;
 let seconds=null;
 try{seconds=players[primaryIndex]?.getCurrentTime?.()}catch{}
 if(!Number.isFinite(seconds))return Number.isFinite(collabAbsoluteMs)?collabAbsoluteMs:start;
 return start+Math.max(0,seconds)*1000;
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
   if(label)label.textContent=stream.label;
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
function pttAtBottom(){return pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48}
function pttToLatest(){pttFeed.scrollTop=pttFeed.scrollHeight;pttNewest.hidden=true;pttFollowing=true}
function resetPttFeed(){
 pttLoaded=false;
 pttFollowing=true;
 pttNewest.hidden=true;
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
function verifiedSameDayVodWindow(row){
 const lifecycle=String(row?.lifecycle_state||row?.state||'').toLowerCase();
 const start=String(row?.actual_start||''),end=String(row?.actual_end||'');
 const startMs=Date.parse(start),endMs=Date.parse(end);
 if(lifecycle!=='ended'||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)return null;
 const today=taipeiDay();
 if(taipeiDayForDate(start)!==today||taipeiDayForDate(new Date(endMs-1))!==today)return null;
 return {start,end,day:today,anchorSource:PTT_ARCHIVE_ANCHOR};
}
async function loadTodayPttPayload(day){
 try{return await api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=1000')}
 catch{return api('/v1/ptt/today?day='+encodeURIComponent(day)+'&limit=300')}
}
async function loadSameDayVodPtt(context,token){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 今日專串';
 pttMeta.textContent=context.day.replaceAll('-','/')+' · 今日暫存 · 讀取中';
 try{
  const data=await loadTodayPttPayload(context.day);
  if(token!==pttResolveToken)return;
  if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes))throw new Error('資料格式錯誤');
  const startMs=Date.parse(context.start),endMs=Date.parse(context.end);
  const rows=data.pushes.filter(row=>{
   if(!row||typeof row.content!=='string')return false;
   const occurred=Date.parse(String(row.occurred_at||''));
   return Number.isFinite(occurred)&&occurred>=startMs&&occurred<endMs;
  });
  const seen=new Set(),deduped=[];
  for(const row of rows){
   const key=pttKey(row);
   if(!key||seen.has(key))continue;
   seen.add(key);deduped.push(row);
  }
  pttFeed.replaceChildren(...deduped.map(pttRow));
  pttLoaded=true;pttFollowing=false;pttNewest.hidden=true;pttFeed.scrollTop=0;
  pttMeta.textContent=context.day.replaceAll('-','/')+' · '+deduped.length+' 則 · 今日暫存 · ⚠ 尚未封存，不宣稱完整';
  if(!deduped.length)pttFeed.replaceChildren(node('div','這段今日 VOD 時間範圍內目前沒有可顯示的 PTT 推文；資料尚未封存。','ptt-empty'));
 }catch(error){
  if(token!==pttResolveToken)return;
  pttMeta.textContent=context.day.replaceAll('-','/')+' · 今日暫存 · 讀取失敗';
  pttFeed.replaceChildren(node('div','今日稍早 VOD 的 PTT 暫時無法讀取：'+String(error?.message||error),'ptt-empty'));
 }
}
let archiveManifestCache=null;
function archiveIntegrityError(message){
 const error=new Error(message);error.archiveIntegrity=true;return error;
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
function archiveHourKey(ms){
 const date=new Date(ms);
 return 'ptt/v1/chunks/'+date.getUTCFullYear()+'/'+String(date.getUTCMonth()+1).padStart(2,'0')+'/'+
  String(date.getUTCDate()).padStart(2,'0')+'/'+String(date.getUTCHours()).padStart(2,'0')+'00.json';
}
function archiveHourKeys(startMs,endMs){
 const keys=[];
 let cursor=Math.floor(startMs/3600000)*3600000;
 while(cursor<endMs){keys.push(archiveHourKey(cursor));cursor+=3600000}
 return keys;
}
async function archiveSha256Hex(buffer){
 if(!globalThis.crypto?.subtle)throw new Error('瀏覽器不支援歷史檔案完整性驗證');
 const digest=await crypto.subtle.digest('SHA-256',buffer);
 return [...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join('');
}
function validateArchiveManifest(manifest){
 if(manifest?.schema_version!==PTT_ARCHIVE_SCHEMA||manifest?.precision!=='minute'||
    manifest?.chunk_minutes!==60||manifest?.timezone!=='UTC'||
    !Array.isArray(manifest?.objects)||!Array.isArray(manifest?.days))throw new Error('歷史 PTT manifest 格式不支援');
 const seen=new Set();
 for(const item of manifest.objects){
  if(!item||typeof item.key!=='string'||!item.key.endsWith('.json')||seen.has(item.key)||
     !/^[0-9a-f]{64}$/.test(String(item.sha256||''))||!Number.isInteger(item.pushes)||item.pushes<0)
    throw new Error('歷史 PTT manifest 物件索引無效');
  seen.add(item.key);
 }
 return manifest;
}
async function fetchArchiveManifest(force=false){
 if(!PTT_ARCHIVE_BASE||!/^https:\/\//.test(PTT_ARCHIVE_BASE))throw new Error('歷史 PTT Static Assets 未設定');
 if(archiveManifestCache&&!force)return archiveManifestCache;
 const response=await fetch(PTT_ARCHIVE_BASE+PTT_ARCHIVE_MANIFEST,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}});
 if(!response.ok)throw new Error('歷史 PTT manifest HTTP '+response.status);
 archiveManifestCache=validateArchiveManifest(await response.json());
 return archiveManifestCache;
}
async function fetchArchiveChunk(item){
 const response=await fetch(PTT_ARCHIVE_BASE+'/'+item.key,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}});
 if(!response.ok)throw new Error('歷史 PTT chunk HTTP '+response.status);
 const contentType=String(response.headers.get('content-type')||'').toLowerCase();
 if(!contentType.startsWith('application/json'))throw archiveIntegrityError('歷史 PTT chunk Content-Type 不符');
 const buffer=await response.arrayBuffer();
 const digest=await archiveSha256Hex(buffer);
 if(digest!==String(item.sha256))throw archiveIntegrityError('歷史 PTT chunk SHA 不符');
 let payload;
 try{payload=JSON.parse(new TextDecoder().decode(buffer))}catch{throw archiveIntegrityError('歷史 PTT chunk JSON 無效')}
 if(payload?.schema_version!==PTT_ARCHIVE_SCHEMA||!Array.isArray(payload?.pushes)||
    payload.pushes.length!==item.pushes)throw archiveIntegrityError('歷史 PTT chunk push count 不符');
 if(String(payload.bucket_start||'')!==String(item.bucket_start||'')||
    String(payload.bucket_end||'')!==String(item.bucket_end||''))throw archiveIntegrityError('歷史 PTT chunk bucket 不符');
 return payload.pushes;
}
function archiveCoverageStatus(manifest,startMs,endMs){
 const priority={COMPLETE:0,UNKNOWN:1,PARTIAL:2,MISSING:3};
 const byDay=new Map(manifest.days.map(item=>[String(item?.day||''),String(item?.coverage_status||'MISSING')]));
 const days=archiveCoverageDays(startMs,endMs);
 let status='COMPLETE';
 for(const day of days){
  const candidate=priority[byDay.get(day)]===undefined?'MISSING':byDay.get(day);
  if(priority[candidate]>priority[status])status=candidate;
 }
 return {status,days};
}
async function resolveArchiveRows(context,manifest){
 const startMs=Date.parse(context.start),endMs=Date.parse(context.end);
 if(context.anchorSource!==PTT_ARCHIVE_ANCHOR||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)
  throw new Error('缺少可信的 YouTube actualStartTime / actualEndTime');
 const objects=new Map(manifest.objects.map(item=>[item.key,item]));
 const rows=[];
 for(const key of archiveHourKeys(startMs,endMs)){
  const item=objects.get(key);
  if(!item)continue;
  const pushes=await fetchArchiveChunk(item);
  for(const row of pushes){
   const occurred=Date.parse(String(row?.occurred_at||''));
   if(Number.isFinite(occurred)&&occurred>=startMs&&occurred<endMs)rows.push(row);
  }
 }
 const seen=new Set(),deduped=[];
 rows.sort((a,b)=>Date.parse(String(a.occurred_at||''))-Date.parse(String(b.occurred_at||''))||
  String(a.aid||'').localeCompare(String(b.aid||''))||
  (Number(a.floor)||0)-(Number(b.floor)||0)||(Number(a.source_line)||0)-(Number(b.source_line)||0));
 for(const row of rows){
  const key=String(row?.source_record_key||'');
  if(!key||seen.has(key))continue;
  seen.add(key);deduped.push(row);
 }
 const coverage=archiveCoverageStatus(manifest,startMs,endMs);
 return {rows:deduped,coverageStatus:coverage.status,coverageDays:coverage.days};
}
async function loadArchivePtt(context,token){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 歷史專串';
 pttMeta.textContent='歷史 Static Assets · 讀取中';
 let result=null;
 try{
  for(let attempt=0;attempt<2;attempt++){
   try{
    const manifest=await fetchArchiveManifest(attempt===1);
    result=await resolveArchiveRows(context,manifest);
    break;
   }catch(error){
    if(attempt===0&&error?.archiveIntegrity){archiveManifestCache=null;continue}
    throw error;
   }
  }
  if(token!==pttResolveToken||!result)return;
  pttFeed.replaceChildren(...result.rows.map(pttRow));
  pttLoaded=true;
  pttFollowing=false;
  pttNewest.hidden=true;
  pttFeed.scrollTop=0;
  const dayLabel=result.coverageDays.length?result.coverageDays.join('～'):(context.day||'').replaceAll('-','/');
  const warning=result.coverageStatus==='COMPLETE'
   ?'完整涵蓋'
   :'⚠ '+result.coverageStatus+' · 資料可能不完整';
  pttMeta.textContent=dayLabel+' · '+result.rows.length+' 則 · VOD · '+warning;
  if(!result.rows.length)pttFeed.replaceChildren(node('div',
   result.coverageStatus==='COMPLETE'?'這段 VOD 時間範圍內沒有 PTT 推文。':'這段 VOD 沒有可顯示推文；歷史涵蓋狀態為 '+result.coverageStatus+'。','ptt-empty'));
 }catch(error){
  if(token!==pttResolveToken)return;
  pttMeta.textContent='歷史 Static Assets · 讀取失敗';
  pttFeed.replaceChildren(node('div','歷史 PTT 暫時無法讀取：'+String(error?.message||error),'ptt-empty'));
 }
}
async function resolvePrimaryPtt(){
 const stream=streams[primaryIndex];
 if(!stream){showPttUnavailable('沒有可判定的影片。');return}
 const token=++pttResolveToken;
 const id=stream.videoId;
 resetPttFeed();
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 專串';
 const archiveWindow=archiveWindows.get(id);
 if(archiveVodEntry){
  if(!archiveWindow){
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable('缺少可信的 YouTube actualStartTime / actualEndTime；不會改用 scheduled time，也不會查 Live Worker / D1。','VOD 歷史 PTT 無法判定');
   return;
  }
  pttContext={mode:'archive',videoId:id,start:archiveWindow.start,end:archiveWindow.end,
              day:taipeiDayForDate(archiveWindow.start),anchorSource:archiveWindow.anchorSource};
  updateUrl();
  await loadArchivePtt(pttContext,token);
  return;
 }
 pttMeta.textContent='判定 Live 中';
 try{
  const row=await api('/v1/catalog/videos/'+encodeURIComponent(id));
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
  const sameDayWindow=verifiedSameDayVodWindow(row);
  if(sameDayWindow){
   pttContext={mode:'same-day',videoId:id,start:sameDayWindow.start,end:sameDayWindow.end,
               day:sameDayWindow.day,anchorSource:sameDayWindow.anchorSource};
   updateUrl();
   await loadSameDayVodPtt(pttContext,token);
   return;
  }
  pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
  updateUrl();
  showPttUnavailable('已結束影片若不是今天稍早的 verified VOD，仍需由 History 傳入 verified actualStartTime / actualEndTime。','VOD 請由歷史頁進入');
 }catch{
  if(token!==pttResolveToken)return;
  const todayRow=catalogRows.find(row=>String(row?.video_id||'')===id);
  const todayState=String(todayRow?.lifecycle_state||todayRow?.state||'').toLowerCase();
  if(requestedPttMode==='live'&&todayState==='live'){
   pttContext={mode:'live',videoId:id,start:'',end:'',day:taipeiDay()};
   updateUrl();
   await loadLivePtt();
  }else{
   const sameDayWindow=verifiedSameDayVodWindow(todayRow);
   if(requestedPttMode==='live'&&sameDayWindow){
    pttContext={mode:'same-day',videoId:id,start:sameDayWindow.start,end:sameDayWindow.end,
                day:sameDayWindow.day,anchorSource:sameDayWindow.anchorSource};
    updateUrl();
    await loadSameDayVodPtt(pttContext,token);
    return;
   }
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable(
    requestedPttMode==='live'
     ?'這支影片沒有被今日 catalog 驗證為 LIVE，也沒有可用的今日 ended actual_start / actual_end，因此不會誤接今天的 PTT。歷史 VOD 請由 History 提供 verified window。'
     :'無法自動判定這支影片；未連接錯誤日期的 PTT。',
    requestedPttMode==='live'?'非今日 LIVE':'無法判定'
   );
  }
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
 pttFollowing=pttAtBottom();
 pttNewest.hidden=pttFollowing;
},{passive:true});
pttFeed.addEventListener('wheel',event=>{if(event.deltaY<0)pttFollowing=false},{passive:true});
pttFeed.addEventListener('dblclick',event=>{
 event.preventDefault();
 window.open('/ptt-today','_blank','noopener,noreferrer');
});
pttNewest.addEventListener('click',pttToLatest);
fullscreenButton.addEventListener('click',async()=>{
 try{
  if(document.fullscreenElement)await document.exitFullscreen();
  else await document.documentElement.requestFullscreen();
 }catch{}
});
window.addEventListener('pagehide',()=>{
 clearInterval(collabPollTimer);clearInterval(collabVodTimer);
});
document.addEventListener('fullscreenchange',()=>{
 const on=Boolean(document.fullscreenElement);
 document.body.classList.toggle('immersive',on);
 fullscreenButton.textContent=on?'退出沉浸模式':'沉浸模式';
});

readSettings();
carousel.checked=currentLayoutPreset()!=='equal';
if(currentLayoutPreset()==='focus')lockedIndex=primaryIndex;
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
setInterval(loadPtt,10000);

if(window.YT?.Player)tryMountPlayers();
else window.onYouTubeIframeAPIReady=tryMountPlayers;
