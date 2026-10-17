'use strict';

const API_BASE=String(window.HOLOVIEWER_CONFIG?.apiBase||'').replace(/\/$/,'');
const params=new URLSearchParams(location.search);
const streams=[...new Set(params.getAll('stream').filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))].slice(0,3).map(id=>({videoId:id,label:id,channelId:''}));
let layout=['equal','primary'].includes(params.get('layout'))?params.get('layout'):(streams.length>1?'equal':'equal');
let primaryIndex=Math.max(0,Math.min(streams.length-1,Number(params.get('primary'))||0));
let audioMaster=Math.max(0,Math.min(streams.length-1,Number(params.get('audio'))||0));
const pttMode=params.get('ptt')||'live';

const stage=document.getElementById('stage');
const liveRail=document.getElementById('viewerLiveRail');
const liveList=document.getElementById('viewerLiveList');
const controls=document.getElementById('viewerControls');
const settingsButton=document.getElementById('viewerSettings');
const fullscreenButton=document.getElementById('viewerFullscreen');
const focusChoices=document.getElementById('focusChoices');
const audioSelect=document.getElementById('audioMaster');
const audioFollow=document.getElementById('audioFollowFocus');
const syncPlayback=document.getElementById('syncPlayback');
const playAll=document.getElementById('playAll');
const pauseAll=document.getElementById('pauseAll');
const carousel=document.getElementById('focusCarousel');
const carouselInterval=document.getElementById('focusCarouselInterval');
const carouselOutput=document.getElementById('focusCarouselIntervalOutput');
const pttPanel=document.getElementById('pttPanel');
const pttFeed=document.getElementById('pttFeed');
const pttMeta=document.getElementById('pttMeta');
const pttNewest=document.getElementById('pttNewest');
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');
const pttShowFloor=document.getElementById('pttShowFloor');

const players=Array(streams.length).fill(null);
const playerCards=[];
let catalogRows=[];
let syncGuard=false;
let carouselTimer=null;
let pttFollowing=true;
let pttLoaded=false;

function api(path){
 if(!API_BASE||!/^https:\/\//.test(API_BASE))return Promise.reject(new Error('正式 API 未設定'));
 return fetch(API_BASE+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}}).then(r=>{
  if(!r.ok)throw new Error('API HTTP '+r.status);
  return r.json();
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
 if(/^#[0-9a-fA-F]{6}$/.test(audited))return audited;
 return '#9ab8c4';
}
function updateUrl(){
 const q=new URLSearchParams();
 streams.forEach(s=>q.append('stream',s.videoId));
 q.set('layout',layout);
 q.set('ptt',pttMode);
 q.set('primary',String(primaryIndex));
 q.set('audio',String(audioMaster));
 history.replaceState(null,'','/viewer/?'+q.toString());
}
function renderShell(){
 if(!streams.length){
  stage.replaceChildren(node('div','沒有可播放的 YouTube 影片。','ptt-empty'));
  controls.hidden=true;
  return;
 }
 stage.replaceChildren();
 playerCards.length=0;
 streams.forEach((stream,index)=>{
  const card=node('section',undefined,'player-card');
  card.dataset.index=String(index);
  const label=node('div',stream.label,'player-label');
  const host=node('div',undefined,'player-host');
  host.id='viewer-player-'+index;
  card.append(label,host);
  stage.append(card);
  playerCards.push(card);
 });
 renderControls();
 applyLayout();
}
function renderControls(){
 focusChoices.replaceChildren();
 audioSelect.replaceChildren();
 streams.forEach((stream,index)=>{
  const b=node('button',String.fromCharCode(65+index));
  b.type='button';b.dataset.focusIndex=String(index);b.title=stream.label;
  b.addEventListener('click',()=>setPrimary(index));
  focusChoices.append(b);
  const option=document.createElement('option');
  option.value=String(index);option.textContent=String.fromCharCode(65+index)+' · '+stream.label;
  audioSelect.append(option);
 });
 audioSelect.value=String(audioMaster);
 const multi=streams.length>1;
 document.getElementById('layoutGroup').hidden=!multi;
 document.getElementById('focusGroup').hidden=!multi;
 audioFollow.parentElement.hidden=!multi;
 syncPlayback.parentElement.hidden=!multi;
 playAll.hidden=!multi;pauseAll.hidden=!multi;
 carousel.parentElement.hidden=!multi;
 carouselInterval.parentElement.hidden=!multi;
 refreshControlState();
}
function refreshControlState(){
 document.querySelectorAll('[data-layout]').forEach(b=>b.classList.toggle('active',b.dataset.layout===layout));
 [...focusChoices.children].forEach((b,i)=>b.classList.toggle('active',i===primaryIndex));
 audioSelect.value=String(audioMaster);
 playerCards.forEach((card,index)=>{
  card.classList.toggle('primary',index===primaryIndex);
  card.classList.remove('secondary-1','secondary-2');
 });
 const secondary=playerCards.filter((_,index)=>index!==primaryIndex);
 secondary[0]?.classList.add('secondary-1');
 secondary[1]?.classList.add('secondary-2');
}
function applyLayout(){
 const effective=streams.length===1?'equal':layout;
 stage.className='viewer-stage layout-'+effective;
 const cols=streams.length<=1?1:2;
 const rows=Math.max(1,Math.ceil(streams.length/cols));
 stage.style.setProperty('--viewer-cols',String(cols));
 stage.style.setProperty('--viewer-rows',String(rows));
 if(effective==='primary'){
  const ordered=[playerCards[primaryIndex],...playerCards.filter((_,i)=>i!==primaryIndex)];
  ordered.forEach(card=>stage.append(card));
 }else{
  playerCards.sort((a,b)=>Number(a.dataset.index)-Number(b.dataset.index)).forEach(card=>stage.append(card));
 }
 refreshControlState();
 updateUrl();
}
function setPrimary(index){
 if(index<0||index>=streams.length)return;
 primaryIndex=index;
 if(audioFollow.checked)setAudioMaster(index);
 applyLayout();
}
function setAudioMaster(index){
 if(index<0||index>=streams.length)return;
 audioMaster=index;
 audioSelect.value=String(index);
 players.forEach((player,i)=>{
  if(!player)return;
  try{if(i===audioMaster)player.unMute();else player.mute();}catch{}
 });
 updateUrl();
}
function syncPlayers(state,sourceIndex){
 if(!syncPlayback.checked||syncGuard||streams.length<2)return;
 syncGuard=true;
 players.forEach((player,index)=>{
  if(!player||index===sourceIndex)return;
  try{
   if(state===YT.PlayerState.PLAYING)player.playVideo();
   else if(state===YT.PlayerState.PAUSED)player.pauseVideo();
  }catch{}
 });
 setTimeout(()=>{syncGuard=false},350);
}
function mountPlayers(){
 if(!window.YT?.Player)return;
 streams.forEach((stream,index)=>{
  if(players[index])return;
  players[index]=new YT.Player('viewer-player-'+index,{
   videoId:stream.videoId,
   playerVars:{playsinline:1,rel:0,enablejsapi:1,origin:location.origin},
   events:{
    onReady:()=>{setAudioMaster(audioMaster)},
    onStateChange:event=>{
     if(event.data===YT.PlayerState.PLAYING||event.data===YT.PlayerState.PAUSED)syncPlayers(event.data,index);
    }
   }
  });
 });
}
function replacePrimaryStream(row){
 const id=String(row?.video_id||'');
 if(!/^[A-Za-z0-9_-]{11}$/.test(id)||!streams.length)return;
 const existing=streams.findIndex(s=>s.videoId===id);
 if(existing>=0){setPrimary(existing);return}
 const index=primaryIndex;
 streams[index]={videoId:id,label:catalogName(row),channelId:String(row?.channel_id||'')};
 const player=players[index];
 if(player?.loadVideoById)player.loadVideoById(id);
 const label=playerCards[index]?.querySelector('.player-label');
 if(label)label.textContent=streams[index].label;
 renderControls();
 applyLayout();
 renderLiveRail(catalogRows);
}
function supportStyle(button,row){
 const accent=accentFor(row);
 button.style.setProperty('--member-accent',accent);
 const dual=Array.isArray(row?.member_accent_dual)?row.member_accent_dual:[];
 if(String(row?.support_mode||'')==='dual_color'&&dual.length===2&&dual.every(x=>/^#[0-9a-fA-F]{6}$/.test(String(x)))){
  button.dataset.supportMode='dual_color';
  button.style.setProperty('--member-accent-dual','linear-gradient(135deg,'+dual[0]+' 0 50%,'+dual[1]+' 50% 100%)');
 }
}
function renderLiveRail(rows){
 const live=rows.filter(row=>String(row?.lifecycle_state||row?.state||'').toLowerCase()==='live'&&/^[A-Za-z0-9_-]{11}$/.test(String(row?.video_id||'')));
 liveList.replaceChildren();
 live.forEach(row=>{
  const button=node('button',undefined,'viewer-live-item');
  button.type='button';button.dataset.videoId=String(row.video_id);
  button.title=catalogName(row);supportStyle(button,row);
  button.classList.toggle('is-active',streams.some(s=>s.videoId===row.video_id));
  const avatar=node('span',undefined,'viewer-live-avatar');
  const url=safeAvatar(row.avatar_url);
  if(url){const img=document.createElement('img');img.src=url;img.alt='';img.loading='lazy';avatar.append(img)}
  else avatar.append(node('span',[...catalogName(row)][0]||'H'));
  avatar.append(node('i'));
  button.append(avatar,node('strong',catalogName(row)));
  button.addEventListener('click',()=>replacePrimaryStream(row));
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
 const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
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
 const floor=node('span',Number.isInteger(row?.floor)&&row.floor>0?row.floor+'樓':'','ptt-floor');
 const body=node('span',undefined,'ptt-body');
 body.append(node('span',String(row?.author||'unknown')+':','ptt-author'),node('span',String(row?.content||''),'ptt-content'));
 el.append(kindEl,time,floor,body);
 el.classList.toggle('hide-floor',!pttShowFloor.checked);
 if(row?.source_url)el.addEventListener('dblclick',()=>window.open(String(row.source_url),'_blank','noopener,noreferrer'));
 return el;
}
function pttAtBottom(){return pttFeed.scrollHeight-pttFeed.scrollTop-pttFeed.clientHeight<48}
function pttToLatest(){pttFeed.scrollTop=pttFeed.scrollHeight;pttNewest.hidden=true;pttFollowing=true}
async function loadPtt(){
 if(pttMode!=='live'){
  pttPanel.hidden=false;
  pttFeed.replaceChildren(node('div','這個觀看組合目前沒有即時 PTT 專串。','ptt-empty'));
  pttMeta.textContent='無即時資料';
  return;
 }
 pttPanel.hidden=false;
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
   rows.forEach(row=>{const key=pttKey(row);if(!seen.has(key)){pttFeed.append(pttRow(row));seen.add(key)}});
   while(pttFeed.children.length>300)pttFeed.firstElementChild?.remove();
  }
  const freshness=String(data.freshness?.status||'unknown');
  pttMeta.textContent=day.replaceAll('-','/')+' · '+pttFeed.children.length+' 則 · '+(freshness==='fresh'?'即時':freshness==='stale'?'資料稍舊':'狀態未知');
  if(beforeAtBottom)requestAnimationFrame(pttToLatest);
 }catch(e){
  pttMeta.textContent=day.replaceAll('-','/')+' · 讀取失敗';
  if(!pttLoaded)pttFeed.replaceChildren(node('div','PTT 暫時無法讀取，稍後會自動重試。','ptt-empty'));
 }
}
function startCarousel(){
 clearInterval(carouselTimer);carouselTimer=null;
 if(!carousel.checked||streams.length<2)return;
 const ms=Math.max(5,Math.min(30,Number(carouselInterval.value)||10))*1000;
 carouselTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length),ms);
}
function readSettings(){
 try{
  const font=Math.max(12,Math.min(26,Number(localStorage.getItem('holoviewer-viewer-ptt-font'))||14));
  pttFontSize.value=String(font);pttFontValue.textContent=font+'px';
  document.documentElement.style.setProperty('--ptt-font-size',font+'px');
  pttShowFloor.checked=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';
 }catch{}
}
function applyFloor(){
 pttFeed.querySelectorAll('.ptt-row').forEach(row=>row.classList.toggle('hide-floor',!pttShowFloor.checked));
 try{localStorage.setItem('holoviewer-ptt-show-floor',String(pttShowFloor.checked))}catch{}
}

settingsButton.addEventListener('click',()=>{
 const open=document.body.classList.toggle('settings-open');
 controls.hidden=!open;settingsButton.setAttribute('aria-expanded',String(open));
});
document.querySelectorAll('[data-layout]').forEach(button=>button.addEventListener('click',()=>{
 layout=button.dataset.layout;applyLayout();
}));
audioSelect.addEventListener('change',()=>setAudioMaster(Number(audioSelect.value)));
audioFollow.addEventListener('change',()=>{if(audioFollow.checked)setAudioMaster(primaryIndex)});
playAll.addEventListener('click',()=>players.forEach(player=>{try{player?.playVideo()}catch{}}));
pauseAll.addEventListener('click',()=>players.forEach(player=>{try{player?.pauseVideo()}catch{}}));
carousel.addEventListener('change',startCarousel);
carouselInterval.addEventListener('input',()=>{carouselOutput.textContent=carouselInterval.value+'s';startCarousel()});
pttFontSize.addEventListener('input',()=>{
 const size=Math.max(12,Math.min(26,Number(pttFontSize.value)||14));
 pttFontValue.textContent=size+'px';document.documentElement.style.setProperty('--ptt-font-size',size+'px');
 try{localStorage.setItem('holoviewer-viewer-ptt-font',String(size))}catch{}
});
pttShowFloor.addEventListener('change',applyFloor);
pttFeed.addEventListener('scroll',()=>{
 pttFollowing=pttAtBottom();pttNewest.hidden=pttFollowing;
},{passive:true});
pttFeed.addEventListener('wheel',event=>{if(event.deltaY<0)pttFollowing=false},{passive:true});
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
loadCatalog();
loadPtt();
setInterval(loadPtt,10000);

if(window.YT?.Player)mountPlayers();
else window.onYouTubeIframeAPIReady=mountPlayers;
