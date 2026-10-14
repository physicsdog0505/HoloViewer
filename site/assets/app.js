'use strict';
const config=window.HOLOVIEWER_CONFIG||{};
const $=id=>document.getElementById(id);
const names={home:'今日直播',single:'自訂觀看',multi:'多人連動',history:'歷史直播',ptt:'PTT 今日專串',watchalong:'同時視聽'};
const stored=(()=>{try{return JSON.parse(sessionStorage.getItem('hvMulti')||'[]')}catch{return []}})();
const state={multi:Array.isArray(stored)?stored.filter(x=>typeof x==='string'&&/^[\w-]{11}$/.test(x)).slice(0,12):[],offset:0};
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function message(target,text){const box=$(target);box.replaceChildren(node('div',text,'notice'))}
function videoId(input){let t=input.trim();if(/^[\w-]{11}$/.test(t))return t;try{const u=new URL(t);if(!['youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be'].includes(u.hostname))return null;t=u.hostname.includes('youtu.be')?u.pathname.split('/')[1]:u.pathname==='/watch'?u.searchParams.get('v'):['live','embed','shorts'].includes(u.pathname.split('/')[1])?u.pathname.split('/')[2]:null;return /^[\w-]{11}$/.test(t||'')?t:null}catch{return null}}
function frame(id){const f=document.createElement('iframe');f.className='frame';f.title='YouTube player '+id;f.src='https://www.youtube-nocookie.com/embed/'+encodeURIComponent(id)+'?enablejsapi=1';f.allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';f.referrerPolicy='strict-origin-when-cross-origin';f.allowFullscreen=true;return f}
function single(id,target='single-player'){if(!id){message(target,'請輸入有效的 YouTube 網址或影片 ID。');return}$(target).replaceChildren(frame(id))}
function renderMulti(){const box=$('multi-players');box.replaceChildren();state.multi.forEach(id=>{const wrap=node('div',undefined,'multi-item');wrap.append(frame(id));const actions=node('div',undefined,'entry');const remove=node('button','移除 '+id,'secondary');remove.onclick=()=>{state.multi=state.multi.filter(x=>x!==id);renderMulti()};actions.append(remove);wrap.append(actions);box.append(wrap)});sessionStorage.setItem('hvMulti',JSON.stringify(state.multi));if(!state.multi.length)message('multi-players','新增影片後可在同一頁觀看。')}
function route(r){if(!names[r])r='home';document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id===r));document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.addEventListener('click',()=>setHomeFilter(button.dataset.filter)));
window.addEventListener('storage',event=>{if(event.key===HOME_FILTER_KEY)applyHomeFilter()});
$('historyMultiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('historyMultiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;if(ids.length===1){single(ids[0]);route('single')}else{state.multi=ids.slice(0,12);renderMulti();route('multi')}};
$('multiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('multiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;if(ids.length===1){single(ids[0]);route('single')}else{state.multi=ids.slice(0,12);renderMulti();route('multi')}};
document.querySelectorAll('[data-page-link]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.pageLink)}));
document.querySelectorAll('[data-route]').forEach(el=>el.classList.toggle('active',el.dataset.route===r));document.querySelectorAll('[data-mobile-route]').forEach(el=>el.classList.toggle('active',el.dataset.mobileRoute===r));$('page-title').textContent=names[r];$('mobileNav').hidden=true;$('mobileNavButton').setAttribute('aria-expanded','false');history.replaceState(null,'','#'+r);document.body.classList.toggle('home-wide',r==='home'||r==='history');$('live-channel-rail').hidden=r!=='home'||!$('live-channel-list').childElementCount;if(r==='home')loadHome();if(r==='history')loadHistory();if(r==='ptt')loadPtt()}
async function api(path){if(!config.apiBase||!/^https:\/\//.test(config.apiBase))throw Error('尚未設定正式 Worker API');const base=config.apiBase.replace(/\/$/,'');const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});if(!response.ok)throw Error('API HTTP '+response.status);return response.json()}
function catalogCard(item,container){if(!item||! /^[\w-]{11}$/.test(item.video_id||''))return;const card=node('div',undefined,'card');card.append(node('strong',String(item.title||item.video_id)));card.append(node('p',String(item.channel_name||item.lifecycle_state||''),'sub'));const btn=node('button','單人觀看');btn.onclick=()=>{single(item.video_id);route('single')};card.append(btn);card.append(' ');const multi=node('button','加入多人','secondary');multi.onclick=()=>{if(!state.multi.includes(item.video_id)&&state.multi.length<12)state.multi.push(item.video_id);renderMulti();route('multi')};card.append(multi);container.append(card)}
const HOME_FILTER_KEY='holoviewer-live-filter';
const HOME_FILTERS=new Set(['hololive','holostars','mekpark','all']);
const selectedHomeVideos=new Set();
function homeFilter(){try{const x=localStorage.getItem(HOME_FILTER_KEY);return HOME_FILTERS.has(x)?x:'hololive'}catch{return 'hololive'}}
function setHomeFilter(value){if(!HOME_FILTERS.has(value))return;try{localStorage.setItem(HOME_FILTER_KEY,value)}catch{}applyHomeFilter(value)}
function applyHomeFilter(value=homeFilter()){
 document.querySelectorAll('#homeDynamic .stream-card').forEach(card=>{card.hidden=value!=='all'&&card.dataset.group!==value});
 document.querySelectorAll('#live-channel-list .live-channel-rail-item').forEach(card=>{card.hidden=value!=='all'&&card.dataset.group!==value});
 document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.classList.toggle('active',button.dataset.filter===value));
}
function homeSelection(){
 document.querySelectorAll('#homeDynamic .stream-card[data-multiview-id],#historyDynamic .stream-card[data-multiview-id]').forEach(card=>{const on=selectedHomeVideos.has(card.dataset.multiviewId);card.classList.toggle('multi-selected',on);card.setAttribute('aria-selected',String(on))});
 const count=selectedHomeVideos.size;for(const [bar,countEl,watch] of [['multiSelectBar','multiSelectCount','multiWatch'],['historyMultiSelectBar','historyMultiSelectCount','historyMultiWatch']]){
  $(bar).hidden=!count;$(countEl).textContent='已選 '+count+' 個影片';$(watch).textContent=count>1?'開始多視角觀看':'觀看選取影片';
 }
}
function homeCard(item,container){
 if(!item||! /^[\\w-]{11}$/.test(item.video_id||''))return;
 const id=item.video_id;const lifecycle=String(item.lifecycle_state||item.state||'unknown').toLowerCase();
 const group=String(item.group||item.channel_group||'other').toLowerCase();
 const href='/custom-view/session?stream='+encodeURIComponent(id)+'&layout=auto&primary=0&audio=0';
 const card=node('a',undefined,'client-card stream-card');card.href=href;card.dataset.group=group;card.id='stream-'+id;
 const states={live:['LIVE','live'],waiting:['等待中','upcoming'],upcoming:['即將開始','upcoming'],ended:['已結束','ended'],unknown:['狀態待更新',''],stale:['狀態待更新','']};
 const status=states[lifecycle]||states.unknown;
 if(['live','waiting','upcoming','ended'].includes(lifecycle)){card.dataset.multiviewId=id;card.setAttribute('aria-selected','false')}
 const thumb=node('div',undefined,'card-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
 const youTube=node('span','YouTube ↗','youtube-source-link');youTube.role='link';youTube.tabIndex=0;youTube.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;thumb.append(youTube);
 const overlay=node('div',undefined,'thumb-overlay');overlay.append(node('span',status[0],'thumb-badge '+status[1]));
 const time=String(item.start_label||item.start_time_label||'');overlay.append(node('span',time,'thumb-time'));thumb.append(overlay);card.append(thumb);
 const meta=node('div',undefined,'yt-meta');const ring=node('span',undefined,'channel-avatar-ring');const name=String(item.channel_title||item.channel_name||'頻道資訊待補');const first=[...name].find(c=>/[a-zA-Z0-9]/.test(c))||'H';
 ring.append(node('span',first.toUpperCase(),'channel-avatar-fallback'));meta.append(ring);
 const copy=node('div',undefined,'yt-copy');copy.append(node('h3',String(item.title||id),'stream-title'));copy.append(node('div',name,'channel-name'));meta.append(copy);card.append(meta);
 card.addEventListener('click',event=>{
  const source=event.target.closest('[data-youtube-href]');
  if(source){event.preventDefault();event.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer');return}
  event.preventDefault();if(!card.dataset.multiviewId){single(id);route('single');return}
  if(selectedHomeVideos.has(id))selectedHomeVideos.delete(id);else selectedHomeVideos.add(id);homeSelection()
 });
 card.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-youtube-href]')){event.preventDefault();event.stopPropagation();window.open(event.target.dataset.youtubeHref,'_blank','noopener,noreferrer')}});
 container.append(card);
}
function homeRail(items){const box=$('live-channel-list');box.replaceChildren();const seen=new Set();
 items.forEach(item=>{const id=item.video_id;if(!/^[\\w-]{11}$/.test(id||''))return;const key=item.channel_id||item.channel_name||item.channel_title||id;if(seen.has(key))return;seen.add(key);
 const link=node('a',undefined,'live-channel-rail-item');link.href='#stream-'+id;link.dataset.group=String(item.group||item.channel_group||'other').toLowerCase();
 const avatar=node('span',undefined,'live-channel-avatar');const name=String(item.channel_title||item.channel_name||'頻道資訊待補');avatar.append(node('span',([...name].find(c=>/[a-zA-Z0-9]/.test(c))||'H').toUpperCase()));avatar.append(node('i'));link.append(avatar);link.append(node('strong',name));
 link.onclick=event=>{event.preventDefault();const card=$('stream-'+id);card?.scrollIntoView({block:'center',behavior:'smooth'})};box.append(link)});
 $('live-channel-rail').hidden=!box.children.length||!$('home').classList.contains('active');
}
async function loadHome(){
 if(!config.apiBase){$('home-empty').textContent='正式直播資料 API 尚未接通。';return}
 try{
 const data=await api('/v1/catalog/today');const rows=data.streams||data.items;
 if(!Array.isArray(rows))throw Error('資料格式錯誤');
 const buckets={live:[],upcoming:[],unknown:[],ended:[]};
 rows.forEach(item=>{const state=String(item.lifecycle_state||item.state||'unknown').toLowerCase();const bucket=state==='live'?'live':['waiting','upcoming'].includes(state)?'upcoming':state==='ended'?'ended':'unknown';buckets[bucket].push(item)});
 for(const key of Object.keys(buckets)){const el=$('home-'+key);el.replaceChildren();buckets[key].forEach(item=>homeCard(item,el));$('home-'+key+'-section').hidden=!el.children.length}
 const allowed=new Set(rows.map(item=>item.video_id));for(const id of selectedHomeVideos){if(!allowed.has(id))selectedHomeVideos.delete(id)}
 homeSelection();homeRail(buckets.live);applyHomeFilter();
 $('home-empty').textContent=rows.length?'':'目前沒有今天的直播資料。';
 $('connection').textContent='API 已連線';
 }catch(e){$('home-empty').textContent='無法讀取正式直播資料：'+e.message}
}
function taipeiDay(){const p=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const o=Object.fromEntries(p.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));return o.year+'-'+o.month+'-'+o.day}
function shiftDay(day,delta){const date=new Date(day+'T00:00:00Z');date.setUTCDate(date.getUTCDate()+delta);return date.toISOString().slice(0,10)}
function historyBounds(){const today=taipeiDay();return {earliest:shiftDay(today,-30),latest:shiftDay(today,-1)}}
function historyDateValid(day){const b=historyBounds();return /^\\d{4}-\\d{2}-\\d{2}$/.test(day)&&day>=b.earliest&&day<=b.latest}
function historyLink(label,day,page=1){const link=node('a',label,'subtle-action');link.href='/history?date='+encodeURIComponent(day)+(page>1?'&page='+page:'');link.onclick=e=>{e.preventDefault();$('historyDate').value=day;state.offset=(page-1)*50;loadHistory()};return link}
function historyChrome(){const b=historyBounds();const input=$('historyDate');input.min=b.earliest;input.max=b.latest;if(!historyDateValid(input.value)){input.value=b.latest;state.offset=0}
 const selected=input.value;const shortcuts=$('history-shortcuts');shortcuts.replaceChildren();
 [['昨天',b.latest],['前天',shiftDay(b.latest,-1)],['7 天前',shiftDay(b.latest,-6)],['← 前一天',shiftDay(selected,-1)],['後一天 →',shiftDay(selected,1)]].forEach(([label,day])=>{if(historyDateValid(day))shortcuts.append(historyLink(label,day))});
 $('history-heading').textContent=selected.replaceAll('-','/');
}
async function loadHistory(){
 historyChrome();const day=$('historyDate').value;const error=$('history-error');error.hidden=true;error.textContent='';
 const list=$('history-list');list.replaceChildren();const pagination=$('history-pagination');pagination.replaceChildren();$('history-empty').hidden=true;
 if(!config.apiBase){error.textContent='History 正式 API 尚未接通。';error.hidden=false;return}
 try{
  const data=await api('/v1/history?day='+encodeURIComponent(day)+'&limit=50&offset='+state.offset);
  if(!Array.isArray(data.items))throw Error('資料格式錯誤');
  data.items.forEach(item=>homeCard(item,list));
  const ids=new Set(data.items.map(item=>item.video_id));for(const id of selectedHomeVideos){if(!ids.has(id))selectedHomeVideos.delete(id)}homeSelection();
 const total=Number(data.total||0);if(!data.items.length)$('history-empty').hidden=false;
  const page=Math.floor(state.offset/50)+1;if(page>1)pagination.append(historyLink('上一頁',day,page-1));
  if(data.items.length&&((Number.isFinite(total)&&total>state.offset+data.items.length)||data.has_more===true))pagination.append(historyLink('下一頁',day,page+1));
 }catch(e){error.textContent='無法讀取歷史直播：'+e.message;error.hidden=false}
}
async function loadPtt(){if(!config.apiBase){message('ptt-status','PTT 正式 Worker API 尚未接通。');return}message('ptt-status','PTT 需要經來源驗證的文章識別碼與游標；不會混用不同專串。')}
document.querySelectorAll('[data-route]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.route)}));document.querySelectorAll('[data-mobile-route]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.mobileRoute)}));document.querySelectorAll('.rail-brand,.mobile-top-brand').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route('home')}));$('mobileNavButton').onclick=()=>{const opening=$('mobileNav').hidden;$('mobileNav').hidden=!opening;$('mobileNavButton').setAttribute('aria-expanded',String(opening))};$('multi-add').onclick=()=>{const id=videoId($('multi-url').value);if(!id)return alert('請輸入有效的 YouTube 網址或 ID');if(!state.multi.includes(id)&&state.multi.length<12)state.multi.push(id);renderMulti()};$('multi-clear').onclick=()=>{state.multi=[];renderMulti()};$('watch-add').onclick=()=>single(videoId($('watch-url').value),'watch-player');$('history-picker').onsubmit=event=>{event.preventDefault();state.offset=0;loadHistory()};$('historyDate').value=historyBounds().latest;renderMulti();route(location.hash.substring(1)||'home');

/* Accepted 4174 custom-view selection controller with public read-only catalog adapter. */
(function(){

const items=[];const list=document.getElementById('list');const input=document.getElementById('url');
const streamMetadata=new Map([...document.querySelectorAll('[data-live-pick]')].map(b=>[b.dataset.livePick,{channel:b.dataset.channel||b.dataset.livePick,title:b.dataset.title||'',avatar:b.dataset.avatar||''}]));
function streamLabel(id){const m=streamMetadata.get(id);return m?(m.channel+(m.title?' · '+m.title:'')):id;}
const primary=document.getElementById('primary'),audio=document.getElementById('audio'),count=document.getElementById('selectedCount');
let primaryId=null,audioId=null,dragId=null;
function moveStream(from,to){
  if(from===to||from<0||to<0||from>=items.length||to>=items.length)return;
  const [item]=items.splice(from,1);items.splice(to,0,item);render();
}
function render(){
  list.replaceChildren();count.textContent=String(items.length);
  if(primaryId!==null&&!items.includes(primaryId))primaryId=items[0]||null;
  if(audioId!==null&&!items.includes(audioId))audioId=items[0]||null;
  if(primaryId===null)primaryId=items[0]||null;
  if(audioId===null)audioId=items[0]||null;
  if(!items.length){const e=document.createElement('div');e.className='empty-selection';e.textContent='尚未加入影片';list.appendChild(e);}
  items.forEach((value,index)=>{
    const row=document.createElement('div');row.className='selected-item';row.draggable=true;row.dataset.video=value;
    if(value===primaryId)row.classList.add('is-primary');
    const grip=document.createElement('button');grip.type='button';grip.className='drag-handle';grip.textContent='⠿';grip.title='拖曳排序；也可使用 Alt 加上下方向鍵';grip.setAttribute('aria-label','拖曳或鍵盤排序 '+value);
    grip.onkeydown=e=>{if(e.altKey&&(e.key==='ArrowUp'||e.key==='ArrowDown')){e.preventDefault();moveStream(index,index+(e.key==='ArrowUp'?-1:1));}};
    const metadata=streamMetadata.get(value);
    const avatar=document.createElement('img');avatar.className='selected-avatar';avatar.alt='';avatar.loading='lazy';avatar.src=metadata?.avatar||'/favicon.ico';avatar.onerror=()=>{avatar.onerror=null;avatar.style.visibility='hidden';};
    const name=document.createElement('div');name.className='selected-name';
    const channel=document.createElement('span');channel.className='selected-channel';channel.textContent=(index+1)+' · '+(metadata?.channel||value);
    const title=document.createElement('span');title.className='selected-title';title.textContent=metadata?.title||'';name.title=streamLabel(value);name.append(channel,title);
    const choice=document.createElement('label');choice.className='primary-choice';
    const radio=document.createElement('input');radio.type='radio';radio.name='mainVideo';radio.value=value;radio.checked=value===primaryId;radio.setAttribute('aria-label','設為主視角 '+value);
    radio.onchange=()=>{primaryId=value;render();};
    const label=document.createElement('span');label.textContent=radio.checked?'主視角':'設為主視角';choice.append(radio,label);
    const actions=document.createElement('div');actions.className='item-actions';
    [['↑',-1],['↓',1]].forEach(([label,delta])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.title=delta<0?'往前':'往後';b.onclick=()=>moveStream(index,index+delta);actions.appendChild(b);});
    const rm=document.createElement('button');rm.type='button';rm.textContent='×';rm.title='移除';rm.onclick=()=>{items.splice(index,1);render();};actions.appendChild(rm);
    row.addEventListener('dragstart',e=>{dragId=value;row.classList.add('dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',value);});
    row.addEventListener('dragover',e=>{e.preventDefault();row.classList.add('drag-over');});
    row.addEventListener('dragleave',()=>row.classList.remove('drag-over'));
    row.addEventListener('drop',e=>{e.preventDefault();row.classList.remove('drag-over');if(dragId!==null)moveStream(items.indexOf(dragId),items.indexOf(value));});
    row.addEventListener('dragend',()=>{dragId=null;list.querySelectorAll('.selected-item').forEach(r=>r.classList.remove('dragging','drag-over'));});
    row.append(grip,avatar,name,choice,actions);list.appendChild(row);
  });
  document.querySelectorAll('[data-live-pick]').forEach(button=>button.setAttribute('aria-pressed',String(items.includes(button.dataset.livePick))));
  const multiview=items.length>1;
  document.getElementById('layoutControl').hidden=!multiview;
  document.getElementById('layout').disabled=!multiview;
  if(!multiview)document.getElementById('layout').value='auto';
  primary.replaceChildren();audio.replaceChildren();
  items.forEach((value,index)=>{
    for(const select of [primary,audio]){const o=document.createElement('option');o.value=String(index);o.textContent=(index+1)+' · '+streamLabel(value);select.appendChild(o);}
  });
  primary.disabled=!items.length;audio.disabled=!items.length;
  primary.value=String(Math.max(0,items.indexOf(primaryId)));
  audio.value=String(Math.max(0,items.indexOf(audioId)));
}
function addStream(value){const id=videoId(String(value||''));if(!id){const error=document.getElementById('custom-error');error.textContent='請提供有效的 YouTube 直播或影片連結。';error.hidden=false;return}if(items.includes(id))return;document.getElementById('custom-error').hidden=true;items.push(id);render();}
document.getElementById('custom-live-picker').addEventListener('click',event=>{
 const button=event.target.closest('[data-live-pick]');if(!button)return;
 if(event.target.closest('[data-youtube-href]')){event.preventDefault();event.stopPropagation();window.open('https://www.youtube.com/watch?v='+button.dataset.livePick,'_blank','noopener,noreferrer');return}
 const value=button.dataset.livePick;if(items.includes(value))items.splice(items.indexOf(value),1);else addStream(value);render();
});
document.getElementById('custom-live-picker').addEventListener('keydown',event=>{
 if(event.key!=='Enter'&&event.key!==' ')return;
 const button=event.target.closest('[data-live-pick]');if(!button)return;
 event.preventDefault();event.stopPropagation();
 if(event.target.closest('[data-youtube-href]')){window.open('https://www.youtube.com/watch?v='+button.dataset.livePick,'_blank','noopener,noreferrer');return}
 button.click();
});
document.querySelectorAll('[data-library-tab]').forEach(tab=>tab.addEventListener('click',()=>{
  const history=tab.dataset.libraryTab==='history';
  document.querySelectorAll('[data-library-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===tab)));
  document.getElementById('liveLibrary').hidden=history;
  document.getElementById('historyLibrary').hidden=!history;
}));
document.getElementById('displayMode').onclick=()=>{
  const gallery=document.querySelector('.live-picker-list');if(!gallery)return;
  gallery.classList.toggle('compact');document.getElementById('displayMode').textContent=gallery.classList.contains('compact')?'詳細卡片':'精簡列表';
};
audio.addEventListener('change',()=>{audioId=items[Number(audio.value)]||null;});
document.getElementById('add').onclick=()=>{const value=input.value.trim();if(!value)return;addStream(value);input.value='';input.focus();};
input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();document.getElementById('add').click();}});
document.getElementById('start').onclick=()=>{
  if(!items.length){alert('請先加入至少一個影片。');return;}
  const q=new URLSearchParams();items.forEach(v=>q.append('stream',v));
  q.set('layout',items.length===1?'auto':document.getElementById('layout').value);
  q.set('ptt',document.getElementById('pttMode').value);
  q.set('primary',String(Math.max(0,items.indexOf(primaryId))));
  q.set('audio',String(Math.max(0,items.indexOf(audioId))));
  window.hvOpenCustomSession?.(items.slice(),{layout:q.get('layout'),ptt:q.get('ptt'),primary:Number(q.get('primary')),audio:Number(q.get('audio'))});
};
render();

window.hvCustomCatalog=function(rows){
 const box=document.getElementById('custom-live-picker');box.replaceChildren();streamMetadata.clear();
 for(const row of rows){
  const id=String(row?.video_id||'');if(!/^[A-Za-z0-9_-]{11}$/.test(id))continue;
  const channel=String(row.channel_title||row.channel_name||'Hololive');const title=String(row.title||id);
  const avatar=String(row.avatar_url||'');streamMetadata.set(id,{channel,title,avatar:/^https:\/\/(yt3\.ggpht\.com|i\.ytimg\.com)\//.test(avatar)?avatar:''});
  const card=node('div',undefined,'live-picker-item');card.setAttribute('role','button');card.tabIndex=0;card.dataset.livePick=id;card.setAttribute('aria-pressed',String(items.includes(id)));
  const cover=node('div');cover.style.position='relative';const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';cover.append(img);
  const source=node('span','YouTube ↗','youtube-source-link');source.setAttribute('role','link');source.tabIndex=0;source.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;cover.append(source);card.append(cover);
  const label=node('span');const strong=node('strong',channel);label.append(strong,document.createTextNode(' · '+title));card.append(label);box.append(card);
 }
 document.getElementById('custom-live-empty').hidden=box.childElementCount>0;
 render();
};
window.hvCustomAdd=addStream;

})();
