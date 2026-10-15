/* Clean 4174 frontend transplant.
 * Product DOM/CSS/player ownership comes from 4174 a144bb3.
 * This file is only the Cloudflare API + static route boundary.
 */
(()=>{
'use strict';
const config=window.HOLOVIEWER_CONFIG||{};
const app=document.getElementById('app');
const topStatus=document.getElementById('topStatus');
const liveRail=document.getElementById('live-channel-rail');
const liveList=document.getElementById('live-channel-list');
let catalogCache=null;

const routePaths={home:'/',history:'/history',watchalong:'/watchalong',custom:'/custom-view',collab:'/collab',ptt:'/ptt-today'};
const bodyRouteClasses=['home-wide','watchalong-wide','custom-session-watching','layout-auto','layout-equal','layout-primary','single-ptt','single-live','single-vod','watch-grid','watch-multi','custom-immersive'];

function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
function videoId(input){
 const raw=String(input||'').trim();
 if(/^[A-Za-z0-9_-]{11}$/.test(raw))return raw;
 try{
  const u=new URL(raw);
  const host=u.hostname.replace(/^www\./,'');
  let id='';
  if(host==='youtu.be')id=u.pathname.split('/').filter(Boolean)[0]||'';
  else if(['youtube.com','m.youtube.com'].includes(host)){
   if(u.pathname==='/watch')id=u.searchParams.get('v')||'';
   else if(/^\/(live|embed|shorts)\//.test(u.pathname))id=u.pathname.split('/')[2]||'';
  }
  return /^[A-Za-z0-9_-]{11}$/.test(id)?id:null;
 }catch{return null;}
}
async function api(path){
 if(!/^https:\/\//.test(config.apiBase||''))throw Error('Cloudflare Public API 未設定');
 const response=await fetch(config.apiBase.replace(/\/$/,'')+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});
 if(!response.ok)throw Error('API HTTP '+response.status);
 return response.json();
}
function taipeiDay(){
 const p=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
 const o=Object.fromEntries(p.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return o.year+'-'+o.month+'-'+o.day;
}
function shiftDay(day,delta){const d=new Date(day+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+delta);return d.toISOString().slice(0,10);}
function englishDate(day){
 const d=new Date(day+'T12:00:00Z');
 return new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',weekday:'short',month:'short',day:'2-digit',year:'numeric'}).format(d).replace(',',' ·').toUpperCase();
}
function cleanupRoute(){
 window.hvExit4174Immersive?.();
 bodyRouteClasses.forEach(c=>document.body.classList.remove(c));
 liveRail.hidden=true;
 topStatus.textContent='';
 app.replaceChildren();
}
function setActive(route){
 document.querySelectorAll('[data-route]').forEach(a=>a.classList.toggle('active',a.dataset.route===route));
}
async function loadCatalog(){
 if(catalogCache)return catalogCache;
 const data=await api('/v1/catalog/today');
 const rows=Array.isArray(data.streams)?data.streams:Array.isArray(data.items)?data.items:null;
 if(!rows)throw Error('Catalog 格式錯誤');
 catalogCache=rows;
 return rows;
}
function stateOf(item){
 const state=String(item.lifecycle_state||item.state||'unknown').toLowerCase();
 if(state==='live')return 'live';
 if(['waiting','upcoming'].includes(state))return 'upcoming';
 if(state==='ended')return 'ended';
 return 'unknown';
}
function groupOf(item){return String(item.group||item.channel_group||'hololive').toLowerCase();}
function streamCard(item){
 const id=escapeHtml(item.video_id);
 const state=stateOf(item);
 const label=state==='live'?'LIVE':state==='upcoming'?'即將開始':state==='ended'?'已結束':'狀態待更新';
 const badgeClass=state==='live'?'live':state==='upcoming'?'upcoming':state==='ended'?'ended':'';
 const channel=escapeHtml(item.channel_title||item.channel_name||'頻道資訊待補');
 const title=escapeHtml(item.title||item.video_id);
 const avatar=String(item.avatar_url||'');
 const avatarHtml=/^https:\/\/(yt3\.ggpht\.com|i\.ytimg\.com)\//.test(avatar)
   ?'<img class="channel-avatar-img" src="'+escapeHtml(avatar)+'" alt="" loading="lazy">'
   :'<span class="channel-avatar-fallback" aria-hidden="true">'+escapeHtml(channel.slice(0,1)||'H')+'</span>';
 const href='/custom-view/session?stream='+encodeURIComponent(item.video_id)+'&layout=auto&primary=0&audio=0&ptt=video';
 const selectable=['live','upcoming','ended'].includes(state)?' data-multiview-id="'+id+'" aria-selected="false"':'';
 return '<a id="stream-'+id+'" class="client-card stream-card" data-group="'+escapeHtml(groupOf(item))+'" href="'+href+'"'+selectable+'>'
  +'<div class="card-thumb"><img src="https://i.ytimg.com/vi/'+id+'/mqdefault.jpg" alt="" loading="lazy">'
  +'<span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v='+id+'">YouTube ↗</span>'
  +'<div class="thumb-overlay"><span class="thumb-badge '+badgeClass+'">'+label+'</span><span class="thumb-time">'+escapeHtml(item.start_label||item.start_time_label||'')+'</span></div></div>'
  +'<div class="yt-meta"><span class="channel-avatar-ring">'+avatarHtml+'</span><div class="yt-copy"><h3 class="stream-title">'+title+'</h3><div class="channel-name">'+channel+'</div></div></div></a>';
}
function section(title,rows,subtitle=''){
 if(!rows.length)return '';
 return '<section class="section"><div class="section-head"><div><h2>'+escapeHtml(title)+'</h2>'+(subtitle?'<p>'+escapeHtml(subtitle)+'</p>':'')+'</div></div><div class="client-grid">'+rows.map(streamCard).join('')+'</div></section>';
}
function renderRail(rows){
 const live=rows.filter(x=>stateOf(x)==='live');
 const seen=new Set();
 liveList.replaceChildren();
 for(const item of live){
  const key=item.channel_id||item.channel_title||item.channel_name||item.video_id;
  if(seen.has(key))continue;seen.add(key);
  const a=document.createElement('a');a.className='live-channel-rail-item';a.href='#stream-'+item.video_id;
  a.dataset.liveVideoId=item.video_id;a.dataset.channelId=String(item.channel_id||'');a.dataset.group=groupOf(item);
  const avatar=document.createElement('span');avatar.className='live-channel-avatar';
  if(/^https:\/\/(yt3\.ggpht\.com|i\.ytimg\.com)\//.test(String(item.avatar_url||''))){const img=document.createElement('img');img.src=item.avatar_url;img.alt='';img.loading='lazy';avatar.append(img);}
  else{const fallback=document.createElement('span');fallback.textContent=String(item.channel_title||item.channel_name||'H').slice(0,1);avatar.append(fallback);}
  avatar.append(document.createElement('i'));
  const strong=document.createElement('strong');strong.textContent=item.channel_title||item.channel_name||'頻道資訊待補';
  a.append(avatar,strong);liveList.append(a);
 }
 liveRail.hidden=!liveList.children.length;
}
function wireYoutubeLinks(root=app){
 root.querySelectorAll('[data-youtube-href]').forEach(el=>{
  el.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();window.open(el.dataset.youtubeHref,'_blank','noopener,noreferrer');});
  el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();window.open(el.dataset.youtubeHref,'_blank','noopener,noreferrer');}});
 });
}
function wirePathLinks(root=app){
 root.querySelectorAll('a[href^="/"]').forEach(a=>{
  if(a.target==='_blank')return;
  a.addEventListener('click',e=>{if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();history.pushState(null,'',a.getAttribute('href'));renderRoute();});
 });
}

async function renderHome(){
 cleanupRoute();setActive('home');document.body.classList.add('home-wide');topStatus.textContent=englishDate(taipeiDay());
 app.innerHTML='<div id="homeDynamic"><div class="page-head"><div><h1>今日直播</h1></div></div><p class="empty-note">載入中…</p></div>';
 try{
  const rows=await loadCatalog();renderRail(rows);
  const buckets={live:[],upcoming:[],unknown:[],ended:[]};rows.forEach(x=>buckets[stateOf(x)].push(x));
  app.innerHTML='<div id="homeDynamic">'
   +'<div class="page-head"><div><h1>今日直播</h1></div></div>'
   +'<div class="stream-filter" role="group" aria-label="直播群組"><button class="stream-filter-button active" type="button" data-filter="hololive">Hololive</button><button class="stream-filter-button" type="button" data-filter="holostars">HOLOSTARS</button><button class="stream-filter-button" type="button" data-filter="mekpark">mekPark</button><button class="stream-filter-button" type="button" data-filter="all">全部</button></div>'
   +section('現在直播中',buckets.live,'目前可直接觀看的直播。')
   +section('即將開始',buckets.upcoming,'已排程、尚未開始的直播。')
   +section('狀態待更新',buckets.unknown,'已找到直播，但目前沒有足夠新的 lifecycle 證據。')
   +'<section class="section"><div class="section-head"><div><h2>觀看方式</h2></div></div><div class="feature-row">'
   +'<a class="feature-card" href="/watchalong"><div><span class="eyebrow">WATCHALONG</span><strong>同時視聽</strong></div><span>Hololive 保持主時間軸，片源跟隨觀看。</span></a>'
   +'<a class="feature-card" href="/custom-view"><div><span class="eyebrow">CUSTOM</span><strong>自訂觀看</strong></div><span>自由加入直播、排列畫面並指定主要聲音。</span></a>'
   +'<a class="feature-card" href="/ptt-today"><div><span class="eyebrow">PTT</span><strong>PTT 今日專串</strong></div><span>只留下今天的 PTT 推文時間軸。</span></a>'
   +'</div></section>'+section('已結束',buckets.ended,'今天已完成的直播存檔。')+'</div>';
  app.querySelectorAll('.stream-filter-button').forEach(b=>b.onclick=()=>{const f=b.dataset.filter;app.querySelectorAll('.stream-filter-button').forEach(x=>x.classList.toggle('active',x===b));app.querySelectorAll('.stream-card').forEach(c=>c.hidden=f!=='all'&&c.dataset.group!==f);});
  wireYoutubeLinks();wirePathLinks();
 }catch(e){app.innerHTML='<div class="page-head"><div><h1>今日直播</h1></div></div><p class="form-error">'+escapeHtml(e.message)+'</p>';}
}

function customPicker(rows){
 const live=rows.filter(x=>stateOf(x)==='live');
 if(!live.length)return '<p class="empty-note">目前沒有可用的直播，仍可貼上影片網址。</p>';
 return '<div class="live-picker-list">'+live.map(item=>{
  const id=escapeHtml(item.video_id),channel=escapeHtml(item.channel_title||item.channel_name||'Hololive'),title=escapeHtml(item.title||'');
  return '<div class="live-picker-item" role="button" tabindex="0" data-live-pick="'+id+'" data-channel="'+channel+'" data-title="'+title+'" data-avatar="'+escapeHtml(item.avatar_url||'')+'" aria-pressed="false"><div style="position:relative"><img src="https://i.ytimg.com/vi/'+id+'/mqdefault.jpg" alt="" loading="lazy"><span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v='+id+'">YouTube ↗</span></div><span><strong>'+channel+'</strong> · '+title+'</span></div>';
 }).join('')+'</div>';
}
async function renderCustom(){
 cleanupRoute();setActive('custom');
 app.innerHTML='<div class="page-head"><div><h1>自訂觀看</h1><p>自己挑任意直播組合，再交給系統排版。</p></div></div><p class="empty-note">載入中…</p>';
 try{
  const rows=await loadCatalog();renderRail(rows);
  app.innerHTML='<div class="page-head"><div><h1>自訂觀看</h1><p>自己挑任意直播組合，再交給系統排版。</p></div></div>'
   +'<div class="custom-layout"><section class="custom-main"><div class="search-box"><input id="url" aria-label="YouTube URL 或 Video ID" placeholder="貼上 YouTube URL 或 Video ID"><button id="add" class="subtle-action" type="button">加入網址</button></div>'
   +'<div class="builder-note">可直接點選正在直播的影片，或貼上任意 YouTube 影片網址。跨日期組合不會猜測共用 PTT。</div>'
   +'<div class="live-picker"><span class="eyebrow">影片庫 · 點選影片加入播放設定</span><div class="library-tabs" role="tablist" aria-label="影片來源"><button type="button" role="tab" data-library-tab="live" aria-selected="true">直播中</button><button type="button" role="tab" data-library-tab="history" aria-selected="false">歷史影片</button></div>'
   +'<div id="liveLibrary" role="tabpanel"><div class="library-display"><span class="empty-note">選擇想一起觀看的直播</span><button id="displayMode" type="button">精簡列表</button></div>'+customPicker(rows)+'</div><div id="historyLibrary" role="tabpanel" hidden><p class="library-empty">歷史影片搜尋功能準備中。目前可直接貼上 YouTube 影片網址加入觀看清單。</p></div></div></section>'
   +'<aside class="selection-panel"><span class="eyebrow">播放設定 · 拖曳調整順序</span><h2>已選 <span id="selectedCount">0</span> 個直播</h2><div id="list" class="selected-list"><div class="empty-selection">還沒有選擇直播。</div></div>'
   +'<div class="custom-settings"><div class="controls"><label id="layoutControl" hidden>版面<select id="layout"><option value="auto">自動</option><option value="equal">平均排列</option><option value="primary">主視角</option></select></label><select id="primary" hidden aria-label="主要畫面索引"></select><label>主要聲音<select id="audio"></select></label><label>觀看版型<select id="pttMode"><option value="live">影片＋即時 PTT 專串</option><option value="video">純影片</option></select></label><span class="empty-note">即時專串不顯示搜尋；歷史 VOD 專串需使用對應日期資料，避免誤連今天的推文。</span></div></div><div class="start-row"><button id="start" class="primary-action" type="button">開始觀看</button></div></aside></div>';
  wireYoutubeLinks();window.mount4174CustomView();
 }catch(e){app.innerHTML='<div class="page-head"><div><h1>自訂觀看</h1></div></div><p class="form-error">'+escapeHtml(e.message)+'</p>';}
}

async function renderSession(){
 cleanupRoute();setActive('custom');
 const q=new URLSearchParams(location.search);
 const ids=[...new Set(q.getAll('stream').map(videoId).filter(Boolean))];
 if(!ids.length){history.replaceState(null,'','/custom-view');return renderCustom();}
 const layout=['auto','equal','primary'].includes(q.get('layout'))?q.get('layout'):'auto';
 const primary=Math.max(0,Math.min(ids.length-1,Number(q.get('primary')||0)||0));
 const audio=Math.max(0,Math.min(ids.length-1,Number(q.get('audio')||0)||0));
 const ptt=q.get('ptt')==='live'?'live':'video';
 document.body.classList.add('custom-session-watching','layout-'+layout);
 if(ids.length===1&&ptt==='live')document.body.classList.add('single-ptt','single-live');
 try{
  const rows=await loadCatalog();renderRail(rows);
  const byId=new Map(rows.map(x=>[x.video_id,x]));
  const streams=ids.map((id,i)=>{const x=byId.get(id)||{};return {videoId:id,label:x.title||x.channel_title||x.channel_name||('Stream '+(i+1)),channelId:x.channel_id||''};});
  app.replaceChildren(window.render4174SharedViewerDOM(ptt==='live'));
  window.mount4174SharedViewer({streams,layout,primaryIndex:primary,audioMasterIndex:audio,singlePttKind:ptt==='live'?'live':'',translationA:[],translationB:[],verifiedTimelineStarts:{},manualTimelineStarts:{},collabPollUrl:'',collabLabel:''});
 }catch(e){app.innerHTML='<p class="form-error">播放器啟動失敗：'+escapeHtml(e.message)+'</p>';}
}

async function renderHistory(){
 cleanupRoute();setActive('history');
 const today=taipeiDay(),latest=shiftDay(today,-1),earliest=shiftDay(today,-30);
 const q=new URLSearchParams(location.search);let day=q.get('date')||latest;if(day<earliest||day>latest)day=latest;
 topStatus.textContent=englishDate(day);
 app.innerHTML='<div class="page-head"><div><h1>歷史直播</h1><p>依日期查看已完成的直播。</p></div></div><form class="history-picker" id="historyForm"><label>日期<input id="historyDate" type="date" min="'+earliest+'" max="'+latest+'" value="'+day+'"></label><button class="primary-action" type="submit">查看</button></form><div id="historyResult"><p class="empty-note">載入中…</p></div>';
 document.getElementById('historyForm').onsubmit=e=>{e.preventDefault();history.pushState(null,'','/history?date='+encodeURIComponent(document.getElementById('historyDate').value));renderHistory();};
 try{
  const data=await api('/v1/history?day='+encodeURIComponent(day)+'&limit=50&offset=0');
  const rows=Array.isArray(data.items)?data.items:[];
  document.getElementById('historyResult').innerHTML='<section class="section"><div class="section-head"><div><h2>'+day.replaceAll('-','/')+'</h2></div></div>'+(rows.length?'<div class="client-grid">'+rows.map(streamCard).join('')+'</div>':'<p class="empty-note">這一天沒有可顯示的直播。</p>')+'</section>';
  wireYoutubeLinks();wirePathLinks();
 }catch(e){document.getElementById('historyResult').innerHTML='<p class="form-error">'+escapeHtml(e.message)+'</p>';}
}
function renderWatchalong(){
 cleanupRoute();setActive('watchalong');document.body.classList.add('watchalong-wide');
 app.innerHTML='<div class="page-head"><div><h1>同時視聽</h1></div></div><section class="section"><div class="tool-card manual-shell"><span class="eyebrow">4174 FRONTEND</span><h2>同時視聽</h2><p class="empty-note">4174 Watchalong 前端正在同一條 clean transplant 線搬移；不會回退到舊 Public controller。</p></div></section>';
}
function renderCollab(){
 cleanupRoute();setActive('collab');
 app.innerHTML='<div class="page-head"><div><h1>多人連動</h1><p>只顯示後端已驗證的連動事件。</p></div></div><p class="empty-note">Cloudflare Public API 目前尚未提供已驗證多人連動契約，因此不製造假資料。</p>';
}
function renderPtt(){
 cleanupRoute();setActive('ptt');
 app.innerHTML='<div class="page-head"><div><h1>PTT 今日專串</h1><p>'+taipeiDay().replaceAll('-','/')+' · 純 PTT 閱讀</p></div></div><p class="empty-note">Cloudflare Public API 的 PTT Reader 契約尚未接入；8788 不會使用 Python／SQLite fallback。</p>';
}
function routeKey(){
 const p=location.pathname;
 if(p==='/custom-view/session')return 'session';
 if(p==='/history')return 'history';
 if(p==='/watchalong')return 'watchalong';
 if(p==='/custom-view')return 'custom';
 if(p==='/collab')return 'collab';
 if(p==='/ptt-today')return 'ptt';
 return 'home';
}
function renderRoute(){
 const key=routeKey();
 if(key==='session')return renderSession();
 if(key==='history')return renderHistory();
 if(key==='watchalong')return renderWatchalong();
 if(key==='custom')return renderCustom();
 if(key==='collab')return renderCollab();
 if(key==='ptt')return renderPtt();
 return renderHome();
}
document.querySelectorAll('[data-route]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();history.pushState(null,'',routePaths[a.dataset.route]||'/');renderRoute();}));
document.getElementById('mobileNavButton').onclick=()=>{const n=document.getElementById('mobileNav');const opening=n.hidden;n.hidden=!opening;document.getElementById('mobileNavButton').setAttribute('aria-expanded',String(opening));};
window.addEventListener('popstate',renderRoute);
renderRoute();
})();
