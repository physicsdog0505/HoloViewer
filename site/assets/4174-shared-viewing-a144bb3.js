/* Direct browser transplant from Hololive-PTT-Viewer shared_viewing_core.py
 * source: a144bb378a8bdd772faa867d608c1e7491253883
 * Only Python server-side value injection is adapted to the config argument.
 */
window.mount4174SharedViewer = function mount4174SharedViewer(config){
const streams=config.streams;
const singlePttKind=(config.singlePttKind||"");
function syncSessionCardinalityClasses(){
 const single=streams.length===1;
 document.body.classList.toggle('single-ptt',single&&Boolean(singlePttKind));
 document.body.classList.toggle('single-live',single&&singlePttKind==='live');
 document.body.classList.toggle('single-vod',single&&singlePttKind==='vod');
}
syncSessionCardinalityClasses();
const translationTracks={A:(config.translationA||[]),B:(config.translationB||[])};
let activeTranslationTrack=translationTracks.A.length?'A':(translationTracks.B.length?'B':'');
const translationSlot=document.getElementById('translationSlot');
const translationText=document.getElementById('translationText');
const translationA=document.getElementById('translationA');
const translationB=document.getElementById('translationB');
const translationStatus=document.getElementById('translationStatus');
function setTranslationTrack(name){
 if(!translationTracks[name]?.length)return;
 activeTranslationTrack=name;
 translationA?.classList.toggle('active',name==='A');
 translationB?.classList.toggle('active',name==='B');
}
if(translationSlot&&(translationTracks.A.length||translationTracks.B.length)){
 translationSlot.hidden=false;
 if(translationA)translationA.hidden=!translationTracks.A.length;
 if(translationB)translationB.hidden=!translationTracks.B.length;
 translationA?.addEventListener('click',()=>setTranslationTrack('A'));
 translationB?.addEventListener('click',()=>setTranslationTrack('B'));
 setTranslationTrack(activeTranslationTrack);
}
function refreshTranslationText(){
 if(!translationText||!activeTranslationTrack||players.length!==1)return;
 const player=players[0];
 if(!player||typeof player.getCurrentTime!=='function')return;
 const now=Number(player.getCurrentTime());
 const cue=translationTracks[activeTranslationTrack].find(row=>now>=Number(row.start)&&now<Number(row.end));
 translationText.textContent=cue?.translated||'';
}
setInterval(refreshTranslationText,250);
let watchMode=streams.length>1?"multi":"single";
// No product-imposed stream cap: stop adding only for duplicates or browser/API failures.
const liveRailItems=Array.from(document.querySelectorAll('.live-channel-rail-item[data-live-video-id]'));
streams.forEach(stream=>{
 const match=liveRailItems.find(item=>item.dataset.liveVideoId===stream.videoId);
 stream.channelId=match?.dataset.channelId||'';
});
function refreshRailVisibility(){
 const selectedIds=new Set(streams.map(stream=>stream.videoId));
 const selectedChannels=new Set(streams.map(stream=>stream.channelId).filter(Boolean));
 liveRailItems.forEach(item=>{
  item.hidden=watchMode==='multi'&&(selectedIds.has(item.dataset.liveVideoId)||(item.dataset.channelId&&selectedChannels.has(item.dataset.channelId)));
 });
}
const verifiedTimelineStarts=(config.verifiedTimelineStarts||{});
const manualTimelineStarts=(config.manualTimelineStarts||{});
const manualTimelineAlign=document.getElementById('manualTimelineAlign');
const manualTimelineLabel=document.getElementById('manualTimelineLabel');
let manualTimelineEnabled=false;
function timelineValue(map,index){
 const value=Number(map[streams[index]?.videoId]);
 return Number.isFinite(value)?value:NaN;
}
function verifiedTimelineComplete(){
 return streams.length>1&&streams.every((_,index)=>Number.isFinite(timelineValue(verifiedTimelineStarts,index)));
}
function manualTimelineEligible(){
 return streams.length>1&&streams.every((_,index)=>Number.isFinite(timelineValue(manualTimelineStarts,index)));
}
function timelineStartFor(index){
 const verified=timelineValue(verifiedTimelineStarts,index);
 if(Number.isFinite(verified))return verified;
 if(manualTimelineEnabled){
  const manual=timelineValue(manualTimelineStarts,index);
  if(Number.isFinite(manual))return manual;
 }
 return NaN;
}
function recomputeVerifiedTimeline(){
 const verifiedComplete=verifiedTimelineComplete();
 const manualEligible=manualTimelineEligible();
 if(manualTimelineLabel)manualTimelineLabel.hidden=verifiedComplete||!manualEligible;
 if(manualTimelineAlign&&(verifiedComplete||!manualEligible)){
  manualTimelineAlign.checked=false;
  manualTimelineEnabled=false;
 }
 manualTimelineEnabled=Boolean(!verifiedComplete&&manualEligible&&manualTimelineAlign?.checked);
 hasVerifiedTimeline=verifiedComplete||manualTimelineEnabled;
 return hasVerifiedTimeline;
}
let hasVerifiedTimeline=false;
recomputeVerifiedTimeline();
const immerse=document.getElementById('customImmerse');
const watchSettings=document.getElementById('watchSettings');
const watchImmersive=document.getElementById('watchImmersive');
watchSettings?.addEventListener('click',()=>{
 const open=document.body.classList.toggle('settings-open');
 watchSettings.setAttribute('aria-expanded',String(open));
});
watchImmersive?.addEventListener('click',()=>immerse?.click());
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');
const pttEmbedShowFloor=document.getElementById('pttEmbedShowFloor');
const hasPtt=Boolean(document.querySelector('.ptt-live-panel'));
function pttFrame(){return document.querySelector('.ptt-live-panel iframe');}
function setPttFontSize(value){const size=Math.max(12,Math.min(26,Number(value)||14));document.documentElement.style.setProperty('--ptt-font-size',size+'px');if(pttFontSize)pttFontSize.value=String(size);if(pttFontValue)pttFontValue.textContent=size+'px';const frame=pttFrame();if(frame?.contentWindow)frame.contentWindow.postMessage({type:'holoviewer:ptt-font-size',size},location.origin);}
function setEmbeddedPttFloor(show){if(pttEmbedShowFloor)pttEmbedShowFloor.checked=Boolean(show);try{localStorage.setItem('holoviewer-ptt-show-floor',String(Boolean(show)));}catch(_e){}const frame=pttFrame();if(frame?.contentWindow)frame.contentWindow.postMessage({type:'holoviewer:ptt-show-floor',show:Boolean(show)},location.origin);}
if(pttFontSize){setPttFontSize(pttFontSize.value);pttFontSize.addEventListener('input',()=>setPttFontSize(pttFontSize.value));}
if(pttEmbedShowFloor){let show=true;try{show=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';}catch(_e){}pttEmbedShowFloor.checked=show;pttEmbedShowFloor.addEventListener('change',()=>setEmbeddedPttFloor(pttEmbedShowFloor.checked));}
const pttEmbeddedFrame=pttFrame();pttEmbeddedFrame?.addEventListener('load',()=>{if(pttFontSize)setPttFontSize(pttFontSize.value);if(pttEmbedShowFloor)setEmbeddedPttFloor(pttEmbedShowFloor.checked);});
let immersiveEnabled=false;
function repinWorkerPttAfterLayout(){
 const feed=document.getElementById('ptt-worker-feed');
 const follow=document.getElementById('ptt-worker-follow');
 if(!feed||!follow?.checked)return;
 requestAnimationFrame(()=>requestAnimationFrame(()=>{feed.scrollTop=feed.scrollHeight;}));
 setTimeout(()=>{feed.scrollTop=feed.scrollHeight;},250);
}
function forceSingleImmersiveGeometry(active){
 if(!contentGrid||!pttPanel)return;
 const rail=document.querySelector('.live-channel-rail');
 const stageNode=document.getElementById('stage');
 const card=stageNode?.querySelector('.player-card');
 const wrap=card?.querySelector('.video-wrap');
 const controls=card?.querySelector('.player-controls');
 const playerNode=wrap?.querySelector('.player');
 const iframe=wrap?.querySelector('iframe');
 const nodes=[contentGrid,document.querySelector('.custom-player-column'),stageNode,card,wrap,playerNode,iframe,pttPanel,controls,rail].filter(Boolean);
 if(!active||streams.length!==1){
  nodes.forEach(node=>{
   const saved=node.dataset.immersiveStyle;
   if(saved!==undefined){node.setAttribute('style',saved);delete node.dataset.immersiveStyle;}
  });
  return;
 }
 nodes.forEach(node=>{if(node.dataset.immersiveStyle===undefined)node.dataset.immersiveStyle=node.getAttribute('style')||'';});
 if(rail)rail.style.setProperty('display','none','important');
 Object.assign(contentGrid.style,{position:'fixed',inset:'0',width:'100vw',height:'100dvh',margin:'0',padding:'0',overflow:'hidden',background:'#000',zIndex:'2147483000'});
 contentGrid.style.setProperty('display','grid','important');
 contentGrid.style.setProperty('grid-template-columns','minmax(0,1fr) clamp(320px,24vw,420px)','important');
 contentGrid.style.setProperty('grid-template-rows','100dvh','important');
 const playerColumn=document.querySelector('.custom-player-column');
 if(playerColumn)Object.assign(playerColumn.style,{position:'relative',width:'100%',height:'100dvh',margin:'0',padding:'0',overflow:'hidden',background:'#000'});
 [stageNode,card,wrap,playerNode,iframe].filter(Boolean).forEach(node=>{
  Object.assign(node.style,{position:'absolute',inset:'0',display:'block',width:'100%',height:'100dvh',minWidth:'0',minHeight:'100dvh',maxWidth:'none',maxHeight:'none',margin:'0',padding:'0',border:'0'});
  node.style.setProperty('aspect-ratio','auto','important');
 });
 if(controls)controls.style.setProperty('display','none','important');
 Object.assign(pttPanel.style,{position:'relative',inset:'auto',display:'flex',width:'100%',height:'100dvh',minWidth:'0',minHeight:'0',maxWidth:'none',maxHeight:'none',margin:'0',padding:'0',overflow:'hidden'});
 pttPanel.style.setProperty('grid-column','2','important');
 pttPanel.style.setProperty('grid-row','1','important');
}
function forceMultiImmersiveGeometry(active){
 if(!contentGrid||!pttPanel||streams.length<2)return;
 const playerColumn=document.querySelector('.custom-player-column');
 const stageNode=document.getElementById('stage');
 const cards=Array.from(stageNode?.querySelectorAll('.player-card')||[]);
 const wraps=cards.map(card=>card.querySelector('.video-wrap')).filter(Boolean);
 const playersNodes=wraps.flatMap(wrap=>Array.from(wrap.querySelectorAll('.player,iframe')));
 const controls=cards.map(card=>card.querySelector('.player-controls')).filter(Boolean);
 const nodes=[contentGrid,playerColumn,stageNode,pttPanel,...cards,...wraps,...playersNodes,...controls].filter(Boolean);
 if(!active){
  nodes.forEach(node=>{
   const saved=node.dataset.multiImmersiveStyle;
   if(saved!==undefined){node.setAttribute('style',saved);delete node.dataset.multiImmersiveStyle;}
  });
  return;
 }
 nodes.forEach(node=>{if(node.dataset.multiImmersiveStyle===undefined)node.dataset.multiImmersiveStyle=node.getAttribute('style')||'';});
 contentGrid.style.setProperty('position','fixed','important');
 contentGrid.style.setProperty('inset','0','important');
 contentGrid.style.setProperty('display','block','important');
 contentGrid.style.setProperty('width','100vw','important');
 contentGrid.style.setProperty('height','100dvh','important');
 contentGrid.style.setProperty('margin','0','important');
 contentGrid.style.setProperty('padding','0','important');
 contentGrid.style.setProperty('overflow','hidden','important');
 contentGrid.style.setProperty('background','#000','important');
 contentGrid.style.setProperty('z-index','2147483000','important');
 if(playerColumn){
  playerColumn.style.setProperty('position','absolute','important');
  playerColumn.style.setProperty('inset','0','important');
  playerColumn.style.setProperty('display','block','important');
  playerColumn.style.setProperty('width','100%','important');
  playerColumn.style.setProperty('height','100%','important');
  playerColumn.style.setProperty('overflow','hidden','important');
 }
 if(stageNode){
  stageNode.style.setProperty('position','absolute','important');
  stageNode.style.setProperty('inset','0','important');
  stageNode.style.setProperty('display','grid','important');
  stageNode.style.setProperty('width','100%','important');
  stageNode.style.setProperty('height','100%','important');
  stageNode.style.setProperty('min-height','0','important');
  stageNode.style.setProperty('max-height','none','important');
  stageNode.style.setProperty('gap','4px','important');
  stageNode.style.setProperty('overflow','hidden','important');
 }
 if(layout==='primary'){
  stageNode?.style.setProperty('grid-template-columns','minmax(0,2.25fr) minmax(260px,.9fr)','important');
  stageNode?.style.setProperty('grid-template-rows','repeat(3,minmax(0,1fr))','important');
 }else{
  const tileCount=cards.length+(pttPanel?1:0);
  const cols=tileCount<=1?1:tileCount<=4?2:tileCount<=9?3:4;
  const rows=Math.max(1,Math.ceil(tileCount/cols));
  stageNode?.style.setProperty('grid-template-columns','repeat('+cols+',minmax(0,1fr))','important');
  stageNode?.style.setProperty('grid-template-rows','repeat('+rows+',minmax(0,1fr))','important');
 }
 cards.forEach((card,index)=>{
  card.style.setProperty('position','relative','important');
  card.style.setProperty('display',(layout==='primary'&&card.classList.contains('focus-hidden'))?'none':'flex','important');
  card.style.setProperty('flex-direction','column','important');
  card.style.setProperty('width','100%','important');
  card.style.setProperty('height','100%','important');
  card.style.setProperty('min-width','0','important');
  card.style.setProperty('min-height','0','important');
  card.style.setProperty('max-width','none','important');
  card.style.setProperty('max-height','none','important');
  card.style.setProperty('overflow','hidden','important');
  if(layout==='primary'){
   if(card.classList.contains('primary')){card.style.setProperty('grid-column','1','important');card.style.setProperty('grid-row','1 / 4','important');}
   else if(card.classList.contains('focus-side-1')){card.style.setProperty('grid-column','2','important');card.style.setProperty('grid-row','1','important');}
   else if(card.classList.contains('focus-side-2')){card.style.setProperty('grid-column','2','important');card.style.setProperty('grid-row','2','important');}
  }else{
   card.style.setProperty('grid-column','auto','important');card.style.setProperty('grid-row','auto','important');
  }
 });
 wraps.forEach(wrap=>{
  wrap.style.setProperty('position','relative','important');
  wrap.style.setProperty('display','block','important');
  wrap.style.setProperty('flex','1 1 0','important');
  wrap.style.setProperty('width','100%','important');
  wrap.style.setProperty('height','100%','important');
  wrap.style.setProperty('min-width','0','important');
  wrap.style.setProperty('min-height','0','important');
  wrap.style.setProperty('max-width','none','important');
  wrap.style.setProperty('max-height','none','important');
  wrap.style.setProperty('aspect-ratio','auto','important');
  wrap.style.setProperty('overflow','hidden','important');
 });
 playersNodes.forEach(node=>{
  node.style.setProperty('position','absolute','important');
  node.style.setProperty('inset','0','important');
  node.style.setProperty('display','block','important');
  node.style.setProperty('width','100%','important');
  node.style.setProperty('height','100%','important');
  node.style.setProperty('min-width','0','important');
  node.style.setProperty('min-height','0','important');
  node.style.setProperty('max-width','none','important');
  node.style.setProperty('max-height','none','important');
 });
 controls.forEach(node=>node.style.setProperty('display','none','important'));
 pttPanel.style.setProperty('position','relative','important');
 pttPanel.style.setProperty('display','flex','important');
 pttPanel.style.setProperty('flex-direction','column','important');
 pttPanel.style.setProperty('width','100%','important');
 pttPanel.style.setProperty('height','100%','important');
 pttPanel.style.setProperty('min-width','0','important');
 pttPanel.style.setProperty('min-height','0','important');
 pttPanel.style.setProperty('max-width','none','important');
 pttPanel.style.setProperty('max-height','none','important');
 pttPanel.style.setProperty('overflow','hidden','important');
 if(layout==='primary'){pttPanel.style.setProperty('grid-column','2','important');pttPanel.style.setProperty('grid-row',streams.length===2?'2 / 4':'3','important');}
 else{pttPanel.style.setProperty('grid-column','auto','important');pttPanel.style.setProperty('grid-row','auto','important');}
 const pttContent=pttPanel.querySelector('iframe:not([hidden]),#ptt-worker-feed:not([hidden])');
 if(pttContent){
  pttContent.style.setProperty('display','block','important');
  pttContent.style.setProperty('flex','1 1 0','important');
  pttContent.style.setProperty('width','100%','important');
  pttContent.style.setProperty('height','100%','important');
  pttContent.style.setProperty('min-height','0','important');
  pttContent.style.setProperty('max-height','none','important');
 }
}

function applyImmersiveState(active){
 immersiveEnabled=Boolean(active);
 document.body.classList.toggle('custom-immersive',immersiveEnabled);
 mountImmersiveSurface(immersiveEnabled);
 forceSingleImmersiveGeometry(immersiveEnabled);
 forceMultiImmersiveGeometry(immersiveEnabled);
 repinWorkerPttAfterLayout();
 immerse?.setAttribute('aria-pressed',String(immersiveEnabled));
 if(watchImmersive)watchImmersive.textContent=immersiveEnabled?'退出沉浸模式':'沉浸模式';
 if(immerse)immerse.textContent=immersiveEnabled?'退出沉浸模式':'沉浸模式';
}
immerse?.addEventListener('click',async()=>{
 const next=!immersiveEnabled;
 applyImmersiveState(next);
 try{
  if(next&&!document.fullscreenElement){
   // Fullscreen the viewing surface itself, not the document: it enters the
   // browser top layer and cannot inherit the Client shell's max-width/rails.
   const surface=pttPanel&&contentGrid?contentGrid:document.documentElement;
   await surface.requestFullscreen();
  }
  else if(!next&&document.fullscreenElement)await document.exitFullscreen();
 }catch(_e){
  // Keep the CSS immersive state even when browser fullscreen is unavailable.
  statusBox.textContent=next?'已進入沉浸介面（瀏覽器未提供全螢幕）':'已退出沉浸介面';
 }
});
document.addEventListener('fullscreenchange',()=>{
 // Escape exits immersive if fullscreen was actually active. CSS-only immersive
 // remains valid when the browser refuses requestFullscreen().
 if(!document.fullscreenElement&&immersiveEnabled&&document.visibilityState==='visible'){
  applyImmersiveState(false);
 }else if(document.fullscreenElement){
  applyImmersiveState(true);
 }
});

function refreshMultiControls(){const active=streams.length>1;document.querySelectorAll('[data-layout]').forEach(button=>button.hidden=!active);for(const id of ['playerSyncLabel','focusChoices','focusCarousel','focusCarouselIntervalLabel','audioFollowLabel','playAll','pauseAll']){const el=document.getElementById(id);if(el)el.hidden=!active;}}
refreshMultiControls();
let layout=(config.layout||"auto")==='auto'&&streams.length===2?'equal':(config.layout||"auto"), primaryIndex=Number(config.primaryIndex||0), audioMaster=Number(config.audioMasterIndex||0);
const videoHeight=document.getElementById('videoHeight');
const videoHeightValue=document.getElementById('videoHeightValue');
videoHeight?.addEventListener('input',()=>{
 const height=Math.max(360,Math.min(1000,Number(videoHeight.value)||1000));
 document.querySelector('.custom-player-column')?.style.setProperty('--custom-video-height',height+'px');
 if(videoHeightValue)videoHeightValue.textContent=height+'px';
});
/* Clicking a catalog-confirmed live avatar immediately replaces only the
   selected slot. Do not reconstruct other YouTube players or guess offsets. */
document.querySelectorAll('.live-channel-rail-item[data-live-video-id]').forEach(link=>{
 link.addEventListener('click',event=>{
  const next=link.dataset.liveVideoId;
  if(!/^[A-Za-z0-9_-]{11}$/.test(next))return;
  event.preventDefault();
  const title=link.querySelector('strong')?.textContent||next;
  if(watchMode==='multi'){
    if(streams.some(stream=>stream.videoId===next))return;

    appendWatchStream(next,title,link.dataset.channelId||'');
    return;
  }
  const index=streams.length===1?0:replacementTarget;
  const player=players[index];
  if(!player||typeof player.loadVideoById!=='function')return;
  if(streams[index].videoId===next)return;
  syncEchoes.clear();pendingArchiveFollowers.clear();
  // Re-evaluate provenance after a source change. A verified collab timeline
  // survives only while every current stream still belongs to that event.
  // A new live source invalidates archive Seek, but 8501-style multi-live
  // play/pause linking remains on after user-selected channel replacement.
  if(syncPlayback)syncPlayback.checked=streams.length>1;
  streams[index].videoId=next;
  streams[index].channelId=link.dataset.channelId||'';
  recomputeVerifiedTimeline();
  persistWatchState();
  player.loadVideoById(next);
  if(index===primaryIndex&&typeof refreshPrimaryPtt==='function')setTimeout(()=>refreshPrimaryPtt(index),0);
  refreshRailVisibility();
  const activeCard=document.querySelector('.player-card[data-index="'+index+'"]');
  const label=activeCard?.querySelector('.player-label');
  if(label)label.textContent=title;
  const youtubeLink=activeCard?.querySelector('.player-youtube-link');
  if(youtubeLink)youtubeLink.href='https://www.youtube.com/watch?v='+encodeURIComponent(next);
  statusBox.textContent='已切換視角 '+String.fromCharCode(65+index)+'：'+title;
 });
});
const syncPlayback=document.getElementById('syncPlayback');
/* Multi-view is linked by default, but never auto-started. Verified archive
   collabs need the same default so the first user Play drives absolute-time
   follower seeks; manual multi-view keeps play/pause linking without guessed offsets. */
if(syncPlayback&&streams.length>1)syncPlayback.checked=true;
const playAll=document.getElementById('playAll'),pauseAll=document.getElementById('pauseAll');
const focusChoices=document.getElementById('focusChoices');
const focusCarousel=document.getElementById('focusCarousel');
const focusCarouselInterval=document.getElementById('focusCarouselInterval');
const focusCarouselIntervalOutput=document.getElementById('focusCarouselIntervalOutput');
const audioFollowFocus=document.getElementById('audioFollowFocus');
let focusTimer=null,focusCarouselMs=10000;
let syncMaster=primaryIndex;
const syncEchoes=new Map();
const pendingArchiveFollowers=new Set();
let nextPlayerSlotId=0;
const players=Array(streams.length).fill(null),stage=document.getElementById('stage'),statusBox=document.getElementById('status');
let replacementTarget=0;

const pttWorkerConfig={};
const pttResolverUrl=(config.pttResolverUrl||'');
let pttPlayback=null,pttTransport=null,pttPollTimer=null,pttResolveToken=0;
const pttWorkerFeed=document.getElementById('ptt-worker-feed');
const pttWorkerStatus=document.getElementById('ptt-worker-status');
const pttWorkerFollow=document.getElementById('ptt-worker-follow');
const pttWorkerStyle=document.getElementById('ptt-worker-style');
const pttWorkerFloor=document.getElementById('ptt-worker-floor');
const pttWorkerFloorQuick=document.getElementById('ptt-worker-floor-quick');
const pttDynamicTitle=document.getElementById('ptt-dynamic-title');
const pttLiveFrame=document.getElementById('ptt-live-frame');
const pttUnavailable=document.getElementById('ptt-dynamic-unavailable');
const pttWorkerOptions=document.getElementById('ptt-worker-options');
const pttWorkerFollowLabel=document.getElementById('ptt-worker-follow-label');
function pttReadSetting(name,fallback){
 try{const x=localStorage.getItem(name);return x===null?fallback:x;}catch(_){return fallback;}
}
function pttSaveSetting(name,value){
 try{localStorage.setItem(name,value);}catch(_){}
}
function pttApplyReaderSettings(){
 if(!pttWorkerFeed)return;
 const style=pttWorkerStyle?pttWorkerStyle.value:'history';
 const floors=pttWorkerFloor?pttWorkerFloor.checked:(pttWorkerFloorQuick?pttWorkerFloorQuick.checked:true);
 if(pttWorkerFloor)pttWorkerFloor.checked=floors;
 if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=floors;
 pttWorkerFeed.classList.toggle('ptt-worker-original',style==='original');
 pttWorkerFeed.classList.toggle('ptt-worker-hide-floor',!floors);
 pttWorkerFeed.querySelectorAll('.ptt-worker-floor').forEach(el=>{el.hidden=!floors;});
 if(pttLiveFrame?.contentWindow){
  pttLiveFrame.contentWindow.postMessage({type:'holoviewer:ptt-show-floor',show:Boolean(floors)},location.origin);
 }
}
if(pttWorkerStyle){
 pttWorkerStyle.value=pttReadSetting('holoviewer-ptt-style','history')==='original'?'original':'history';
 pttWorkerStyle.addEventListener('change',()=>{
  pttSaveSetting('holoviewer-ptt-style',pttWorkerStyle.value);pttApplyReaderSettings();
 });
}
const savedFloorSetting=pttReadSetting('holoviewer-ptt-show-floor','true')!=='false';
if(pttWorkerFloor)pttWorkerFloor.checked=savedFloorSetting;
if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=savedFloorSetting;
function pttSetFloorVisibility(checked){
 if(pttWorkerFloor)pttWorkerFloor.checked=checked;
 if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=checked;
 pttSaveSetting('holoviewer-ptt-show-floor',String(checked));
 pttApplyReaderSettings();
}
pttWorkerFloor?.addEventListener('change',()=>pttSetFloorVisibility(pttWorkerFloor.checked));
pttWorkerFloorQuick?.addEventListener('change',()=>pttSetFloorVisibility(pttWorkerFloorQuick.checked));
pttApplyReaderSettings();
let pttPermanentWarning='';
function pttWarn(message){pttPermanentWarning=message;pttSetStatus('');}
function pttSetStatus(message){if(pttWorkerStatus)pttWorkerStatus.textContent=pttPermanentWarning?(pttPermanentWarning+' · '+message):message;}
function pttRender(rows,state){
 if(!pttWorkerFeed)return;
 const isNearBottom=pttWorkerFeed.scrollHeight-pttWorkerFeed.clientHeight-pttWorkerFeed.scrollTop<32;
 const oldNodes=Array.from(pttWorkerFeed.children);
 const oldScroll=pttWorkerFeed.scrollTop;
 const oldPositions=new Map(oldNodes.map(el=>[el.dataset.key,{top:el.offsetTop,height:el.offsetHeight}]));
 const existing=new Map(oldNodes.map(el=>[el.dataset.key,el]));
 const fragment=document.createDocumentFragment();
 rows.slice(-300).forEach(row=>{
  let el=existing.get(row.key);
  if(!el){
   el=document.createElement('div');el.className='ptt-worker-row';el.dataset.key=row.key;
   const kind=document.createElement('span');kind.className='ptt-worker-kind';kind.textContent=row.kind||'推';
   const clock=document.createElement('span');clock.className='ptt-worker-clock';clock.textContent=row.clock||'';
   const floor=document.createElement('span');floor.className='ptt-worker-floor';floor.textContent=row.floor?row.floor+'樓':'';
   const body=document.createElement('span');body.className='ptt-worker-body';
   const author=document.createElement('span');author.className='ptt-worker-author';author.textContent=row.author+': ';
   const content=document.createElement('span');content.className='ptt-worker-content';content.textContent=row.content;
   body.append(author,content);el.append(kind,clock,floor,body);
  }
  const floor=el.querySelector('.ptt-worker-floor');
  if(floor)floor.hidden=Boolean(pttWorkerFloor&&!pttWorkerFloor.checked);
  fragment.appendChild(el);
 });
 const firstVisible=oldNodes.find(el=>
  oldPositions.get(el.dataset.key).top+oldPositions.get(el.dataset.key).height>oldScroll)||oldNodes[0];
 const incomingKeys=new Set(rows.slice(-300).map(row=>row.key));
 const survivors=oldNodes.filter(el=>incomingKeys.has(el.dataset.key));
 const anchor=(firstVisible&&incomingKeys.has(firstVisible.dataset.key))
  ?firstVisible
  :survivors.find(el=>oldPositions.get(el.dataset.key).top>=oldScroll)||survivors[survivors.length-1];
 const anchorKey=anchor&&anchor.dataset.key;
 const anchorOffset=anchor?oldPositions.get(anchorKey).top-oldScroll:0;
 pttWorkerFeed.replaceChildren(fragment);
 if(pttWorkerFollow&&pttWorkerFollow.checked&&isNearBottom)pttWorkerFeed.scrollTop=pttWorkerFeed.scrollHeight;
 else {
  const restored=anchorKey&&Array.from(pttWorkerFeed.children).find(el=>el.dataset.key===anchorKey);
  pttWorkerFeed.scrollTop=restored?restored.offsetTop-anchorOffset:oldScroll;
 }
 pttSetStatus('同步推文 '+state.visible+' / '+state.total+' 則');
}
function disposePttBinding(){
 if(pttPollTimer){clearInterval(pttPollTimer);pttPollTimer=null;}
 if(pttTransport){pttTransport.stop();pttTransport=null;}
 if(pttPlayback){pttPlayback.dispose();pttPlayback=null;}
 pttPermanentWarning='';
}
function showArchivePtt(index,payload){
 disposePttBinding();
 if(!players[index]||!pttWorkerFeed)return;
 if(pttLiveFrame){pttLiveFrame.hidden=true;pttLiveFrame.removeAttribute('src');}
 if(pttUnavailable)pttUnavailable.hidden=true;
 pttWorkerFeed.hidden=false;
 if(pttWorkerOptions){pttWorkerOptions.hidden=false;pttWorkerOptions.classList.remove('live-ptt-controls');}
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=false;
 if(pttDynamicTitle)pttDynamicTitle.textContent='同時段歷史 PTT（未確認完整）';
 pttWorkerFeed.replaceChildren();
 pttPlayback=HoloViewerPttPlayer.attach({
  player:players[index],start:payload.start,render:pttRender,
  initialMessages:Array.isArray(payload.messages)?payload.messages:[],
  status:(state,msg)=>{if(state==='error')pttSetStatus(msg);}
 });
 pttApplyReaderSettings();
 pttSetStatus('跟隨主視角 · 同時段歷史推文');
}
function showLivePtt(){
 disposePttBinding();
 if(pttWorkerFeed)pttWorkerFeed.hidden=true;
 if(pttUnavailable)pttUnavailable.hidden=true;
 // Keep the font slider available after the live iframe replaces the archive feed.
 // Archive-only style/floor options are suppressed by the live-ptt-controls class.
 if(pttWorkerOptions){pttWorkerOptions.hidden=false;pttWorkerOptions.classList.add('live-ptt-controls');}
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=true;
 if(pttLiveFrame){
  const src=pttLiveFrame.dataset.src||'/ptt-today?focus=1&embed=1';
  if(pttLiveFrame.getAttribute('src')!==src)pttLiveFrame.setAttribute('src',src);
  pttLiveFrame.hidden=false;
 }
 if(pttDynamicTitle)pttDynamicTitle.textContent='PTT 今日專串';
 pttSetStatus('跟隨目前主視角 LIVE');
 pttApplyReaderSettings();
}
function showUnavailablePtt(){
 disposePttBinding();
 if(pttWorkerFeed)pttWorkerFeed.hidden=true;
 if(pttLiveFrame){pttLiveFrame.hidden=true;pttLiveFrame.removeAttribute('src');}
 if(pttWorkerOptions)pttWorkerOptions.hidden=true;
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=true;
 if(pttUnavailable){
  pttUnavailable.hidden=false;
  pttUnavailable.textContent='目前主視角沒有可驗證的歷史 PTT 時間範圍；不會沿用上一支影片的推文。';
 }
 if(pttDynamicTitle)pttDynamicTitle.textContent='PTT 尚未對齊';
 pttSetStatus('');
}
async function refreshPrimaryPtt(index=primaryIndex){
 if(!pttResolverUrl)return;
 const stream=streams[index],player=players[index];
 if(!stream||!player)return;
 const token=++pttResolveToken;
 pttSetStatus('依主視角載入…');
 try{
  let payload;
  if(typeof config.pttResolve==='function')payload=await config.pttResolve(stream.videoId);
  else{
   const join=pttResolverUrl.includes('?')?'&':'?';
   const response=await fetch(pttResolverUrl+join+'video_id='+encodeURIComponent(stream.videoId),{cache:'no-store',credentials:'same-origin'});
   if(!response.ok)throw new Error('PTT HTTP '+response.status);
   payload=await response.json();
  }
  if(token!==pttResolveToken||streams[index]?.videoId!==stream.videoId)return;
  if(payload?.mode==='archive')showArchivePtt(index,payload);
  else if(payload?.mode==='live')showLivePtt();
  else showUnavailablePtt();
 }catch(_error){
  if(token===pttResolveToken)showUnavailablePtt();
 }
}
function startPttBridge(index){
 if(pttResolverUrl||typeof config.pttResolve==='function'){
  if(index===primaryIndex)refreshPrimaryPtt(index);
  return;
 }
 if(!pttWorkerFeed||pttPlayback||streams[index].videoId!==pttWorkerConfig.videoId)return;
 pttPlayback=HoloViewerPttPlayer.attach({
  player:players[index],start:pttWorkerConfig.start,render:pttRender,
  initialMessages:pttWorkerConfig.mode==='archive'?pttWorkerConfig.rows:[],
  status:(state,msg)=>{if(state==='error')pttSetStatus(msg);}
 });
 if(pttWorkerConfig.mode==='archive'){
  pttSetStatus('同時段歷史推文 · 來源 Coverage／Gap 未確認完整，非影片專屬留言');
  return;
 }
 pttTransport=HoloViewerWorkerPtt.create({
  aid:pttWorkerConfig.aid,endpoint:pttWorkerConfig.endpoint,mode:'history',
  onRows:rows=>pttPlayback.ingest(rows),
  onGap:cursor=>pttWarn('歷史資料存在缺口（purged cursor '+cursor+'）')
 });
 const refresh=()=>{
  const selected=players[index];
  if(selected&&typeof selected.getPlayerState==='function'&&typeof YT!=='undefined'&&YT.PlayerState&&selected.getPlayerState()===YT.PlayerState.ENDED){
    disposePttBinding();return;
  }
  return pttTransport.run().catch(error=>pttSetStatus('PTT 更新失敗：'+error.message));
 };
 refresh();pttPollTimer=setInterval(refresh,10000);
}
window.addEventListener('pagehide',disposePttBinding,{once:true});

const watchSingleMode=document.getElementById('watchSingleMode'),watchMultiMode=document.getElementById('watchMultiMode'),watchModeToggle=document.getElementById('watchModeToggle');
function refreshWatchMode(){
 const single=watchMode==='single';
 watchSingleMode?.setAttribute('aria-pressed',String(single));
 watchMultiMode?.setAttribute('aria-pressed',String(!single));
 watchModeToggle?.setAttribute('aria-checked',String(!single));
 document.body.classList.toggle('watch-multi',!single);
 refreshRailVisibility();
}
watchSingleMode?.addEventListener('click',()=>{watchMode='single';refreshWatchMode();statusBox.textContent='已切換至單人模式：點頭像替換直播';});
watchMultiMode?.addEventListener('click',()=>{watchMode='multi';refreshWatchMode();statusBox.textContent='已切換至多人模式：點頭像新增視角';});
watchModeToggle?.addEventListener('click',()=>{watchMode=watchMode==='single'?'multi':'single';refreshWatchMode();statusBox.textContent=watchMode==='single'?'已切換至單人模式：點頭像替換直播':'已切換至多人模式：點頭像新增視角';});
refreshWatchMode();
function setReplacementTarget(index){
 if(index<0||index>=streams.length)return;
 replacementTarget=index;
 document.querySelectorAll('.player-card').forEach((card,i)=>{
  card.classList.toggle('replacement-target',i===index);
  const button=card.querySelector('.replacement-choice');
  if(button)button.setAttribute('aria-pressed',String(i===index));
 });
}

function clampVolume(v){return Math.max(0,Math.min(100,Number(v)||0));}
function columnsFor(count){if(count<=1)return 1;if(count<=4)return 2;if(count<=9)return 3;return 4;}
function persistWatchState(){
 try{
  const url=new URL(window.location.href);
  url.searchParams.delete('stream');
  streams.forEach(stream=>url.searchParams.append('stream',stream.videoId));
  window.history.replaceState(null,'',url.pathname+'?'+url.searchParams.toString()+url.hash);
 }catch(_error){}
}
function applyLayout(){
  const tileCount=stage.children.length;
  const tileColumns=tileCount<=1?1:tileCount<=4?2:tileCount<=9?3:tileCount<=16?4:5;
  const tileRows=Math.max(1,Math.ceil(tileCount/tileColumns));
  document.documentElement.style.setProperty('--tile-count',String(tileCount));
  document.documentElement.style.setProperty('--tile-columns',String(tileColumns));
  document.documentElement.style.setProperty('--tile-rows',String(tileRows));
  document.body.classList.toggle('watch-grid',streams.length>=3);
  document.body.classList.toggle('layout-auto',layout==='auto');
  document.body.classList.toggle('layout-equal',layout==='equal');
  document.body.classList.toggle('layout-primary',layout==='primary');
  document.documentElement.style.setProperty('--columns',String(streams.length===1?1:(layout==='primary'?2:columnsFor(streams.length))));
  document.documentElement.style.setProperty('--side-count',String(Math.max(1,streams.length-1)));
  const focusSideIndices=[];
  if(layout==='primary'&&streams.length>1){
   for(let offset=1;offset<streams.length&&focusSideIndices.length<2;offset++){
    focusSideIndices.push((primaryIndex+offset)%streams.length);
   }
  }
  document.querySelectorAll('.player-card').forEach((card,index)=>{
   card.classList.toggle('primary',index===primaryIndex);
   const sidePosition=focusSideIndices.indexOf(index);
   card.classList.toggle('focus-hidden',layout==='primary'&&index!==primaryIndex&&sidePosition<0);
   card.classList.toggle('focus-side-1',layout==='primary'&&sidePosition===0);
   card.classList.toggle('focus-side-2',layout==='primary'&&sidePosition===1);
  });
  placePttForLayout();
  document.querySelectorAll('[data-layout]').forEach(button=>button.classList.toggle('active',button.dataset.layout===layout));
  focusChoices?.querySelectorAll('[data-focus-index]').forEach(button=>button.classList.toggle('active',layout==='primary'&&Number(button.dataset.focusIndex)===primaryIndex));
  document.querySelectorAll('.player-card').forEach((card,index)=>{
   const focus=card.querySelector('.focus');
   if(focus)focus.hidden=streams.length===1||(layout==='primary'&&index===primaryIndex);
  });
  if(immersiveEnabled&&streams.length>1)forceMultiImmersiveGeometry(true);
}
const globalVolume=document.getElementById('globalVolume');
const globalVolumeValue=document.getElementById('globalVolumeValue');
const immersiveGlobalVolume=document.getElementById('immersiveGlobalVolume');
const immersiveGlobalVolumeValue=document.getElementById('immersiveGlobalVolumeValue');
let masterVolume=100;
function setGlobalVolume(value){
 masterVolume=clampVolume(value);
 if(globalVolume)globalVolume.value=String(masterVolume);
 if(immersiveGlobalVolume)immersiveGlobalVolume.value=String(masterVolume);
 if(globalVolumeValue)globalVolumeValue.textContent=masterVolume+'%';
 if(immersiveGlobalVolumeValue)immersiveGlobalVolumeValue.textContent=masterVolume+'%';
 applyAudio();
}
globalVolume?.addEventListener('input',()=>setGlobalVolume(globalVolume.value));
immersiveGlobalVolume?.addEventListener('input',()=>setGlobalVolume(immersiveGlobalVolume.value));
function effectiveVolume(index){
 const slider=document.querySelector('.player-card[data-index="'+index+'"] .slider');
 return Math.round(masterVolume*clampVolume(slider?slider.value:100)/100);
}
function applyAudio(){
  players.forEach((player,index)=>{
    if(!player||typeof player.setVolume!=='function')return;
    player.setVolume(effectiveVolume(index));
    if(index===audioMaster)player.unMute();else player.mute();
  });
  document.querySelectorAll('.master').forEach((button,index)=>{
    const active=index===audioMaster;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));button.textContent=active?'主聲源':'設為聲源';
  });
}
function setPrimary(index,fromCarousel=false){
 if(index<0||index>=streams.length)return;
 if(!fromCarousel)stopFocusCarousel();
 primaryIndex=index;setReplacementTarget(index);layout='primary';applyLayout();
 if(audioFollowFocus?.checked){audioMaster=index;applyAudio();}
 if(typeof refreshPrimaryPtt==='function')refreshPrimaryPtt(index);
}
function stopFocusCarousel(){
 if(focusTimer!==null)clearInterval(focusTimer);
 focusTimer=null;
 if(focusCarousel){focusCarousel.classList.remove('active');focusCarousel.textContent='輪播 '+(focusCarouselMs/1000)+'s';}
}
function startFocusCarousel(){
 if(focusTimer!==null)clearInterval(focusTimer);
 focusTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length,true),focusCarouselMs);
}
if(streams.length>1){
 streams.forEach((stream,index)=>{
  const button=document.createElement('button');
  button.type='button';button.dataset.focusIndex=String(index);
  button.textContent='Focus '+String.fromCharCode(65+index);
  button.title=stream.label||('Stream '+(index+1));
  button.onclick=()=>setPrimary(index);
  focusChoices?.appendChild(button);
 });
}
focusCarousel?.addEventListener('click',()=>{
 if(focusTimer!==null){stopFocusCarousel();return;}
 if(audioFollowFocus)audioFollowFocus.checked=true;
 setPrimary(primaryIndex,true);
 focusCarousel.classList.add('active');
 focusCarousel.textContent='停止輪播';
 startFocusCarousel();
});
focusCarouselInterval?.addEventListener('input',()=>{
 focusCarouselMs=Math.max(10000,Math.min(60000,Number(focusCarouselInterval.value)*1000||10000));
 focusCarouselIntervalOutput.textContent=focusCarouselInterval.value+' 秒';
 if(focusTimer!==null)startFocusCarousel();
 else focusCarousel.textContent='輪播 '+focusCarouselInterval.value+'s';
});
audioFollowFocus?.addEventListener('change',()=>{
 if(audioFollowFocus.checked&&layout==='primary'){audioMaster=primaryIndex;applyAudio();}
});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopFocusCarousel();});
window.addEventListener('pagehide',stopFocusCarousel,{once:true});
function timelineSeconds(index){
 const player=players[index];
 return player&&typeof player.getCurrentTime==='function'
  ?Math.max(0,Number(player.getCurrentTime())||0):0;
}
function alignFollower(index,master){
 if(!hasVerifiedTimeline||index===master)return true;
 const player=players[index],source=players[master];
 if(!player||!source||typeof player.seekTo!=='function')return false;
 const expected=timelineStartFor(master)+timelineSeconds(master)-timelineStartFor(index);
 if(expected<0)return false;
 // YouTube can silently clamp seeks past the VOD end. Never chase that
 // unreachable position every 500ms. Treat it as standby until the
 // master returns to a playable instant within this source.
 const duration=typeof player.getDuration==='function'?Number(player.getDuration()):NaN;
 if(Number.isFinite(duration)&&duration>0&&expected>=duration)return false;
 if(Math.abs(timelineSeconds(index)-expected)>.8)player.seekTo(expected,true);
 return true;
}
function syncFollowers(master,playing){
  if(!syncPlayback?.checked)return;
  syncMaster=master;
  players.forEach((player,index)=>{
    if(index===master||!player)return;
    const canPlay=alignFollower(index,master);
    if(playing&&!canPlay){
      pendingArchiveFollowers.add(index);
      if(typeof player.pauseVideo==='function'){
        syncEchoes.set(index,{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000});
        player.pauseVideo();
      }
      return;
    }
    pendingArchiveFollowers.delete(index);
    const expected=playing?YT.PlayerState.PLAYING:YT.PlayerState.PAUSED;
    if(typeof player.getPlayerState==='function'&&player.getPlayerState()===expected)return;
    syncEchoes.set(index,{expected,expires:Date.now()+2000});
    if(playing&&typeof player.playVideo==='function')player.playVideo();
    else if(!playing&&typeof player.pauseVideo==='function')player.pauseVideo();
    else syncEchoes.delete(index);
  });
}
function handlePlayerState(index,event){
 if(!syncPlayback?.checked||!window.YT?.PlayerState)return;
 const echo=syncEchoes.get(index);
 if(echo){
  if(Date.now()>echo.expires)syncEchoes.delete(index);
  else if(event.data===echo.expected){
   syncEchoes.delete(index);
   return;
  }
  // BUFFERING / CUED can precede the induced PLAYING event.
  // Keep the expected echo until it matches; a real PAUSED/PLAYING
  // user action with a different state still propagates.
 }
 if(event.data===YT.PlayerState.PLAYING)syncFollowers(index,true);
 else if(event.data===YT.PlayerState.PAUSED)syncFollowers(index,false);
}
syncPlayback?.addEventListener('change',()=>{
 syncEchoes.clear();
 if(!syncPlayback.checked)pendingArchiveFollowers.clear();
 statusBox.textContent=syncPlayback.checked?'已啟用連動：操作任一播放器可一起播放／暫停':'獨立播放：播放器互不影響';
 if(!syncPlayback.checked)return;
 const master=players[syncMaster];
 if(!master||typeof master.getPlayerState!=='function')return;
 const state=master.getPlayerState();
 if(state===YT.PlayerState.PLAYING)syncFollowers(syncMaster,true);
 else if(state===YT.PlayerState.PAUSED)syncFollowers(syncMaster,false);
});
manualTimelineAlign?.addEventListener('change',()=>{
 syncEchoes.clear();pendingArchiveFollowers.clear();
 manualTimelineEnabled=Boolean(manualTimelineAlign.checked);
 recomputeVerifiedTimeline();
 if(manualTimelineAlign.checked&&!hasVerifiedTimeline){
  manualTimelineAlign.checked=false;
  manualTimelineEnabled=false;
  statusBox.textContent='目前影片缺少可用的實際開播時間，無法自動對齊';
  return;
 }
 if(manualTimelineAlign.checked){
  if(syncPlayback)syncPlayback.checked=true;
  syncMaster=primaryIndex;
  const master=players[syncMaster];
  const state=master&&typeof master.getPlayerState==='function'?master.getPlayerState():null;
  if(state===YT.PlayerState.PLAYING)syncFollowers(syncMaster,true);
  else if(state===YT.PlayerState.PAUSED)syncFollowers(syncMaster,false);
  else players.forEach((_,index)=>{if(index!==syncMaster)alignFollower(index,syncMaster);});
  statusBox.textContent='已啟用依實際開播時間自動對齊';
 }else{
  recomputeVerifiedTimeline();
  statusBox.textContent='已關閉時間軸自動對齊；仍可保留連動播放／暫停';
 }
});
function controlAllPlayback(playing){
 syncEchoes.clear();
 if(!playing)pendingArchiveFollowers.clear();
 syncMaster=primaryIndex;
 // Explicit archive group-play is consent to keep the verified timeline in sync.
 if(playing&&hasVerifiedTimeline&&syncPlayback)syncPlayback.checked=true;
 players.forEach((player,index)=>{
  if(!player)return;
  if(playing&&hasVerifiedTimeline&&index!==syncMaster&&!alignFollower(index,syncMaster)){
   pendingArchiveFollowers.add(index);
   if(typeof player.pauseVideo==='function'){
    syncEchoes.set(index,{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000});
    player.pauseVideo();
   }
   return;
  }
  const expected=playing?YT.PlayerState.PLAYING:YT.PlayerState.PAUSED;
  if(typeof player.getPlayerState==='function'&&player.getPlayerState()===expected)return;
  syncEchoes.set(index,{expected,expires:Date.now()+2000});
  if(playing&&typeof player.playVideo==='function')player.playVideo();
  else if(!playing&&typeof player.pauseVideo==='function')player.pauseVideo();
  else syncEchoes.delete(index);
 });
 statusBox.textContent=playing?'正在播放全部視角':'已暫停全部視角';
}
// Explicit group controls remain permitted; never infer archive offsets.
playAll?.addEventListener('click',()=>controlAllPlayback(true));
setInterval(()=>{
 if(!hasVerifiedTimeline||!syncPlayback?.checked)return;
 const master=players[syncMaster];
 if(!master||typeof master.getPlayerState!=='function')return;
 const state=master.getPlayerState();
 if(state!==YT.PlayerState.PLAYING&&state!==YT.PlayerState.PAUSED)return;
 players.forEach((_,index)=>{
  if(index===syncMaster)return;
  const ready=alignFollower(index,syncMaster);
  if(!ready){
   pendingArchiveFollowers.add(index);
   const follower=players[index];
   if(follower&&typeof follower.pauseVideo==='function'&&
      typeof follower.getPlayerState==='function'&&
      follower.getPlayerState()!==YT.PlayerState.PAUSED){
    syncEchoes.set(index,{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000});
    follower.pauseVideo();
   }
   return;
  }
  if(ready&&pendingArchiveFollowers.has(index)){
   pendingArchiveFollowers.delete(index);
   const follower=players[index];
   if(state===YT.PlayerState.PLAYING&&follower&&typeof follower.playVideo==='function'){
    syncEchoes.set(index,{expected:YT.PlayerState.PLAYING,expires:Date.now()+2000});
    follower.playVideo();
   }
  }
 });
},500);
pauseAll?.addEventListener('click',()=>controlAllPlayback(false));
function buildCard(stream,index){
  const card=document.createElement('section');card.className='player-card';card.dataset.index=String(index);card.dataset.slotId=String(nextPlayerSlotId++);
  card.innerHTML='<div class="video-wrap"><div id="player-'+card.dataset.slotId+'" class="player"></div></div><div class="player-controls"><div><div class="player-label"></div><div class="audio-row"><span>音量</span><input class="slider" type="range" min="0" max="100" step="1" value="100"></div></div><div class="player-actions"><a class="player-youtube-link" target="_blank" rel="noopener noreferrer">YouTube ↗</a><button class="master" type="button"></button><button class="replacement-choice" type="button" aria-pressed="false">換台目標</button><button class="focus" type="button">設為主要</button></div></div>';
  const youtubeLink=card.querySelector('.player-youtube-link');youtubeLink.href='https://www.youtube.com/watch?v='+encodeURIComponent(stream.videoId);
  card.querySelector('.player-label').textContent=stream.label;
  card.querySelector('.slider').oninput=()=>{const current=Number(card.dataset.index);const player=players[current];if(player&&typeof player.setVolume==='function')player.setVolume(effectiveVolume(current));};
  card.querySelector('.master').onclick=()=>{audioMaster=Number(card.dataset.index);applyAudio();};
  card.querySelector('.replacement-choice').onclick=()=>setReplacementTarget(Number(card.dataset.index));
  card.querySelector('.focus').onclick=()=>setPrimary(Number(card.dataset.index));
  if(streams.length===1)card.querySelector('.focus').hidden=true;
  const remove=document.createElement('button');remove.type='button';remove.className='remove-stream';remove.textContent='🗑';remove.title='移除這個直播';remove.setAttribute('aria-label','移除 '+stream.label);remove.onclick=()=>removeWatchStream(Number(card.dataset.index));
  card.querySelector('.player-actions').appendChild(remove);
  return card;
}
streams.forEach((stream,index)=>stage.appendChild(buildCard(stream,index)));
function refreshWatchCards(){
 stage.querySelectorAll('.player-card').forEach((card,index)=>{card.dataset.index=String(index);card.querySelector('.focus').hidden=streams.length===1;});
}
function removeWatchStream(index){
 if(streams.length<=1){statusBox.textContent='至少保留一個直播';return;}
 const player=players[index];if(player&&typeof player.destroy==='function')player.destroy();
 const card=stage.querySelector('.player-card[data-index="'+index+'"]');card?.remove();
 streams.splice(index,1);players.splice(index,1);syncEchoes.clear();pendingArchiveFollowers.clear();
 if(primaryIndex===index)primaryIndex=Math.min(index,streams.length-1);
 else if(primaryIndex>index)primaryIndex--;
 if(audioMaster===index)audioMaster=primaryIndex;else if(audioMaster>index)audioMaster--;
 if(replacementTarget>=streams.length)replacementTarget=0;
 // Rebuild only the lightweight focus buttons, never the surviving YouTube players.
 focusChoices?.replaceChildren();streams.forEach((stream,i)=>{const b=document.createElement('button');b.type='button';b.dataset.focusIndex=String(i);b.textContent='Focus '+String.fromCharCode(65+i);b.onclick=()=>setPrimary(i);focusChoices?.appendChild(b);});
 recomputeVerifiedTimeline();
 syncSessionCardinalityClasses();if(immersiveEnabled)forceSingleImmersiveGeometry(streams.length===1);refreshWatchCards();refreshMultiControls();applyLayout();refreshRailVisibility();setReplacementTarget(Math.min(replacementTarget,streams.length-1));applyAudio();persistWatchState();if(typeof refreshPrimaryPtt==='function')refreshPrimaryPtt(primaryIndex);statusBox.textContent='已移除視角';
}
function appendWatchStream(videoId,label,channelId=''){
 const index=streams.length,stream={videoId,label,channelId};streams.push(stream);players.push(null);
 const card=buildCard(stream,index);stage.appendChild(card);syncEchoes.clear();pendingArchiveFollowers.clear();recomputeVerifiedTimeline();
 const b=document.createElement('button');b.type='button';b.dataset.focusIndex=String(index);b.textContent='Focus '+String.fromCharCode(65+index);b.onclick=()=>setPrimary(index);focusChoices?.appendChild(b);
 syncSessionCardinalityClasses();if(immersiveEnabled)forceSingleImmersiveGeometry(false);refreshWatchCards();refreshMultiControls();applyLayout();refreshRailVisibility();persistWatchState();
 if(window.YT?.Player){mountWatchPlayer(index);}
 if(syncPlayback)syncPlayback.checked=true;
 statusBox.textContent='已加入視角 '+String.fromCharCode(65+index)+'：'+label;
}
const collabPollUrl=(config.collabPollUrl||"");
const collabLabel=(config.collabLabel||"");
let collabPollTimer=null,collabPollInFlight=false;
async function refreshLiveCollab(){
 if(!collabPollUrl||document.hidden||collabPollInFlight)return;
 collabPollInFlight=true;
 try{
  const response=await fetch(collabPollUrl,{cache:'no-store',headers:{'Accept':'application/json'}});
  if(!response.ok)return;
  const payload=await response.json();
  const additions=Array.isArray(payload.streams)?payload.streams:[];
  additions.forEach(item=>{
   const id=String(item.video_id||'');
   if(!/^[A-Za-z0-9_-]{11}$/.test(id)||streams.some(stream=>stream.videoId===id))return;
   appendWatchStream(id,String(item.label||id),String(item.channel_id||''));
  });
  if(additions.length&&collabLabel)statusBox.title=collabLabel+' · Live POV 自動更新中';
 }catch(_error){
  // Preserve the current player wall; the next interval retries discovery.
 }finally{collabPollInFlight=false;}
}
if(collabPollUrl){
 document.body.classList.add('collab-live-session');
 refreshLiveCollab();
 collabPollTimer=setInterval(refreshLiveCollab,15000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshLiveCollab();});
 window.addEventListener('pagehide',()=>{if(collabPollTimer)clearInterval(collabPollTimer);},{once:true});
}
setReplacementTarget(primaryIndex);
/* The PTT iframe stays mounted: move only its existing node into the
   stage so Focus layout can put it below the small second video. */
const pttPanel=document.querySelector('.ptt-live-panel');
const contentGrid=document.querySelector('.custom-content-grid');
function mountImmersiveSurface(active){
 // Never reparent a mounted YouTube iframe. Moving an iframe between DOM
 // parents can tear down its browsing context and stop an actively playing
 // single stream. Fullscreen promotes contentGrid to the top layer, while the
 // CSS geometry below handles browsers that decline requestFullscreen().
 void active;
}
function placePttForLayout(){
 if(!pttPanel||!contentGrid)return;
 if(streams.length>=2)stage.appendChild(pttPanel);
 else contentGrid.appendChild(pttPanel);
}
placePttForLayout();

document.querySelectorAll('[data-layout]').forEach(button=>button.onclick=()=>{stopFocusCarousel();layout=button.dataset.layout;applyLayout();if(layout==='primary'&&audioFollowFocus?.checked){audioMaster=primaryIndex;applyAudio();}});
applyLayout();
function mountWatchPlayer(index){
  const stream=streams[index];
  if(!stream||players[index])return;
  const card=stage.querySelector('.player-card[data-index="'+index+'"]');
  if(!card)return;
  const mounted=new YT.Player('player-'+card.dataset.slotId,{
      videoId:stream.videoId,width:'100%',height:'100%',playerVars:{playsinline:1,rel:0,controls:1},
      events:{onReady:()=>{const current=players.indexOf(mounted);if(current<0)return;applyAudio();if(playAll)playAll.disabled=false;if(pauseAll)pauseAll.disabled=false;if(typeof startPttBridge==='function')startPttBridge(current);},onStateChange:event=>{const current=players.indexOf(mounted);if(current>=0)handlePlayerState(current,event);},onError:event=>{const current=players.indexOf(mounted);if(current<0)return;const code=Number(event?.data);statusBox.textContent='YouTube 內嵌播放失敗'+(Number.isFinite(code)?'（錯誤 '+code+'）':'')+'；可用 YouTube ↗ 開啟原影片確認。';}}
  });
  players[index]=mounted;
}
window.onYouTubeIframeAPIReady=function(){streams.forEach((stream,index)=>mountWatchPlayer(index));};
const api=document.createElement('script');api.src='https://www.youtube.com/iframe_api';document.head.appendChild(api);
};
