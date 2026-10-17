'use strict';

const API_BASE=String(window.HOLOVIEWER_CONFIG?.apiBase||'').replace(/\/$/,'');
const params=new URLSearchParams(location.search);
const streams=[...new Set(params.getAll('stream').filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))].slice(0,4).map(id=>({videoId:id,label:id,channelId:''}));
let layout=['equal','primary'].includes(params.get('layout'))?params.get('layout'):'equal';
let workspaceLayout=['sidebar','focus'].includes(params.get('workspace'))?params.get('workspace'):'sidebar';
let primaryIndex=Math.max(0,Math.min(Math.max(0,streams.length-1),Number(params.get('primary'))||0));
let audioMaster=primaryIndex;
let watchMode=params.get('mode')==='multi'||streams.length>1?'multi':'single';
const requestedPttMode=params.get('ptt')||'live';

const stage=document.getElementById('stage');
const workspace=document.querySelector('.viewer-workspace');
const liveRail=document.getElementById('viewerLiveRail');
const liveList=document.getElementById('viewerLiveList');
const controls=document.getElementById('viewerControls');
const settingsButton=document.getElementById('viewerSettings');
const fullscreenButton=document.getElementById('viewerFullscreen');
const multiModeSwitch=document.getElementById('multiModeSwitch');
const focusChoices=document.getElementById('focusChoices');
const syncPlayback=document.getElementById('syncPlayback');
const playAll=document.getElementById('playAll');
const pauseAll=document.getElementById('pauseAll');
const carousel=document.getElementById('focusCarousel');
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
let pttFollowing=true;
let pttLoaded=false;
let pttContext={mode:'unresolved',videoId:'',start:'',end:'',day:''};
let pttResolveToken=0;
let confirmedLiveIds=new Set();
let draggedLiveId='';

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
function accentFor(row){
 const audited=String(row?.member_accent||'');
 return /^#[0-9a-fA-F]{6}$/.test(audited)?audited:'#9ab8c4';
}
function applyModeClass(){
 document.body.classList.toggle('mode-single',watchMode==='single');
 document.body.classList.toggle('mode-multi',watchMode==='multi');
 if(watchMode==='single'){
  document.body.classList.remove('settings-open');
  controls.hidden=true;
  settingsButton.setAttribute('aria-expanded','false');
 }
}
function updateUrl(){
 const q=new URLSearchParams();
 streams.forEach(stream=>q.append('stream',stream.videoId));
 q.set('layout',layout);
 q.set('workspace',workspaceLayout);
 q.set('ptt',pttContext.mode==='live'?'live':requestedPttMode);
 q.set('primary',String(primaryIndex));
 q.set('audio',String(primaryIndex));
 q.set('mode',watchMode);
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
  const button=node('button',String.fromCharCode(65+index));
  button.type='button';
  button.dataset.focusIndex=String(index);
  button.title=stream.label;
  button.addEventListener('click',()=>setPrimary(index));
  focusChoices.append(button);
 });
 const multi=watchMode==='multi'&&streams.length>1;
 playerCards.forEach(card=>{const remove=card?.querySelector('.player-remove');if(remove)remove.hidden=!multi});
 document.getElementById('layoutGroup').hidden=!multi;
 document.getElementById('workspaceGroup').hidden=!multi;
 document.getElementById('focusGroup').hidden=!multi;
 syncPlayback.parentElement.hidden=!multi;
 playAll.hidden=!multi;
 pauseAll.hidden=!multi;
 carousel.parentElement.hidden=!multi;
 carouselInterval.parentElement.hidden=!multi;
 multiModeSwitch.checked=watchMode==='multi';
 applyModeClass();
 refreshControlState();
}
function refreshControlState(){
 document.querySelectorAll('[data-layout]').forEach(button=>button.classList.toggle('active',button.dataset.layout===layout));
 document.querySelectorAll('[data-workspace]').forEach(button=>button.classList.toggle('active',button.dataset.workspace===workspaceLayout));
 [...focusChoices.children].forEach((button,index)=>button.classList.toggle('active',index===primaryIndex));
 playerCards.forEach((card,index)=>{
  if(!card)return;
  card.classList.toggle('primary',index===primaryIndex);
  card.classList.remove('secondary-1','secondary-2','secondary-3');
 });
 const secondary=playerCards.filter((card,index)=>card&&index!==primaryIndex);
 secondary[0]?.classList.add('secondary-1');
 secondary[1]?.classList.add('secondary-2');
 secondary[2]?.classList.add('secondary-3');
}
function applyLayout(){
 const effective=watchMode==='multi'&&streams.length>1?layout:'equal';
 stage.className='viewer-stage layout-'+effective+' count-'+streams.length;
 workspace.className='viewer-workspace workspace-'+workspaceLayout+' layout-'+effective+' count-'+streams.length;
 const cols=streams.length<=1?1:2;
 const rows=Math.max(1,Math.ceil(streams.length/cols));
 stage.style.setProperty('--viewer-cols',String(cols));
 stage.style.setProperty('--viewer-rows',String(rows));
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
 setAudioMaster(index);
 applyLayout();
 resolvePrimaryPtt();
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
function mountPlayerAt(index,autoplay=false){
 if(!window.YT?.Player||players[index]||!streams[index])return;
 const host=document.getElementById(playerHostId(streams[index]));
 if(!host)return;
 players[index]=new YT.Player(host,{
  videoId:streams[index].videoId,
  playerVars:{playsinline:1,rel:0,enablejsapi:1,origin:location.origin},
  events:{
   onReady:event=>{
    if(autoplay){
     try{event.target.mute()}catch{}
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
function appendMultiStream(row){
 const id=String(row?.video_id||'');
 if(!/^[A-Za-z0-9_-]{11}$/.test(id))return;
 const existing=streams.findIndex(stream=>stream.videoId===id);
 if(existing>=0){setPrimary(existing);return}
 if(streams.length>=4)return;
 const index=streams.length;
 streams.push({videoId:id,label:catalogName(row),channelId:String(row?.channel_id||'')});
 const card=createPlayerCard(index);
 stage.append(card);
 players[index]=null;
 renderControls();
 applyLayout();
 let shouldPlay=false;
 try{shouldPlay=players[primaryIndex]?.getPlayerState()===YT.PlayerState.PLAYING}catch{}
 if(window.YT?.Player)mountPlayerAt(index,shouldPlay);
 renderLiveRail(catalogRows);
}
function removeMultiStream(index){
 if(watchMode!=='multi'||streams.length<=1||index<0||index>=streams.length)return;
 const removedWasPrimary=index===primaryIndex;
 const removedPlayer=players[index];
 const removedCard=playerCards[index];

 // Detach first. Any late PAUSED event from destroy() then has no source index
 // and cannot propagate to the surviving players.
 streams.splice(index,1);
 players.splice(index,1);
 playerCards.splice(index,1);
 removedCard?.remove();
 try{removedPlayer?.destroy()}catch{}

 if(index<primaryIndex)primaryIndex-=1;
 else if(removedWasPrimary)primaryIndex=Math.min(index,streams.length-1);
 audioMaster=primaryIndex;

 playerCards.forEach((card,i)=>{if(card)card.dataset.index=String(i)});
 renderControls();
 applyLayout();
 setAudioMaster(primaryIndex);
 renderLiveRail(catalogRows);
 if(removedWasPrimary)resolvePrimaryPtt();
}
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
 const live=rows.filter(row=>{
  const id=String(row?.video_id||'');
  if(String(row?.lifecycle_state||row?.state||'').toLowerCase()!=='live'||!/^[A-Za-z0-9_-]{11}$/.test(id))return false;
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
function pttKey(row){return String(row?.push_id||row?.aid+':'+row?.source_line)}
function pttRow(row){
 const el=node('div',undefined,'ptt-row');
 el.dataset.pushId=pttKey(row);
 const kind=String(row?.kind||'→');
 const kindEl=node('span',kind,'ptt-kind'+(kind==='噓'?' boo':kind==='→'?' arrow':''));
 const when=new Date(String(row?.occurred_at||''));
 let clock='';
 if(Number.isFinite(when.getTime()))clock=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(when);
 const time=node('span',clock,'ptt-time');
 const body=node('span',undefined,'ptt-body');
 body.append(node('span',String(row?.author||'unknown')+':','ptt-author'),node('span',String(row?.content||''),'ptt-content'));
 el.append(kindEl,time,body);
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
async function loadArchivePtt(context,token){
 pttPanel.hidden=false;
 pttTitle.textContent='PTT 歷史專串';
 pttMeta.textContent=(context.day||'')+' · 讀取中';
 const startMs=Date.parse(context.start||'');
 const endMs=Date.parse(context.end||'');
 const rows=[];
 let after='',pages=0;
 try{
  while(pages++<50){
   const path='/v1/ptt/history?day='+encodeURIComponent(context.day)+'&limit=200'+(after?'&after='+encodeURIComponent(after):'');
   const data=await api(path);
   if(token!==pttResolveToken)return;
   if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes))throw new Error('資料格式錯誤');
   let beyond=false;
   for(const row of data.pushes){
    const when=Date.parse(String(row?.occurred_at||''));
    if(!Number.isFinite(when))continue;
    if((!Number.isFinite(startMs)||when>=startMs)&&(!Number.isFinite(endMs)||when<=endMs))rows.push(row);
    if(Number.isFinite(endMs)&&when>endMs)beyond=true;
   }
   const next=String(data.page?.next_checkpoint||'');
   if(beyond||data.page?.has_more!==true||!next||next===after)break;
   after=next;
  }
  if(token!==pttResolveToken)return;
  pttFeed.replaceChildren(...rows.map(pttRow));
  pttLoaded=true;
  pttFollowing=false;
  pttNewest.hidden=true;
  pttFeed.scrollTop=0;
  pttMeta.textContent=context.day.replaceAll('-','/')+' · '+rows.length+' 則 · VOD';
  if(!rows.length)pttFeed.replaceChildren(node('div','這段 VOD 時間範圍內沒有找到 PTT 推文。','ptt-empty'));
 }catch{
  if(token!==pttResolveToken)return;
  pttMeta.textContent=(context.day||'')+' · 讀取失敗';
  pttFeed.replaceChildren(node('div','歷史 PTT 暫時無法讀取。','ptt-empty'));
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
 pttMeta.textContent='判定 Live / VOD 中';
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
  if(lifecycle==='ended'){
   const startValue=String(row?.actual_start||row?.scheduled_start||row?.start_at||'');
   const endValue=String(row?.actual_end||row?.end_at||'');
   const day=taipeiDayForDate(startValue);
   if(day){
    pttContext={mode:'archive',videoId:id,start:startValue,end:endValue,day};
    updateUrl();
    await loadArchivePtt(pttContext,token);
    return;
   }
  }
  if(['upcoming','waiting'].includes(lifecycle)){
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable('這支影片尚未開始，沒有可連接的 PTT 時間軸。','尚未開始');
   return;
  }
  throw new Error('無法由 catalog 判定');
 }catch{
  if(token!==pttResolveToken)return;
  if(requestedPttMode==='live'){
   pttContext={mode:'live',videoId:id,start:'',end:'',day:taipeiDay()};
   updateUrl();
   await loadLivePtt();
  }else{
   pttContext={mode:'unavailable',videoId:id,start:'',end:'',day:''};
   updateUrl();
   showPttUnavailable('無法自動判定這支影片是 Live 或 VOD；未自動連接錯誤日期的 PTT。','無法判定');
  }
 }
}
async function loadPtt(){
 if(pttContext.mode==='live')await loadLivePtt();
}

function startCarousel(){
 clearInterval(carouselTimer);
 carouselTimer=null;
 if(!carousel.checked||watchMode!=='multi'||streams.length<2)return;
 const ms=Math.max(5,Math.min(30,Number(carouselInterval.value)||10))*1000;
 carouselTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length),ms);
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
 const open=document.body.classList.toggle('settings-open');
 controls.hidden=!open;
 settingsButton.setAttribute('aria-expanded',String(open));
});
multiModeSwitch.addEventListener('change',()=>switchWatchMode(multiModeSwitch.checked?'multi':'single'));
syncPlayback.addEventListener('change',()=>{
 if(!syncPlayback.checked||watchMode!=='multi'||streams.length<2)return;
 let state=null;
 try{state=players[primaryIndex]?.getPlayerState()}catch{}
 if(state===YT.PlayerState.PLAYING||state===YT.PlayerState.PAUSED)syncPlayers(state,primaryIndex);
});
document.querySelectorAll('[data-layout]').forEach(button=>button.addEventListener('click',()=>{
 layout=button.dataset.layout;
 applyLayout();
}));
document.querySelectorAll('[data-workspace]').forEach(button=>button.addEventListener('click',()=>{
 workspaceLayout=button.dataset.workspace;
 applyLayout();
}));
playAll.addEventListener('click',()=>players.forEach(player=>{try{player?.playVideo()}catch{}}));
pauseAll.addEventListener('click',()=>players.forEach(player=>{try{player?.pauseVideo()}catch{}}));
carousel.addEventListener('change',startCarousel);
carouselInterval.addEventListener('input',()=>{
 carouselOutput.textContent=carouselInterval.value+'s';
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
document.addEventListener('fullscreenchange',()=>{
 const on=Boolean(document.fullscreenElement);
 document.body.classList.toggle('immersive',on);
 fullscreenButton.textContent=on?'退出沉浸模式':'沉浸模式';
});

readSettings();
renderShell();
applyModeClass();

let viewerReadyForPlayers=false;
function tryMountPlayers(){
 if(!viewerReadyForPlayers||!window.YT?.Player)return;
 mountPlayers();
}
(async()=>{
 await loadCatalog();
 viewerReadyForPlayers=true;
 tryMountPlayers();
 resolvePrimaryPtt();
})();
setInterval(loadPtt,10000);

if(window.YT?.Player)tryMountPlayers();
else window.onYouTubeIframeAPIReady=tryMountPlayers;
