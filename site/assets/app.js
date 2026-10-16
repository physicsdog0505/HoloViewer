'use strict';
const config=window.HOLOVIEWER_CONFIG||{};
const $=id=>document.getElementById(id);
const names={home:'今日直播',single:'自訂觀看',multi:'多人連動',history:'歷史直播',ptt:'PTT 今日專串',watchalong:'同時視聽','watchalong-session':'同時視聽','custom-session':'自訂觀看','ptt-focus':'PTT 今日專串'};
const state={offset:0};
function node(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el}
function message(target,text){const box=$(target);box.replaceChildren(node('div',text,'notice'))}
function videoId(input){let t=input.trim();if(/^[\w-]{11}$/.test(t))return t;try{const u=new URL(t);if(!['youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be'].includes(u.hostname))return null;t=u.hostname.includes('youtu.be')?u.pathname.split('/')[1]:u.pathname==='/watch'?u.searchParams.get('v'):['live','embed','shorts'].includes(u.pathname.split('/')[1])?u.pathname.split('/')[2]:null;return /^[\w-]{11}$/.test(t||'')?t:null}catch{return null}}
function youtubeEmbedUrl(id){
 const url=new URL('https://www.youtube-nocookie.com/embed/'+encodeURIComponent(id));
 url.searchParams.set('enablejsapi','1');
 // Tie iframe API commands to this Public site; never copy a fixed test origin.
 if(/^https?:$/.test(window.location.protocol))url.searchParams.set('origin',window.location.origin);
 return url.toString();
}
function frame(id){const f=document.createElement('iframe');f.className='frame';f.title='YouTube player '+id;f.src=youtubeEmbedUrl(id);f.allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';f.referrerPolicy='strict-origin-when-cross-origin';f.allowFullscreen=true;return f}
function single(id,target='single-player'){if(!id){if($(target))message(target,'請輸入有效的 YouTube 網址或影片 ID。');return}if(!$(target)){openViewingDocument([id],{layout:'auto',primary:0,audio:0});return}$(target).replaceChildren(frame(id))}
function viewingSessionUrl(ids,opts={}){
 const clean=[...new Set((ids||[]).map(id=>videoId(String(id||''))).filter(Boolean))];
 if(!clean.length)return '/custom-view';
 const q=new URLSearchParams();
 clean.forEach(id=>q.append('stream',id));
 q.set('layout',['auto','equal','primary'].includes(opts.layout)?opts.layout:'auto');
 q.set('primary',String(Math.max(0,Number(opts.primary)||0)));
 q.set('audio',String(Math.max(0,Number(opts.audio)||0)));
 if(opts.ptt==='video')q.set('ptt','video');
 if(opts.eventId)q.set('event',String(opts.eventId));
 return '/custom-view/session?'+q.toString();
}
function openViewingDocument(ids,opts={}){
 location.href=viewingSessionUrl(ids,opts);
}

/* 4174 client_home._english_home_date: %a · %b %d, %Y, uppercase. */
function clientTopbarDate(day){
 if(!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(day||''))return '';
 const date=new Date(day+'T12:00:00Z');
 if(!Number.isFinite(date.getTime()))return '';
 const pieces=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',weekday:'short',month:'short',day:'2-digit',year:'numeric'}).formatToParts(date);
 const parts=Object.fromEntries(pieces.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return (parts.weekday+' · '+parts.month+' '+parts.day+', '+parts.year).toUpperCase();
}
function updateClientTopbar(routeName){
 const label=routeName==='home'?clientTopbarDate(taipeiDay()):
  routeName==='history'?clientTopbarDate($('historyDate').value||historyBounds().latest):'';
 $('page-title').textContent=label;
}


let currentRoute='home';
function route(r){
 r=String(r||'').split('?')[0];
 if(!names[r])r='home';
 // A viewing route without valid stream IDs must never display an empty workspace.
 if(r==='custom-session'&&!viewing.ids.length){
  const params=location.pathname==='/custom-view/session'?new URLSearchParams(location.search):new URLSearchParams();
  const recoverable=params.getAll('stream').some(id=>/^[A-Za-z0-9_-]{11}$/.test(id));
  if(!recoverable)r='single';
 }
 if(r!==currentRoute&&['home','history'].includes(currentRoute)){
  selectedHomeVideos.clear();
  homeSelection();
 }
 if(currentRoute==='custom-session'&&r!=='custom-session'){
  window.hvDestroy4174SharedViewer?.();
 }
 currentRoute=r;
 const pageId=r==='ptt-focus'?'ptt':r;
 document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id===pageId));
 const activeNav=r==='custom-session'?'single':r==='watchalong-session'?'watchalong':pageId;
 document.querySelectorAll('[data-route]').forEach(el=>el.classList.toggle('active',el.dataset.route===activeNav));
 document.querySelectorAll('[data-mobile-route]').forEach(el=>el.classList.toggle('active',el.dataset.mobileRoute===activeNav));
 updateClientTopbar(r);$('mobileNav').hidden=true;$('mobileNavButton').setAttribute('aria-expanded','false');
 const viewerActive=r==='custom-session';
 if(!viewerActive)window.hvStopFocusCarousel?.();
 $('viewer-4174-css').media='not all';
 const transplantCss=document.getElementById('viewer-4174-transplant-css');
 if(transplantCss)transplantCss.media=viewerActive?'all':'not all';
 document.body.classList.toggle('custom-session-watching',viewerActive);
 if(!viewerActive&&document.body.classList.contains('custom-immersive')){
  window.hvExit4174Immersive?.();
 }
 document.body.classList.toggle('home-wide',r==='home'||r==='history');
 document.body.classList.toggle('ptt-focus-mode',r==='ptt-focus');
 document.body.classList.toggle('watchalong-wide',r==='watchalong');
 $('ptt-focus').textContent=r==='ptt-focus'?'退出專注':'⛶ 專注模式';
 $('ptt-floor-toggle').hidden=r!=='ptt-focus';
 $('live-channel-rail').hidden=!['home','custom-session'].includes(r)||!$('live-channel-list').childElementCount;
 if(r==='home'||r==='custom-session')loadHome();
 if(r==='history')loadHistory();
 if(r==='ptt'||r==='ptt-focus')loadPtt();
 if(r==='single')loadCustomLibrary();
 if(r==='multi')loadCollab();
 if(r==='watchalong')loadWatchalongRecent();
}
async function api(path){if(!config.apiBase||!/^https:\/\//.test(config.apiBase))throw Error('尚未設定正式 Worker API');const base=config.apiBase.replace(/\/$/,'');const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});if(!response.ok)throw Error('API HTTP '+response.status);return response.json()}
function catalogCard(item,container){if(!item||! /^[\w-]{11}$/.test(item.video_id||''))return;const card=node('div',undefined,'card');card.append(node('strong',String(item.title||item.video_id)));card.append(node('p',String(item.channel_name||item.lifecycle_state||''),'sub'));const btn=node('button','單人觀看');btn.onclick=()=>openViewingDocument([item.video_id],{layout:'auto',primary:0,audio:0});card.append(btn);container.append(card)}
const HOME_FILTER_KEY='holoviewer-live-filter';
const HOME_FILTERS=new Set(['hololive','holostars','mekpark','all']);
const selectedHomeVideos=new Set();
function homeFilter(){try{const x=localStorage.getItem(HOME_FILTER_KEY);return HOME_FILTERS.has(x)?x:'hololive'}catch{return 'hololive'}}
function setHomeFilter(value){if(!HOME_FILTERS.has(value))return;try{localStorage.setItem(HOME_FILTER_KEY,value)}catch{}applyHomeFilter(value)}
function applyHomeFilter(value=homeFilter()){
 document.querySelectorAll('#homeDynamic .stream-card').forEach(card=>{card.hidden=value!=='all'&&card.dataset.group!==value});
 document.querySelectorAll('#live-channel-list .live-channel-rail-item').forEach(card=>{card.hidden=(value!=='all'&&card.dataset.group!==value)||(watchMode==='multi'&&viewing.ids.includes(card.dataset.liveVideoId))});
 document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.classList.toggle('active',button.dataset.filter===value));
}
function selectedHomePttMode(){
 const cards=[...selectedHomeVideos].map(id=>document.querySelector('#homeDynamic .stream-card[data-multiview-id="'+id+'"],#historyDynamic .stream-card[data-multiview-id="'+id+'"]')).filter(Boolean);
 if(!cards.length)return 'video';
 return cards.every(card=>card.closest('#historyDynamic')===null) ? 'live' : 'video';
}
function homeSelection(){
 document.querySelectorAll('#homeDynamic .stream-card[data-multiview-id],#historyDynamic .stream-card[data-multiview-id]').forEach(card=>{const on=selectedHomeVideos.has(card.dataset.multiviewId);card.classList.toggle('multi-selected',on);card.setAttribute('aria-selected',String(on))});
 const count=selectedHomeVideos.size;for(const [bar,countEl,watch] of [['multiSelectBar','multiSelectCount','multiWatch'],['historyMultiSelectBar','historyMultiSelectCount','historyMultiWatch']]){
  $(bar).hidden=!count;$(countEl).textContent='已選 '+count+' 個影片';$(watch).textContent=count>1?'開始多視角觀看':'觀看選取影片';
 }
}

/* Fallback member accents from pinned 4174 client_home._CHANNEL_ACCENT_RULES.
   Audited member-ID palette should override when the reviewed Public schema exists. */
const HOME_CHANNEL_ACCENTS=[
 [["ロボ子", "ROBOCO"], '#d85a8a'],
 [["ときのそら", "TOKINO SORA"], '#397fc4'],
 [["AZKI",], '#c94a52'],
 [["さくらみこ", "SAKURA MIKO"], '#dc6f9f'],
 [["アキ・ローゼンタール", "AKI ROSENTHAL"], '#69a56f'],
 [["白上フブキ", "SHIRAKAMI FUBUKI"], '#4b97c8'],
 [["夏色まつり", "NATSUIRO MATSURI"], '#d87932'],
 [["百鬼あやめ", "NAKIRI AYAME"], '#c84b55'],
 [["癒月ちょこ", "YUZUKI CHOCO", "CHOCO CH."], '#d85a8a'],
 [["大空スバル", "OOZORA SUBARU"], '#a68118'],
 [["大神ミオ", "OOKAMI MIO"], '#69a56f'],
 [["兎田ぺこら", "USADA PEKORA"], '#4b97c8'],
 [["不知火フレア", "SHIRANUI FLARE"], '#d87932'],
 [["白銀ノエル", "SHIROGANE NOEL"], '#7d7d7d'],
 [["宝鐘マリン", "HOUSHOU MARINE"], '#c84b55'],
 [["天音かなた", "AMANE KANATA"], '#4b97c8'],
 [["常闇トワ", "TOKOYAMI TOWA"], '#7751a8'],
 [["雪花ラミィ", "YUKIHANA LAMY"], '#4b97c8'],
 [["獅白ぼたん", "SHISHIRO BOTAN"], '#7d7d7d'],
 [["尾丸ポルカ", "OMARU POLKA"], '#c84b55']
];
function homeChannelAccent(item){
 const audited=String(item.member_accent||'');
 if(/^#[0-9a-fA-F]{6}$/.test(audited))return audited;
 const mode=String(item?.support_mode||'');
 // Accepted 4174 semantics: an explicit audited neutral row stays neutral.
 // Name fallback is only for payloads that do not expose support_mode at all.
 if(mode==='neutral'||mode==='solid'||mode==='dual_color')return '';
 const title=String(item.channel_title||item.channel_name||'').toUpperCase();
 for(const [needles,accent] of HOME_CHANNEL_ACCENTS)if(needles.some(word=>title.includes(word.toUpperCase())))return accent;
 return '';
}
function applyHomeSupportStyle(el,item){
 const accent=homeChannelAccent(item);
 if(accent){el.style.setProperty('--member-accent',accent);el.dataset.supportAccent='1'}
 const dual=Array.isArray(item?.member_accent_dual)?item.member_accent_dual:[];
 const validDual=dual.length===2&&dual.every(value=>/^#[0-9a-fA-F]{6}$/.test(String(value)));
 const mode=String(item?.support_mode||'');
 if(mode==='dual_color'&&validDual){
  el.dataset.supportMode='dual_color';
  el.style.setProperty('--member-accent',String(dual[0]));
  el.style.setProperty('--member-accent-secondary',String(dual[1]));
  el.style.setProperty('--member-accent-dual','linear-gradient(135deg,'+dual[0]+' 0 50%,'+dual[1]+' 50% 100%)');
 }else if(accent){
  el.dataset.supportMode=mode==='neutral'?'neutral':'solid';
 }
}
function homeStartLabel(item){
 const legacy=String(item?.start_label||item?.start_time_label||'').trim();
 if(legacy)return legacy;
 const raw=String(item?.start_at||'').trim();
 if(!raw)return '時間未明';
 const date=new Date(raw);
 if(!Number.isFinite(date.getTime()))return '時間未明';
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
 const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return out.month+'/'+out.day+' '+out.hour+':'+out.minute;
}
function homeAvatarUrl(item){
 const raw=String(item.avatar_url||'');
 try{
  const u=new URL(raw);
  if(u.protocol!=='https:'||u.username||u.password||u.port)return '';
  return ['yt3.ggpht.com','i.ytimg.com'].includes(u.hostname)?u.href:'';
 }catch{return ''}
}
function homeAvatarChild(item,name){
 const url=homeAvatarUrl(item);
 if(url){const img=node('img',undefined,'channel-avatar-img');img.src=url;img.alt='';img.loading='lazy';return img}
 const first=[...name].find(c=>/[a-zA-Z0-9]/.test(c))||'H';
 return node('span',first.toUpperCase(),'channel-avatar-fallback');
}

let homeCollabEvents=[],homeCollabByVideo=new Map();
function collabEventStreams(event){
 return Array.isArray(event?.streams)?event.streams.filter(x=>x&&/^[A-Za-z0-9_-]{11}$/.test(String(x.video_id||''))):[];
}
function setHomeCollabEvents(data){
 const events=data?.schema_version==='public-experience-v1'&&data?.kind==='collab'&&Array.isArray(data.events)?data.events:[];
 homeCollabEvents=events.filter(event=>collabEventStreams(event).length>1);
 homeCollabByVideo=new Map();
 for(const event of homeCollabEvents)for(const stream of collabEventStreams(event))homeCollabByVideo.set(stream.video_id,event);
}
function openCollabEvent(event){
 const streams=collabEventStreams(event);
 const ids=streams.map(x=>x.video_id);
 if(ids.length<2)return;
 location.href=viewingSessionUrl(ids,{layout:'auto',ptt:'live',primary:0,audio:0,eventId:String(event.event_id||'')});
}
function collabEntry(event){
 const streams=collabEventStreams(event);
 if(streams.length<2)return null;
 const entry=node('span',undefined,'stream-collab-entry');
 entry.role='link';entry.tabIndex=0;entry.dataset.collabEventId=String(event.event_id||'');
 entry.setAttribute('aria-label','進入多人連動');entry.title='進入多人連動';
 entry.append(node('span','👥','collab-glyph'),node('span','多人','collab-entry-label'));
 entry.querySelector('.collab-glyph').setAttribute('aria-hidden','true');
 entry.onclick=e=>{e.preventDefault();e.stopPropagation();openCollabEvent(event)};
 entry.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();openCollabEvent(event)}};
 return entry;
}
function homeCard(item,container){
 if(!item||! /^[A-Za-z0-9_-]{11}$/.test(item.video_id||''))return;
 const id=item.video_id;const lifecycle=String(item.lifecycle_state||item.state||'unknown').toLowerCase();
 const group=String(item.group||item.channel_group||'other').toLowerCase();
 const href='/custom-view/session?stream='+encodeURIComponent(id)+'&layout=auto&primary=0&audio=0';
 const card=node('a',undefined,'client-card stream-card');card.href=href;card.dataset.group=group;card.id='stream-'+id;
 applyHomeSupportStyle(card,item);
 const states={live:['LIVE','live'],waiting:['等待中','upcoming'],upcoming:['即將開始','upcoming'],ended:['已結束','ended'],unknown:['狀態待更新',''],stale:['狀態待更新','']};
 const status=states[lifecycle]||states.unknown;
 if(['live','waiting','upcoming','ended'].includes(lifecycle)){card.dataset.multiviewId=id;card.setAttribute('aria-selected','false')}
 const thumb=node('div',undefined,'card-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
 const youTube=node('span','YouTube ↗','youtube-source-link');youTube.role='link';youTube.tabIndex=0;youTube.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;thumb.append(youTube);
 const overlay=node('div',undefined,'thumb-overlay');overlay.append(node('span',status[0],'thumb-badge '+status[1]));
 const time=homeStartLabel(item);overlay.append(node('span',time,'thumb-time'));thumb.append(overlay);card.append(thumb);
 const meta=node('div',undefined,'yt-meta');const ring=node('span',undefined,'channel-avatar-ring');const name=String(item.channel_title||item.channel_name||'頻道資訊待補');
 ring.append(homeAvatarChild(item,name));meta.append(ring);
 const copy=node('div',undefined,'yt-copy');copy.append(node('h3',String(item.title||id),'stream-title'));copy.append(node('div',name,'channel-name'));meta.append(copy);card.append(meta);
 const collab=homeCollabByVideo.get(id);const collabButton=collabEntry(collab);if(collabButton)card.append(collabButton);
 card.addEventListener('click',event=>{
  if(event.target.closest('.stream-collab-entry'))return;
  const source=event.target.closest('[data-youtube-href]');
  if(source){event.preventDefault();event.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer');return}
  event.preventDefault();if(!card.dataset.multiviewId){openViewingDocument([id],{layout:'auto',primary:0,audio:0,ptt:lifecycle==='ended'?'video':'live'});return}
  if(selectedHomeVideos.has(id))selectedHomeVideos.delete(id);else selectedHomeVideos.add(id);homeSelection()
 });
 card.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-youtube-href]')){event.preventDefault();event.stopPropagation();window.open(event.target.dataset.youtubeHref,'_blank','noopener,noreferrer')}});
 container.append(card);
}
function homeRail(items){const box=$('live-channel-list');box.replaceChildren();const seen=new Set();
 items.forEach(item=>{const id=item.video_id;if(!/^[A-Za-z0-9_-]{11}$/.test(id||''))return;const key=item.channel_id||item.channel_name||item.channel_title||id;if(seen.has(key))return;seen.add(key);
 const link=node('a',undefined,'live-channel-rail-item');link.href='#stream-'+id;link.dataset.liveVideoId=id;link.dataset.channelId=String(item.channel_id||'');link.dataset.group=String(item.group||item.channel_group||'other').toLowerCase();
 const avatar=node('span',undefined,'live-channel-avatar');const name=String(item.channel_title||item.channel_name||'頻道資訊待補');
 applyHomeSupportStyle(link,item);
 const avatarNode=homeAvatarChild(item,name);if(!avatarNode.matches('img'))avatarNode.className='';avatar.append(avatarNode);avatar.append(node('i'));link.append(avatar);link.append(node('strong',name));
 link.onclick=event=>{event.preventDefault();if($('custom-session').classList.contains('active')){selectWatchRailVideo(id,name);return}const card=$('stream-'+id);card?.scrollIntoView({block:'center',behavior:'smooth'})};box.append(link)});
 $('live-channel-rail').hidden=!box.children.length||(!$('home').classList.contains('active')&&!$('custom-session').classList.contains('active'));
 applyHomeFilter();refreshWatchRail();
}

/* Accepted 4174 high-signal carousel selection rules from pinned client_home.py. */
const HOME_HIGHLIGHT_RULES=[
 [120,'三期生告知',['3期生','三期生']],
 [105,'重大告知',['重大告知','重要告知','IMPORTANT ANNOUNCEMENT','BIG ANNOUNCEMENT']],
 [100,'初配信',['DEBUT','RE-DEBUT','初配信','デビュー']],
 [95,'周年',['ANNIVERSARY','周年','記念配信']],
 [92,'新衣裝',['NEW OUTFIT','OUTFIT REVEAL','新衣装','新衣裝','衣装お披露目','新衣装お披露目']],
 [90,'生日',['誕生日','BIRTHDAY','生日']],
 [85,'3D LIVE',['3D LIVE','3DLIVE','3Dライブ']],
 [75,'大型聯動',['大型コラボ','大型聯動','COLLAB','コラボ']],
 [65,'歌回',['歌枠','歌回','KARAOKE','SINGING STREAM','SINGING']],
 [60,'新造型',['NEW HAIRSTYLE','髪型お披露目','NEW MODEL','MODEL REVEAL','LIVE2D']]
];
function homeHighlightMatch(item){
 const title=String(item.title||'')+' '+String(item.source_label||'');
 const upper=title.toUpperCase();let bestScore=0,bestLabel='';
 for(const [score,label,keys] of HOME_HIGHLIGHT_RULES){
  let found=keys.some(x=>upper.includes(x.toUpperCase()));
  if(label==='三期生告知')found=found&&['告知','重大','終了','結束','ANNOUNCEMENT'].some(x=>upper.includes(x));
  if(found&&score>bestScore){bestScore=score;bestLabel=label}
 }
 if(bestScore&&String(item.lifecycle_state||item.state||'').toLowerCase()==='live')bestScore+=5;
 return {score:bestScore,label:bestLabel};
}
function chooseHomeHighlights(rows){
 const seen=new Set();const candidates=[];
 for(const row of rows){
  const id=String(row?.video_id||'');
  if(!/^[A-Za-z0-9_-]{11}$/.test(id)||seen.has(id))continue;
  seen.add(id);
  const state=String(row.lifecycle_state||row.state||'').toLowerCase();
  if(!['live','waiting','upcoming'].includes(state))continue;
  const match=homeHighlightMatch(row);
  if(match.score)candidates.push({row,label:match.label,score:match.score});
 }
 candidates.sort((a,b)=>b.score-a.score||String(a.row.video_id).localeCompare(String(b.row.video_id)));
 // Public does not currently expose verified collab-candidate IDs; dedupe by
 // video ID only, never invent shared event identity from titles or dates.
 return candidates.slice(0,6);
}
function renderHomeHighlights(rows){
 const picks=chooseHomeHighlights(rows);
 const highlights=$('home-highlights'),announcement=$('home-announcements');
 highlights.replaceChildren();announcement.replaceChildren();
 const announce=picks.filter(x=>['生日','重大告知','三期生告知'].includes(x.label));
 if(announce.length){
  const aside=node('aside',undefined,'home-announcements');aside.setAttribute('aria-label','生日及重要直播消息');
  aside.append(node('span','📣 最新提醒','announcement-heading'));
  const messages=node('div',undefined,'announcement-messages');
  messages.dataset.announcementCount=String(announce.length);
  const track=node('div',undefined,'announcement-track');
  announce.forEach((pick,i)=>{
   const message=node('span',undefined,'announcement-entry');message.dataset.announcementIndex=String(i);message.hidden=i!==0;
   const link=node('a');link.href='/custom-view/session?stream='+encodeURIComponent(pick.row.video_id);
   link.append(node('strong',pick.label),document.createTextNode(' · '+String(pick.row.channel_title||pick.row.channel_name||'Hololive')+'：'+String(pick.row.title||'')));
   link.onclick=e=>{e.preventDefault();openViewingDocument([pick.row.video_id],{layout:'auto',ptt:'live',primary:0,audio:0})};
   message.append(link);track.append(message);
  });
  messages.append(track);aside.append(messages);announcement.append(aside);
 }
 if(!picks.length)return;
 const section=node('section',undefined,'section highlight-section');
 const heading=node('div',undefined,'section-head');const title=node('div');title.append(node('h2','近期焦點'));heading.append(title);section.append(heading);
 const carousel=node('div',undefined,'highlight-carousel');carousel.setAttribute('aria-label','近期焦點輪播');carousel.dataset.activeSlide='0';
 picks.forEach((pick,i)=>{
  const row=pick.row,id=row.video_id;const state=String(row.lifecycle_state||row.state||'').toLowerCase();
  const slide=node('div',undefined,'highlight-slide');slide.dataset.slide=String(i);slide.hidden=i!==0;
  const card=node('a',undefined,'home-highlight');card.href='/custom-view/session?stream='+encodeURIComponent(id);
  card.onclick=e=>{if(e.target.closest('[data-youtube-href]'))return;e.preventDefault();openViewingDocument([id],{layout:'auto',primary:0,audio:0})};
  const thumb=node('div',undefined,'highlight-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/hqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
  const source=node('span','YouTube ↗','youtube-source-link');source.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;source.setAttribute('role','link');source.tabIndex=0;
  source.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')});
  source.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')}});
  thumb.append(source);card.append(thumb);
  const copy=node('div',undefined,'highlight-copy');const badges=node('div',undefined,'highlight-badges');
  badges.append(node('span',pick.label,'highlight-type'));
  badges.append(node('span',state==='live'?'LIVE':state==='ended'?'已結束':'即將開始','highlight-state'+(state==='live'?' is-live':'')));
  copy.append(badges);copy.append(node('h3',String(row.title||id)));
  copy.append(node('p',String(row.channel_title||row.channel_name||'頻道資訊待補')+' · '+String(row.start_label||''),'highlight-channel'));
  copy.append(node('span','前往觀看 →','highlight-cta'));card.append(copy);slide.append(card);carousel.append(slide);
 });
 if(picks.length>1){
  const controls=node('div',undefined,'highlight-controls');
  const prev=node('button','‹','highlight-prev');prev.type='button';prev.setAttribute('aria-label','上一則重點');
  const dots=node('div',undefined,'highlight-dots');
  const next=node('button','›','highlight-next');next.type='button';next.setAttribute('aria-label','下一則重點');
  const show=index=>{
   const n=(index+picks.length)%picks.length;carousel.dataset.activeSlide=String(n);
   carousel.querySelectorAll('.highlight-slide').forEach((el,i)=>el.hidden=i!==n);
   carousel.querySelectorAll('.highlight-dot').forEach((el,i)=>el.classList.toggle('active',i===n));
  };
  picks.forEach((_,i)=>{const dot=node('button',undefined,'highlight-dot'+(i===0?' active':''));dot.type='button';dot.dataset.slideTo=String(i);dot.setAttribute('aria-label','顯示第 '+(i+1)+' 則重點');dot.onclick=()=>show(i);dots.append(dot)});
  prev.onclick=()=>show(Number(carousel.dataset.activeSlide||0)-1);
  next.onclick=()=>show(Number(carousel.dataset.activeSlide||0)+1);
  controls.append(prev,dots,next);carousel.append(controls);
 }
 section.append(carousel);highlights.append(section);
}

let homeLoadInFlight=false;
async function loadHome(){
 if(homeLoadInFlight)return;
 if(!config.apiBase){$('home-empty').textContent='正式直播資料 API 尚未接通。';return}
 homeLoadInFlight=true;
 try{
 const [data,collabData]=await Promise.all([
  api('/v1/catalog/today'),
  api('/v1/collab/live').catch(()=>null)
 ]);
 const rows=data.streams||data.items;
 if(!Array.isArray(rows))throw Error('資料格式錯誤');
 setHomeCollabEvents(collabData);
 customCatalogCache=rows;
 window.hvCustomCatalog?.(rows);
 const buckets={live:[],upcoming:[],unknown:[],ended:[]};
 rows.forEach(item=>{const state=String(item.lifecycle_state||item.state||'unknown').toLowerCase();const bucket=state==='live'?'live':['waiting','upcoming'].includes(state)?'upcoming':state==='ended'?'ended':'unknown';buckets[bucket].push(item)});
 for(const key of Object.keys(buckets)){const el=$('home-'+key);el.replaceChildren();buckets[key].forEach(item=>homeCard(item,el));$('home-'+key+'-section').hidden=!el.children.length}
 const allowed=new Set(rows.map(item=>item.video_id));for(const id of selectedHomeVideos){if(!allowed.has(id))selectedHomeVideos.delete(id)}
 homeSelection();homeRail(buckets.live);renderHomeHighlights(rows);applyHomeFilter();
 $('home-empty').textContent=rows.length?'':'目前沒有今天的直播資料。';
 $('connection').textContent='API 已連線';
 }catch(e){$('home-empty').textContent='無法讀取正式直播資料：'+e.message}
 finally{homeLoadInFlight=false}
}
function taipeiDay(){const p=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const o=Object.fromEntries(p.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));return o.year+'-'+o.month+'-'+o.day}
function shiftDay(day,delta){const date=new Date(day+'T00:00:00Z');date.setUTCDate(date.getUTCDate()+delta);return date.toISOString().slice(0,10)}
function historyBounds(){const today=taipeiDay();return {earliest:shiftDay(today,-30),latest:shiftDay(today,-1)}}
function historyDateValid(day){const b=historyBounds();return /^\\d{4}-\\d{2}-\\d{2}$/.test(day)&&day>=b.earliest&&day<=b.latest}
function historyLink(label,day,page=1){const link=node('a',label,'subtle-action');link.href='/history?date='+encodeURIComponent(day)+(page>1?'&page='+page:'');return link}
function historyChrome(){const b=historyBounds();const input=$('historyDate');input.min=b.earliest;input.max=b.latest;if(!historyDateValid(input.value)){input.value=b.latest;state.offset=0}
 const selected=input.value;const shortcuts=$('history-shortcuts');shortcuts.replaceChildren();
 [['昨天',b.latest],['前天',shiftDay(b.latest,-1)],['7 天前',shiftDay(b.latest,-6)],['← 前一天',shiftDay(selected,-1)],['後一天 →',shiftDay(selected,1)]].forEach(([label,day])=>{if(historyDateValid(day))shortcuts.append(historyLink(label,day))});
 $('history-heading').textContent=selected.replaceAll('-','/');
 if($('history').classList.contains('active'))updateClientTopbar('history');
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
function collabEventState(event){
 const streams=collabEventStreams(event);
 if(streams.some(x=>x.lifecycle_state==='live'))return 'live';
 if(streams.some(x=>x.lifecycle_state==='upcoming'))return 'upcoming';
 return 'ended';
}
function collabEventCard(event){
 const streams=collabEventStreams(event);if(streams.length<2)return null;
 const members=streams.slice().sort((a,b)=>{
  const at=Date.parse(a.actual_start||a.scheduled_start||a.start_at||'1970-01-01T00:00:00Z');
  const bt=Date.parse(b.actual_start||b.scheduled_start||b.start_at||'1970-01-01T00:00:00Z');
  return at-bt||String(a.video_id).localeCompare(String(b.video_id));
 });
 const representative=members[0],live=members.filter(x=>x.lifecycle_state==='live').length;
 const upcoming=members.filter(x=>['upcoming','waiting'].includes(x.lifecycle_state)).length;
 const ended=members.filter(x=>x.lifecycle_state==='ended').length;
 const state=live?'live':upcoming?'upcoming':'ended',stateLabel=state==='live'?'LIVE':state==='upcoming'?'稍後':'已結束';
 const eventTimes=members.map(x=>Date.parse(x.actual_start||x.scheduled_start||x.start_at||'')).filter(Number.isFinite);
 const eventAt=eventTimes.length?Math.max(...eventTimes):NaN;
 const dateLabel=Number.isFinite(eventAt)?new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(eventAt)):'日期未明';
 const card=node('a',undefined,'collab-event-card '+state);card.href=viewingSessionUrl(members.map(x=>x.video_id),{layout:'auto',primary:0,audio:0,eventId:String(event.event_id||'')});
 card.dataset.eventDate=dateLabel;
 card.onclick=e=>{if(e.target.closest('[data-youtube-href]'))return;e.preventDefault();openCollabEvent(event)};
 const thumb=node('div',undefined,'collab-event-thumb'),img=node('img');img.src='https://i.ytimg.com/vi/'+representative.video_id+'/hqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
 const source=node('span','YouTube ↗','youtube-source-link');source.role='link';source.tabIndex=0;source.dataset.youtubeHref='https://www.youtube.com/watch?v='+representative.video_id;
 source.onclick=e=>{e.preventDefault();e.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')};
 source.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')}};
 thumb.append(source,node('span',stateLabel,'status-pill '+state));card.append(thumb);
 const copy=node('div',undefined,'collab-event-copy'),kicker=node('div',undefined,'collab-event-kicker');
 kicker.append(node('span',dateLabel),node('span',String(event.confidence||'candidate')));copy.append(kicker);
 copy.append(node('h3',String(event.label||'多人連動').replace(/候選/g,'').replace(/^[ ·]+|[ ·]+$/g,'')||'多人連動'));
 const avatars=node('div',undefined,'collab-avatars'),seen=new Set();
 for(const item of members){
  const channel=String(item.channel_id||item.channel_name||item.channel_title||item.video_id);if(seen.has(channel))continue;seen.add(channel);
  const name=String(item.channel_title||item.channel_name||'Hololive'),avatar=node('span',undefined,'collab-avatar');avatar.title=name;
  const url=homeAvatarUrl(item);if(url){const av=node('img');av.src=url;av.alt=name;av.loading='lazy';avatar.append(av)}else{const fallback=[...name].find(ch=>/[A-Za-z0-9]/.test(ch))||'H';avatar.append(node('span',fallback.toUpperCase()))}
  avatars.append(avatar);
 }
 copy.append(avatars);
 const bits=[];if(live)bits.push(live+' 個直播中');if(upcoming)bits.push(upcoming+' 個稍後開始');if(ended)bits.push(ended+' 個已結束');
 copy.append(node('p',members.length+' 個 POV'+(bits.length?' · '+bits.join(' · '):'')+' · 進入多人連動畫面'));
 card.append(copy);return card;
}
async function loadCollab(){
 for(const id of ['collab-live','collab-upcoming','collab-ended']){
  const section=$(id);section.hidden=true;section.querySelector('.collab-event-grid').replaceChildren();
 }
 $('collab-empty').hidden=false;$('collab-empty').textContent='讀取多人連動中…';
 try{
  const data=await api('/v1/collab/live');
  setHomeCollabEvents(data);
  const buckets={live:[],upcoming:[],ended:[]};
  for(const event of homeCollabEvents)buckets[collabEventState(event)].push(event);
  for(const [state,events] of Object.entries(buckets)){
   const section=$('collab-'+state),grid=section.querySelector('.collab-event-grid');
   for(const event of events){const card=collabEventCard(event);if(card)grid.append(card)}
   section.hidden=!grid.children.length;
  }
  $('collab-empty').hidden=homeCollabEvents.length>0;
  if(!homeCollabEvents.length)$('collab-empty').textContent='目前沒有偵測到可用的多人連動。';
 }catch(e){
  $('collab-empty').hidden=false;$('collab-empty').textContent='多人連動資料暫時無法讀取。';
 }
}

let watchalongRecentInFlight=false;
async function loadWatchalongRecent(){
 if(watchalongRecentInFlight)return;
 const grid=$('recentWatchGrid'),empty=$('recentWatchEmpty'),noMatches=$('recentWatchNoMatches');
 if(!grid||!empty)return;
 const requestedMaster=videoId(String(new URLSearchParams(location.search).get('master')||''));
 if(requestedMaster){
  const masterInput=document.querySelector('#watchalongBuilder [name="master"]');
  if(masterInput)masterInput.value=requestedMaster;
 }
 watchalongRecentInFlight=true;empty.hidden=false;empty.textContent='讀取近期同時視聽中…';
 try{
  const data=await api('/v1/watchalong/recent?days=30&limit=60');
  if(data?.schema_version!=='public-experience-v1'||data?.kind!=='watchalong'||!Array.isArray(data.events))throw Error('資料格式錯誤');
  grid.replaceChildren();
  for(const event of data.events){
   const hosts=Array.isArray(event?.hosts)?event.hosts.filter(x=>x&&/^[A-Za-z0-9_-]{11}$/.test(String(x.video_id||''))):[];
   if(!hosts.length)continue;
   const master=hosts[0].video_id;
   const card=node('article',undefined,'recent-watch-card');card.tabIndex=0;card.role='link';
   card.dataset.href='/watchalong?master='+encodeURIComponent(master)+'#manual';
   card.dataset.search=[event.title,event.day,event.scheduled_time,...hosts.map(x=>x.label)].filter(Boolean).join(' ').toLocaleLowerCase();
   const thumb=node('div',undefined,'recent-watch-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+master+'/hqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);card.append(thumb);
   const copy=node('div',undefined,'recent-watch-copy');const meta=node('div',undefined,'recent-watch-meta');
   meta.append(node('span',[event.day,event.scheduled_time].filter(Boolean).join(' ')));
   if(event.member_only)meta.append(node('span','會員限定','status-pill'));
   copy.append(meta,node('h3',String(event.title||'同時視聽')));
   const hostsBox=node('div',undefined,'recent-watch-hosts');
   for(const host of hosts){
    const link=node('a',undefined,'recent-watch-host');link.href='/watchalong?master='+encodeURIComponent(host.video_id)+'#manual';
    const avatar=node('span',undefined,'recent-host-avatar');avatar.append(node('span',(String(host.label||'H')[0]||'H').toUpperCase()));
    link.append(avatar,node('span',String(host.label||host.video_id)));hostsBox.append(link);
   }
   copy.append(hostsBox);card.append(copy);
   card.onclick=e=>{if(e.target.closest('.recent-watch-host'))return;location.href=card.dataset.href};
   card.onkeydown=e=>{if(e.key==='Enter'&&!e.target.closest('.recent-watch-host'))location.href=card.dataset.href};
   grid.append(card);
  }
  empty.hidden=grid.childElementCount>0;
  if(!grid.childElementCount)empty.textContent='目前沒有近期同時視聽資料。';
  const master=requestedMaster;
  if(master){
   const chosen=data.events.find(event=>Array.isArray(event?.hosts)&&event.hosts.some(host=>host.video_id===master));
   const host=chosen?.hosts?.find(item=>item.video_id===master);
   const copy=document.querySelector('#watchalongBuilder .manual-copy');
   if(chosen&&host&&copy){
    copy.replaceChildren();
    copy.append(node('span','已選擇同時視聽','eyebrow'),node('h2',String(chosen.title||'同時視聽')),node('p','主直播已選好，右邊只要選擇要同步的片源。'));
    const actions=node('div',undefined,'selection-actions');
    const cancel=node('a','取消選擇','selection-link');cancel.href='/watchalong?fresh=1#manual';
    const back=node('a','回到上方選擇','selection-link');back.href='#recent-watchalong';actions.append(cancel,back);copy.append(actions);
    const selected=node('div',undefined,'selected-master');
    const img=node('img');img.src='https://i.ytimg.com/vi/'+master+'/hqdefault.jpg';img.alt='';img.loading='lazy';selected.append(img);
    const source=node('span','YouTube ↗','youtube-source-link');source.role='link';source.tabIndex=0;source.dataset.youtubeHref='https://www.youtube.com/watch?v='+master;
    source.onclick=event=>{event.preventDefault();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')};
    source.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer')}};
    selected.append(source);
    const selectedCopy=node('div',undefined,'selected-master-copy');selectedCopy.append(node('strong',String(host.label||master)),node('span',[chosen.day,chosen.scheduled_time].filter(Boolean).join(' ')));selected.append(selectedCopy);copy.append(selected);
    const hidden=document.createElement('input');hidden.type='hidden';hidden.name='master';hidden.value=master;copy.append(hidden);
    document.getElementById('manual')?.scrollIntoView({block:'start'});
   }else{
    const masterInput=document.querySelector('#watchalongBuilder [name="master"]');if(masterInput)masterInput.value=master;
   }
  }
  document.getElementById('recentWatchSearch')?.dispatchEvent(new Event('input'));
  if(noMatches)noMatches.hidden=true;
 }catch(error){
  empty.hidden=false;empty.textContent='近期同時視聽資料暫時無法讀取；仍可使用下方手動建立。';
 }finally{watchalongRecentInFlight=false}
}

let pttLastGoodCount=0,pttLastGoodDay='',pttLoadInFlight=false,pttFollowing=true,pttProgrammatic=false;
function pttAtBottom(){
 const list=$('ptt-list');
 return list.scrollHeight-list.scrollTop-list.clientHeight<48;
}
function pttToLatest(force=false){
 const list=$('ptt-list');
 if(!force&&!pttFollowing)return;
 pttProgrammatic=true;list.scrollTop=list.scrollHeight;
 requestAnimationFrame(()=>requestAnimationFrame(()=>{pttProgrammatic=false}));
 $('ptt-newest').hidden=true;
}
function pttSettleLatest(frames=12){
 if(!pttFollowing||!pttLastGoodCount)return;
 pttToLatest(true);
 if(frames>0)requestAnimationFrame(()=>pttSettleLatest(frames-1));
}
function pttRow(row){
 const push=node('div',undefined,'push');
 push.dataset.pushId=String(row.push_id||row.aid+':'+row.source_line);
 const kind=String(row.kind||'→');
 const kindEl=node('div',kind,'ptt-push-kind '+(kind==='噓'?'kind-boo':kind==='→'?'kind-arrow':''));
 const meta=node('div',undefined,'ptt-push-meta');
 const when=new Date(String(row.occurred_at||''));
 if(Number.isFinite(when.getTime())){
  const label=new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false}).format(when);
  meta.append(node('time',label,'ptt-push-time'));
 }
 if(Number.isInteger(row.floor)&&row.floor>0)meta.append(node('span',row.floor+'樓','ptt-push-floor'));
 const body=node('div',undefined,'ptt-push-body');
 body.append(node('span',String(row.author||'unknown')+':','ptt-push-author'));
 body.append(node('span',String(row.content||''),'ptt-push-content'));
 push.append(kindEl,meta,body);
 if(row.source_url){
  push.title='點兩下開啟 PTT 原文';
  push.ondblclick=()=>window.open(String(row.source_url),'_blank','noopener,noreferrer');
 }
 return push;
}
function pttApplyFloorPreference(show){
 document.body.classList.toggle('ptt-floor-hidden',!show);
 $('ptt-show-floor').checked=show;
 try{localStorage.setItem('holoviewer-ptt-show-floor',String(Boolean(show)))}catch{}
}
function pttInitControls(){
 const list=$('ptt-list'),latest=$('ptt-newest');
 let show=true;try{show=localStorage.getItem('holoviewer-ptt-show-floor')!=='false'}catch{}
 pttApplyFloorPreference(show);
 latest.onclick=()=>{pttFollowing=true;pttToLatest(true)};
 list.addEventListener('wheel',event=>{
  if(event.deltaY<0)pttFollowing=false;
  else if(event.deltaY>0&&pttAtBottom())pttFollowing=true;
 },{passive:true});
 list.addEventListener('scroll',()=>{
  if(pttProgrammatic)return;
  pttFollowing=pttAtBottom();
  latest.hidden=pttFollowing;
 },{passive:true});
 $('ptt-show-floor').onchange=()=>pttApplyFloorPreference($('ptt-show-floor').checked);
 const settleToLatest=()=>pttSettleLatest();
 window.addEventListener('load',settleToLatest,{once:true});
 window.addEventListener('pageshow',settleToLatest);
 if(typeof ResizeObserver==='function'){
  const observer=new ResizeObserver(()=>{if(pttFollowing&&pttLastGoodCount)pttToLatest()});
  observer.observe(list);
  if(list.parentElement)observer.observe(list.parentElement);
 }
 if(typeof MutationObserver==='function'){
  const observer=new MutationObserver(()=>{if(pttFollowing&&pttLastGoodCount)pttToLatest()});
  observer.observe(list,{childList:true,subtree:true});
 }
}
function pttEmbeddedMessage(event){
 if(event.origin!==location.origin||event.source!==window.parent)return;
 const data=event.data&&typeof event.data==='object'?event.data:null;if(!data)return;
 if(data.type==='holoviewer:ptt-show-floor'){pttApplyFloorPreference(Boolean(data.show));return}
 if(data.type==='holoviewer:ptt-font-size'){
  const size=Math.max(12,Math.min(26,Number(data.size)||16));
  document.documentElement.style.setProperty('--ptt-font-size',size+'px');
 }
}
if(window.parent!==window)window.addEventListener('message',pttEmbeddedMessage);
async function loadPtt(){
 if(pttLoadInFlight)return;
 const today=taipeiDay();
 const meta=$('ptt-today-meta'),list=$('ptt-list'),empty=$('ptt-empty'),latest=$('ptt-newest');
 if(pttLastGoodDay&&pttLastGoodDay!==today){
  pttLastGoodCount=0;pttLastGoodDay='';list.replaceChildren();list.hidden=true;latest.hidden=true;pttFollowing=true;
 }
 if(!pttLastGoodCount){
  meta.textContent=today.replaceAll('-','/')+' · 讀取中 · 純 PTT 閱讀';
  empty.hidden=false;empty.textContent='讀取今日 PTT 推文中…';
 }
 if(!config.apiBase){
  meta.textContent=today.replaceAll('-','/')+' · API 未設定 · 純 PTT 閱讀';
  if(!pttLastGoodCount){empty.hidden=false;empty.textContent='PTT 正式 API 尚未接通。'}
  return;
 }
 pttLoadInFlight=true;
 try{
  const data=await api('/v1/ptt/today?day='+encodeURIComponent(today)+'&limit=300');
  if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes))throw Error('資料格式錯誤');
  const rows=data.pushes.filter(row=>row&&typeof row.content==='string');
  const wasEmpty=!pttLastGoodCount;
  const nearBottom=pttFollowing||pttAtBottom();
  const previousScroll=list.scrollTop;
  if(wasEmpty){
   const frag=document.createDocumentFragment();
   rows.forEach(row=>frag.append(pttRow(row)));
   list.replaceChildren(frag);
  }else{
   const seen=new Set([...list.children].map(el=>el.dataset.pushId));
   for(const row of rows){
    const key=String(row.push_id||row.aid+':'+row.source_line);
    if(!seen.has(key)){list.append(pttRow(row));seen.add(key)}
   }
   while(list.children.length>300)list.firstElementChild?.remove();
  }
  pttLastGoodCount=list.children.length;pttLastGoodDay=today;
  const freshness=String(data.freshness?.status||'unknown');
  const freshnessLabel=freshness==='fresh'?'即時':freshness==='stale'?'資料稍舊':'狀態未知';
  meta.textContent=today.replaceAll('-','/')+' · '+pttLastGoodCount+' 則推文 · '+freshnessLabel+' · 純 PTT 閱讀';
  list.hidden=!pttLastGoodCount;empty.hidden=Boolean(pttLastGoodCount);
  if(!pttLastGoodCount)empty.textContent='目前沒有今天的推文。';
  if(pttLastGoodCount){
   if(wasEmpty||nearBottom){pttFollowing=true;pttSettleLatest()}
   else{list.scrollTop=previousScroll;latest.hidden=false}
  }
 }catch(e){
  meta.textContent=today.replaceAll('-','/')+' · 後端暫未就緒 · 10 秒後重試 · 純 PTT 閱讀';
  if(!pttLastGoodCount){
   list.hidden=true;empty.hidden=false;latest.hidden=true;
   empty.textContent='今日 PTT 後端資料暫未就緒；頁面會每 10 秒自動重試。';
  }
 }finally{pttLoadInFlight=false}
}
pttInitControls();
document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.addEventListener('click',()=>setHomeFilter(button.dataset.filter)));
window.addEventListener('storage',event=>{if(event.key===HOME_FILTER_KEY)applyHomeFilter()});
$('historyMultiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('historyMultiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openViewingDocument(ids,{layout:'auto',ptt:'video',primary:0,audio:0})};
$('multiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('multiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openViewingDocument(ids,{layout:'auto',primary:0,audio:0,ptt:selectedHomePttMode()})};
$('ptt-refresh').onclick=event=>{event.preventDefault();location.href='/ptt-today'};
$('ptt-focus').onclick=event=>{event.preventDefault();location.href=document.body.classList.contains('ptt-focus-mode')?'/ptt-today':'/ptt-today?focus=1'};
let customCatalogCache=null;
async function loadCustomLibrary(){
 try{
  if(customCatalogCache===null){const data=await api('/v1/catalog/today');if(!Array.isArray(data.streams||data.items))throw Error('資料格式錯誤');customCatalogCache=data.streams||data.items}
  window.hvCustomCatalog?.(customCatalogCache);
 }catch(e){$('custom-live-empty').textContent='無法讀取目前直播：'+e.message;$('custom-live-empty').hidden=false}
}
function sessionMute(iframe,mute){
 if(!iframe?.contentWindow)return;
 iframe.contentWindow.postMessage(JSON.stringify({event:'command',func:mute?'mute':'unMute',args:[]}), 'https://www.youtube-nocookie.com');
}
const viewing={ids:[],layout:'auto',primary:0,audio:0,ptt:'video'};
const viewerPttPanel=$('custom-session-ptt-panel');
// 4174 watching controls — preserve mounted YouTube iframe instances.
let watchMode='single';
function refreshWatchMode(){
 const single=watchMode==='single';
 $('watchSingleMode').setAttribute('aria-pressed',String(single));
 $('watchMultiMode').setAttribute('aria-pressed',String(!single));
 $('watchModeToggle').setAttribute('aria-checked',String(!single));
 document.body.classList.toggle('watch-multi',!single);
 refreshWatchRail();
}
function setWatchMode(next){watchMode=next;refreshWatchMode();$('session-status').textContent=next==='single'?'已切換至單人模式：點頭像替換直播':'已切換至多人模式：點頭像新增視角'}
$('watchSingleMode').onclick=()=>setWatchMode('single');
$('watchMultiMode').onclick=()=>setWatchMode('multi');
$('watchModeToggle').onclick=()=>setWatchMode(watchMode==='single'?'multi':'single');
$('watchSettings').onclick=()=>{
 const open=document.body.classList.toggle('settings-open');
 $('watchSettings').setAttribute('aria-expanded',String(open));
};
$('watchImmersive').onclick=()=>$('customImmerse').click();
function syncWatchImmersive(){
 $('watchImmersive').textContent=document.body.classList.contains('custom-immersive')?'退出沉浸模式':'沉浸模式';
}
new MutationObserver(syncWatchImmersive).observe(document.body,{attributes:true,attributeFilter:['class']});
function youtubeCommand(iframe,command,args=[]){
 // YouTube documented iframe postMessage player API: no iframe recreation.
 if(!iframe?.contentWindow)return;
 iframe.contentWindow.postMessage(JSON.stringify({event:'command',func:command,args}),'https://www.youtube-nocookie.com');
}
// 4174-style linked play/pause. Player state is accepted only from the
// specific mounted YouTube iframe; no polling, guessed seek offsets or reloads.
const ytOrigins=new Set(['https://www.youtube-nocookie.com','https://www.youtube.com']);
const linkedEchoUntil=new WeakMap();
// Pinned 4174 verified-timeline engine. It stays dormant unless the session
// caller supplies a complete, explicitly verified start-time map.
const viewerTimeline=new Map();
let verifiedTimelineStarts=new Map();
function verifiedTimelineComplete(){
 return viewing.ids.length>1&&viewing.ids.every(id=>Number.isFinite(verifiedTimelineStarts.get(id)));
}
function timelineSeconds(iframe){
 const state=viewerTimeline.get(iframe);
 return state&&Number.isFinite(state.currentTime)?Math.max(0,state.currentTime):NaN;
}
function alignVerifiedFollower(iframe,origin){
 if(!verifiedTimelineComplete()||iframe===origin)return true;
 const iframes=[...$('stage').querySelectorAll('.player-card iframe')];
 const followerIndex=iframes.indexOf(iframe),masterIndex=iframes.indexOf(origin);
 if(followerIndex<0||masterIndex<0)return false;
 const masterNow=timelineSeconds(origin),followerNow=timelineSeconds(iframe);
 if(!Number.isFinite(masterNow)||!Number.isFinite(followerNow))return false;
 const expected=verifiedTimelineStarts.get(viewing.ids[masterIndex])+masterNow-verifiedTimelineStarts.get(viewing.ids[followerIndex]);
 if(expected<0)return false;
 const duration=viewerTimeline.get(iframe)?.duration;
 if(Number.isFinite(duration)&&duration>0&&expected>=duration)return false;
 if(Math.abs(followerNow-expected)>.8)youtubeCommand(iframe,'seekTo',[expected,true]);
 return true;
}
function registerViewerPlayer(iframe){
 if(!iframe?.contentWindow)return;
 iframe.contentWindow.postMessage(JSON.stringify({event:'listening',id:String(iframe.closest('.player-card')?.dataset.index||'0')}),'https://www.youtube-nocookie.com');
}
function linkedPlayPause(event){
 if(!$('syncPlayback').checked||!$('custom-session').classList.contains('active'))return;
 if(!ytOrigins.has(event.origin)||typeof event.data!=='string')return;
 let data;try{data=JSON.parse(event.data)}catch{return}
 const iframes=[...$('stage').querySelectorAll('.player-card iframe')];
 const source=iframes.find(iframe=>iframe.contentWindow===event.source);
 if(data?.event==='infoDelivery'&&source&&data.info&&typeof data.info==='object'){
  const previous=viewerTimeline.get(source)||{};
  viewerTimeline.set(source,{
   currentTime:typeof data.info.currentTime==='number'&&Number.isFinite(data.info.currentTime)?data.info.currentTime:previous.currentTime,
   duration:typeof data.info.duration==='number'&&Number.isFinite(data.info.duration)?data.info.duration:previous.duration
  });
  return;
 }
 if(!data||data.event!=='onStateChange'||![1,2].includes(data.info))return;
 const origin=source;
 if(!origin||Date.now()<(linkedEchoUntil.get(origin)||0))return;
 const command=data.info===1?'playVideo':'pauseVideo';
 for(const iframe of iframes){
  if(iframe===origin)continue;
  if(data.info===1&&verifiedTimelineComplete()&&!alignVerifiedFollower(iframe,origin)){
   linkedEchoUntil.set(iframe,Date.now()+1000);
   youtubeCommand(iframe,'pauseVideo');
   continue;
  }
  linkedEchoUntil.set(iframe,Date.now()+1000);
  youtubeCommand(iframe,command);
 }
}
window.addEventListener('message',linkedPlayPause);

function globalVolume(value){
 const volume=Math.max(0,Math.min(100,Number(value)||0));
 $('globalVolume').value=String(volume);$('immersiveGlobalVolume').value=String(volume);
 $('globalVolumeValue').textContent=volume+'%';$('immersiveGlobalVolumeValue').textContent=volume+'%';
 $('stage').querySelectorAll('iframe').forEach(iframe=>youtubeCommand(iframe,'setVolume',[volume]));
}
$('globalVolume').oninput=event=>globalVolume(event.target.value);
$('immersiveGlobalVolume').oninput=event=>globalVolume(event.target.value);
$('playAll').onclick=()=>$('stage').querySelectorAll('iframe').forEach(iframe=>youtubeCommand(iframe,'playVideo'));
$('pauseAll').onclick=()=>$('stage').querySelectorAll('iframe').forEach(iframe=>youtubeCommand(iframe,'pauseVideo'));
$('videoHeight').oninput=event=>{
 const px=Math.max(360,Math.min(1000,Number(event.target.value)||1000));
 document.querySelector('.custom-player-column').style.setProperty('--custom-video-height',px+'px');
 $('videoHeightValue').textContent=px+'px';
};
$('audioFollowFocus').onchange=()=>{if($('audioFollowFocus').checked){viewing.audio=viewing.primary;sessionAudio()}};
// The pinned 4174 focus carousel rotates the primary view every 10–60 seconds.
// Use animation frames rather than background polling; all mounted players persist.
let focusCarouselFrame=0,focusCarouselDeadline=0;
let focusCarouselSeconds=10;
function stopFocusCarousel(){
 if(focusCarouselFrame)cancelAnimationFrame(focusCarouselFrame);
 focusCarouselFrame=0;focusCarouselDeadline=0;
 $('focusCarousel').classList.remove('active');
 $('focusCarousel').setAttribute('aria-pressed','false');
 $('focusCarousel').textContent='輪播 '+focusCarouselSeconds+'s';
}
window.hvStopFocusCarousel=stopFocusCarousel;
function focusCarouselTick(now){
 if(!focusCarouselFrame)return;
 if(document.hidden||!$('custom-session').classList.contains('active')||viewing.ids.length<2){
  stopFocusCarousel();return;
 }
 if(now>=focusCarouselDeadline){
  setViewerPrimary((viewing.primary+1)%viewing.ids.length,true);
  focusCarouselDeadline=now+focusCarouselSeconds*1000;
 }
 focusCarouselFrame=requestAnimationFrame(focusCarouselTick);
}
function startFocusCarousel(){
 if(viewing.ids.length<2)return;
 stopFocusCarousel();
 $('audioFollowFocus').checked=true;
 setViewerPrimary(viewing.primary,true);
 $('focusCarousel').classList.add('active');
 $('focusCarousel').setAttribute('aria-pressed','true');
 $('focusCarousel').textContent='停止輪播';
 focusCarouselDeadline=performance.now()+focusCarouselSeconds*1000;
 focusCarouselFrame=requestAnimationFrame(focusCarouselTick);
}
$('focusCarousel').onclick=()=>{
 if(focusCarouselFrame)stopFocusCarousel();else startFocusCarousel();
};
$('focusCarouselInterval').oninput=()=>{
 focusCarouselSeconds=Math.max(10,Math.min(60,Number($('focusCarouselInterval').value)||10));
 $('focusCarouselIntervalOutput').textContent=focusCarouselSeconds+' 秒';
 if(focusCarouselFrame)focusCarouselDeadline=performance.now()+focusCarouselSeconds*1000;
 else $('focusCarousel').textContent='輪播 '+focusCarouselSeconds+'s';
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopFocusCarousel()});
window.addEventListener('pagehide',stopFocusCarousel);
function setViewerPrimary(index,fromCarousel=false){
 if(!fromCarousel)stopFocusCarousel();
 if(!Number.isInteger(index)||index<0||index>=viewing.ids.length)return;
 // Original 4174 primary selection is also the target for single-mode rail replacement.
 replacementTarget=index;
 viewing.primary=index;
 // Accepted 4174 setPrimary() selects primary geometry, not merely a badge.
 viewing.layout='primary';
 if($('audioFollowFocus').checked){viewing.audio=index;sessionAudio()}
 sessionLayout();
}
function renderFocusChoices(){
 const box=$('focusChoices');box.replaceChildren();
 viewing.ids.forEach((id,index)=>{
  const button=node('button','Focus '+String.fromCharCode(65+index));button.type='button';
  button.dataset.focusIndex=String(index);button.classList.toggle('active',index===viewing.primary);
  button.onclick=()=>setViewerPrimary(index);
  box.append(button);
 });
}


function makeWatchCard(id,index){
 const card=node('div',undefined,'player-card');card.dataset.index=String(index);
 const wrap=node('div',undefined,'video-wrap');const player=frame(id);wrap.append(player);card.append(wrap);
 const controls=node('div',undefined,'player-controls');const copy=node('div');copy.append(node('div','影片 '+(index+1),'player-label'));
 const actions=node('div',undefined,'player-actions');const primary=node('button','主視角','master');primary.type='button';
 primary.onclick=()=>setViewerPrimary(index);
 const youtube=node('a','YouTube ↗','player-youtube-link');youtube.href='https://www.youtube.com/watch?v='+id;youtube.target='_blank';youtube.rel='noopener noreferrer';
 actions.append(primary,youtube);controls.append(copy,actions);card.append(controls);
 player.addEventListener('load',()=>{registerViewerPlayer(player);sessionMute(player,index!==viewing.audio);globalVolume($('globalVolume').value)});
 return card;
}
let replacementTarget=0;
function refreshWatchRail(){
 const ids=new Set(viewing.ids);
 document.querySelectorAll('.live-channel-rail-item[data-live-video-id]').forEach(link=>{
  link.hidden=(homeFilter()!=='all'&&link.dataset.group!==homeFilter())||(watchMode==='multi'&&ids.has(link.dataset.liveVideoId));
 });
}
function selectWatchRailVideo(id,title){
 if(!/^[A-Za-z0-9_-]{11}$/.test(id)||!viewing.ids.length)return;
 if(watchMode==='multi'){
  if(viewing.ids.includes(id))return;
  const index=viewing.ids.length;viewing.ids.push(id);verifiedTimelineStarts.delete(id);if(viewing.ids.length>1)$('syncPlayback').checked=true;
  $('stage').append(makeWatchCard(id,index));
  const option=node('option',String(index+1)+' · '+id);option.value=String(index);$('session-audio').append(option);
  renderFocusChoices();sessionLayout();sessionAudio();refreshWatchRail();
  $('session-status').textContent='已新增視角 '+String.fromCharCode(65+index)+'：'+title;
  return;
 }
 const index=viewing.ids.length===1?0:Math.min(replacementTarget,viewing.ids.length-1);
 if(viewing.ids[index]===id||viewing.ids.some((v,i)=>i!==index&&v===id))return;
 viewing.ids[index]=id;verifiedTimelineStarts.delete(id);
 const card=$('stage').querySelectorAll('.player-card')[index];if(!card)return;
 const iframe=card.querySelector('iframe');if(!iframe)return;
 // Only the replaced player may navigate. Other iframes stay mounted and playing.
 viewerTimeline.delete(iframe);
 iframe.src=youtubeEmbedUrl(id);
 card.querySelector('.player-label').textContent=title;
 card.querySelector('.player-youtube-link').href='https://www.youtube.com/watch?v='+id;
 const option=$('session-audio').options[index];if(option)option.textContent=String(index+1)+' · '+id;
 renderFocusChoices();sessionLayout();refreshWatchRail();
 $('session-status').textContent='已切換視角 '+String.fromCharCode(65+index)+'：'+title;
}

function sessionLayout(){
 const stage=$('stage');const n=viewing.ids.length;
 stage.style.setProperty('--columns',String(viewing.layout==='equal'?Math.max(1,Math.ceil(Math.sqrt(n))):viewing.layout==='primary'&&n>1?2:Math.max(1,Math.ceil(Math.sqrt(n)))));
 document.body.classList.toggle('layout-primary',viewing.layout==='primary'&&$('custom-session').classList.contains('active'));
 stage.querySelectorAll('.player-card').forEach((el,i)=>{
  el.classList.toggle('primary',i===viewing.primary);
  el.classList.toggle('replacement-target',i===replacementTarget);
  const button=el.querySelector('.master');
  if(button)button.setAttribute('aria-pressed',String(i===viewing.primary));
 });
 document.querySelectorAll('[data-session-layout]').forEach(btn=>btn.classList.toggle('active',btn.dataset.sessionLayout===viewing.layout));
 $('focusChoices').querySelectorAll('[data-focus-index]').forEach(btn=>btn.classList.toggle('active',Number(btn.dataset.focusIndex)===viewing.primary));
}
function sessionAudio(){
 const sel=$('session-audio');sel.value=String(viewing.audio);
 $('stage').querySelectorAll('.player-card iframe').forEach((el,i)=>sessionMute(el,i!==viewing.audio));
}
async function resolveProductionPtt(videoIdValue){
 const id=videoId(String(videoIdValue||''));if(!id)return {mode:'unavailable'};
 let row;try{row=await api('/v1/catalog/videos/'+encodeURIComponent(id));}catch(_error){return {mode:'unavailable'}}
 const lifecycle=String(row?.lifecycle_state||row?.state||'').toLowerCase();
 if(['live','upcoming','waiting'].includes(lifecycle))return {mode:'live'};
 if(lifecycle!=='ended')return {mode:'unavailable'};
 const start=String(row?.actual_start||row?.scheduled_start||'');
 const startMs=Date.parse(start);if(!Number.isFinite(startMs))return {mode:'unavailable'};
 const endMs=Date.parse(String(row?.actual_end||''));
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(startMs));
 const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 const day=out.year+'-'+out.month+'-'+out.day;
 const messages=[];let after='',pages=0;
 while(pages++<50){
  const path='/v1/ptt/history?day='+encodeURIComponent(day)+'&limit=200'+(after?'&after='+encodeURIComponent(after):'');
  let data;try{data=await api(path)}catch(_error){return messages.length?{mode:'archive',start,messages}:{mode:'unavailable'}}
  if(data?.schema_version!=='public-consumer-v1'||!Array.isArray(data.pushes))return {mode:'unavailable'};
  let beyond=false;
  for(const push of data.pushes){
   const when=Date.parse(String(push?.occurred_at||''));
   if(!Number.isFinite(when))continue;
   if(when>=startMs&&(!Number.isFinite(endMs)||when<=endMs))messages.push(push);
   if(Number.isFinite(endMs)&&when>endMs)beyond=true;
  }
  const next=String(data.page?.next_checkpoint||'');
  if(beyond||data.page?.has_more!==true||!next||next===after)break;
  after=next;
 }
 return {mode:'archive',start,messages};
}
window.hvOpenCustomSession=function(ids,opts={}){
 const clean=[...new Set(ids.map(id=>videoId(String(id||''))).filter(Boolean))];
 if(!clean.length)return;
 viewing.ids=clean;
 viewing.ptt=['live','archive','unavailable'].includes(opts.ptt)?opts.ptt:'unavailable';
 viewing.layout=['auto','equal','primary'].includes(opts.layout)?opts.layout:'auto';
 viewing.primary=Math.max(0,Math.min(clean.length-1,Number(opts.primary)||0));
 viewing.audio=Math.max(0,Math.min(clean.length-1,Number(opts.audio)||0));
 replacementTarget=0;
 watchMode=clean.length>1?'multi':'single';

 const section=$('custom-session');
 if(typeof window.render4174SharedViewerDOM!=='function'||typeof window.mount4174SharedViewer!=='function'){
  section.replaceChildren(Object.assign(document.createElement('p'),{className:'form-error',textContent:'4174 viewer transplant assets failed to load.'}));
  return;
 }
 const hasPttResolver=typeof opts.pttResolve==='function'||Boolean(opts.pttResolverUrl);
 section.replaceChildren(window.render4174SharedViewerDOM(viewing.ptt==='live',hasPttResolver));
 route('custom-session');

 const streamMetadata=new Map([...document.querySelectorAll('.live-channel-rail-item[data-live-video-id]')].map(item=>[
  item.dataset.liveVideoId,
  {label:item.dataset.title||item.dataset.channel||item.dataset.liveVideoId,channelId:item.dataset.channelId||item.dataset.channel||''}
 ]));
 const collabMetadata=new Map((Array.isArray(opts.streamMetadata)?opts.streamMetadata:[])
  .filter(x=>x&&clean.includes(x.videoId)).map(x=>[x.videoId,x]));
 const streams=clean.map((id,index)=>{
  const meta=collabMetadata.get(id)||streamMetadata.get(id)||{};
  return {videoId:id,label:meta.label||('Stream '+(index+1)),channelId:meta.channelId||''};
 });
 window.mount4174SharedViewer({
  streams,
  layout:viewing.layout,
  primaryIndex:viewing.primary,
  audioMasterIndex:viewing.audio,
  singlePttKind:viewing.ptt==='live'?'live':(viewing.ptt==='archive'?'vod':''),
  pttResolverUrl:typeof opts.pttResolverUrl==='string'?opts.pttResolverUrl:'',
  pttResolve:typeof opts.pttResolve==='function'?opts.pttResolve:null,
  translationA:[],
  translationB:[],
  verifiedTimelineStarts:opts.verifiedTimelineStarts&&typeof opts.verifiedTimelineStarts==='object'?opts.verifiedTimelineStarts:{},
  manualTimelineStarts:{},
  collabPollUrl:typeof opts.collabPollUrl==='string'?opts.collabPollUrl:'',
  collabLabel:typeof opts.collabLabel==='string'?opts.collabLabel:''
 });
};
$('session-audio').onchange=()=>{viewing.audio=Number($('session-audio').value)||0;sessionAudio()};
document.querySelectorAll('[data-session-layout]').forEach(btn=>btn.onclick=()=>{viewing.layout=btn.dataset.sessionLayout;sessionLayout()});
document.querySelectorAll('[data-route]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.route)}));document.querySelectorAll('[data-mobile-route]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.mobileRoute)}));document.querySelectorAll('.rail-brand,.mobile-top-brand').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route('home')}));$('mobileNavButton').onclick=()=>{const opening=$('mobileNav').hidden;$('mobileNav').hidden=!opening;$('mobileNavButton').setAttribute('aria-expanded',String(opening))};$('history-picker').onsubmit=event=>{event.preventDefault();state.offset=0;loadHistory()};$('historyDate').value=historyBounds().latest;renderMulti();route(location.hash.substring(1).split('?')[0]||'home');



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
    const avatar=document.createElement('img');avatar.className='selected-avatar';avatar.alt='';avatar.loading='lazy';avatar.src=metadata?.avatar||'/favicon.ico';avatar.onerror=()=>{avatar.onerror=null;avatar.hidden=true;};
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
function addStream(value){
 const id=videoId(String(value||''));
 const error=document.getElementById('custom-error');
 const status=document.getElementById('custom-selection-status');
 if(!id){error.textContent='請提供有效的 YouTube 直播或影片連結。';error.hidden=false;status.textContent='';return false;}
 if(items.includes(id)){status.textContent='這支影片已在清單中；按「開始觀看」即可開啟。';return true;}
 error.hidden=true;items.push(id);render();
 status.textContent='已加入 '+items.length+' 支影片；按下方「開始觀看」開啟播放器。';
 return true;
}
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
document.getElementById('add').onclick=()=>{const value=input.value.trim();if(!value){document.getElementById('custom-error').textContent='請先貼上 YouTube 網址或影片 ID。';document.getElementById('custom-error').hidden=false;return;}if(addStream(value))input.value='';input.focus();};
input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();document.getElementById('add').click();}});
document.getElementById('start').onclick=()=>{
  if(!items.length){alert('請先加入至少一個影片。');return;}
  const q=new URLSearchParams();items.forEach(v=>q.append('stream',v));
  q.set('layout',items.length===1?'auto':document.getElementById('layout').value);
  q.set('ptt',document.getElementById('pttMode').value);
  q.set('primary',String(Math.max(0,items.indexOf(primaryId))));
  q.set('audio',String(Math.max(0,items.indexOf(audioId))));
  location.href='/custom-view/session?'+q.toString();
};
render();

window.hvCustomCatalog=function(rows){
 const box=document.getElementById('custom-live-picker');box.replaceChildren();streamMetadata.clear();
 for(const row of rows){
  const id=String(row?.video_id||'');if(!/^[A-Za-z0-9_-]{11}$/.test(id))continue;
  const channel=String(row.channel_title||row.channel_name||'Hololive');const title=String(row.title||id);
  const avatar=String(row.avatar_url||'');streamMetadata.set(id,{channel,title,avatar:/^https:\/\/(yt3\.ggpht\.com|i\.ytimg\.com)\//.test(avatar)?avatar:''});
  const card=node('div',undefined,'live-picker-item');card.setAttribute('role','button');card.tabIndex=0;card.dataset.livePick=id;card.setAttribute('aria-pressed',String(items.includes(id)));
  const cover=node('div',undefined,'live-picker-cover');const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';cover.append(img);
  const source=node('span','YouTube ↗','youtube-source-link');source.setAttribute('role','link');source.tabIndex=0;source.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;cover.append(source);card.append(cover);
  const label=node('span');const strong=node('strong',channel);label.append(strong,document.createTextNode(' · '+title));card.append(label);box.append(card);
 }
 document.getElementById('custom-live-empty').hidden=box.childElementCount>0;
 render();
};
window.hvCustomAdd=addStream;

})();


function playlistId(input){
 const raw=String(input||'').trim();if(/^[A-Za-z0-9_-]{10,}$/.test(raw))return raw;
 try{const u=new URL(raw);if(!['youtube.com','www.youtube.com','m.youtube.com'].includes(u.hostname))return '';return String(u.searchParams.get('list')||'')}catch{return ''}
}

// Accepted 4174 watchalong landing mode/tab interactions.
(function(){

const recentWatchSearch=document.getElementById('recentWatchSearch');
let activeWatchGroup='all';
function filterRecentWatchalong(){
  const query=recentWatchSearch?.value.trim().toLocaleLowerCase()||'';
  let visible=0;
  document.querySelectorAll('#recentWatchGrid .recent-watch-card').forEach(card=>{
    const groupMatch=activeWatchGroup==='all'||(card.dataset.group||'').split(' ').includes(activeWatchGroup);
    const textMatch=!query||(card.dataset.search||'').toLocaleLowerCase().includes(query);
    card.hidden=!(groupMatch&&textMatch);
    if(!card.hidden)visible++;
  });
  const empty=document.getElementById('recentWatchNoMatches');
  if(empty)empty.hidden=visible!==0;
}
recentWatchSearch?.addEventListener('input',filterRecentWatchalong);
document.querySelectorAll('[data-watch-group]').forEach(button=>button.addEventListener('click',()=>{
  activeWatchGroup=button.dataset.watchGroup||'all';
  document.querySelectorAll('[data-watch-group]').forEach(item=>item.classList.toggle('active',item===button));
  filterRecentWatchalong();
}));
const youtubePanel=document.getElementById('youtubePanel');
const externalPanel=document.getElementById('externalPanel');
const youtubeMode=document.getElementById('youtubeMode');
const singleFields=document.getElementById('singleFields');
const playlistFields=document.getElementById('playlistFields');
function applySourceKind(){
  const kind=document.querySelector('input[name="source_kind"]:checked')?.value||'youtube';
  youtubePanel.hidden=kind!=='youtube';
  externalPanel.hidden=kind!=='external';
}
document.querySelectorAll('input[name="source_kind"]').forEach(input=>input.addEventListener('change',applySourceKind));
document.querySelectorAll('[data-youtube-mode]').forEach(button=>button.addEventListener('click',()=>{
  youtubeMode.value=button.dataset.youtubeMode;
  document.querySelectorAll('[data-youtube-mode]').forEach(item=>item.classList.toggle('active',item===button));
  singleFields.hidden=youtubeMode.value!=='single';
  playlistFields.hidden=youtubeMode.value!=='playlist';
}));
applySourceKind();

const watchForm=document.getElementById('watchalongBuilder');
watchForm.addEventListener('submit',event=>{
 event.preventDefault();
 const form=new FormData(watchForm);
 const master=videoId(String(form.get('master')||''));
 const error=document.getElementById('watch-error');error.hidden=true;
 if(!master){error.textContent='Hololive 主影片無法辨識，請確認 YouTube URL 或 Video ID。';error.hidden=false;return}
 if(form.get('source_kind')==='youtube'&&form.get('youtube_mode')==='single'&&!videoId(String(form.get('source')||''))){error.textContent='請提供有效的 YouTube 片源網址或 Video ID。';error.hidden=false;return}
 if(form.get('source_kind')==='youtube'&&form.get('youtube_mode')==='playlist'&&!playlistId(String(form.get('playlist')||''))){error.textContent='請提供有效的 YouTube Playlist URL。';error.hidden=false;return}
 if(form.get('source_kind')==='external'){
  try{const u=new URL(String(form.get('external_source')||''));if(!['https:','http:'].includes(u.protocol))throw Error('invalid')}catch{error.textContent='外部片源網址無法辨識，請提供 http(s) 網址。';error.hidden=false;return}
 }
 const q=new URLSearchParams();for(const [key,value] of form.entries())q.append(key,String(value));
 location.href='/watchalong/session?'+q.toString();
});
})();


function watchalongClock(seconds){
 const value=Math.max(0,Math.floor(Number(seconds)||0)),h=Math.floor(value/3600),m=Math.floor((value%3600)/60),sec=value%60;
 return (h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(sec).padStart(2,'0');
}
function ensureWatchalongYoutubeApi(callback){
 if(window.YT?.Player){callback();return}
 window.__hvWatchalongYoutubeReady=window.__hvWatchalongYoutubeReady||[];
 window.__hvWatchalongYoutubeReady.push(callback);
 if(window.__hvWatchalongYoutubeRequested)return;
 window.__hvWatchalongYoutubeRequested=true;
 const previous=window.onYouTubeIframeAPIReady;
 window.onYouTubeIframeAPIReady=function(){
  if(typeof previous==='function')previous();
  const callbacks=window.__hvWatchalongYoutubeReady.splice(0);
  callbacks.forEach(fn=>fn());
 };
 const script=document.createElement('script');script.src='https://www.youtube.com/iframe_api';document.head.appendChild(script);
}
async function renderWatchalongSession(){
 if(location.pathname!=='/watchalong/session')return;
 const shell=$('watchalong-session-shell');if(!shell)return;
 const params=new URLSearchParams(location.search);
 const master=videoId(String(params.get('master')||'')),kind=String(params.get('source_kind')||'youtube'),youtubeMode=String(params.get('youtube_mode')||'single');
 if(!master){location.replace('/watchalong');return}
 let resolvedMode=String(params.get('view_mode')||'auto');
 if(resolvedMode==='auto'){
  try{
   const data=await api('/v1/catalog/today'),rows=data.streams||data.items||[];
   const found=Array.isArray(rows)?rows.find(x=>x.video_id===master):null,state=String(found?.lifecycle_state||found?.state||'').toLowerCase();
   resolvedMode=['live','upcoming','waiting'].includes(state)?'live':state==='ended'?'archive':'manual';
  }catch{resolvedMode='manual'}
 }
 shell.replaceChildren();
 const status=node('div','等待播放器…','watchalong-session-status');
 const actions=node('div',undefined,'watchalong-session-actions');
 const compare=node('button','雙畫面');compare.type='button';compare.className='active';
 const focus=node('button','動畫優先');focus.type='button';
 const play=node('button','播放左側直播');play.type='button';play.className='primary-action';
 const pause=node('button','暫停左側直播');pause.type='button';
 const immersive=node('button','沉浸全螢幕');immersive.type='button';
 actions.append(compare,focus,play,pause,immersive);
 const layout=node('div',undefined,'watchalong-player-grid');
 const masterCard=node('section',undefined,'watchalong-player-card');
 masterCard.append(node('div','Hololive 直播（主時間軸）','watchalong-player-head'));
 const masterWrap=node('div',undefined,'watchalong-player-wrap'),masterHost=node('div');masterHost.id='watchalong-master-player';masterHost.className='watchalong-player';masterWrap.append(masterHost);masterCard.append(masterWrap);
 layout.append(masterCard);
 let masterPlayer=null,sourcePlayer=null,statusTimer=null;
 const setFocus=enabled=>{layout.classList.toggle('focus-source',enabled);compare.classList.toggle('active',!enabled);focus.classList.toggle('active',enabled)};
 const setImmersive=enabled=>{
  document.body.classList.toggle('watchalong-immersive',Boolean(enabled));
  immersive.textContent=enabled?'退出沉浸模式':'沉浸全螢幕';
 };
 compare.onclick=()=>setFocus(false);focus.onclick=()=>setFocus(true);
 immersive.onclick=async()=>{
  const next=!document.body.classList.contains('watchalong-immersive');setImmersive(next);
  if(next&&!document.fullscreenElement&&shell.requestFullscreen){try{await shell.requestFullscreen()}catch(_error){}}
  else if(!next&&document.fullscreenElement&&document.exitFullscreen){try{await document.exitFullscreen()}catch(_error){}}
 };
 document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement&&document.body.classList.contains('watchalong-immersive'))setImmersive(false)});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('watchalong-immersive')&&!document.fullscreenElement)setImmersive(false)});
 function tick(){
  const mt=Number(masterPlayer?.getCurrentTime?.()||0),st=Number(sourcePlayer?.getCurrentTime?.()||0);
  if(kind==='youtube')status.textContent=(resolvedMode==='live'?'即時模式 · 右側片源獨立控制':'手動模式 · 右側片源獨立控制')+' · 主時間 '+watchalongClock(mt)+' · 來源 '+watchalongClock(st);
  else status.textContent='外部平台 companion · 主時間 '+watchalongClock(mt);
 }
 window.addEventListener('pagehide',()=>{if(statusTimer)clearInterval(statusTimer);try{masterPlayer?.destroy?.();sourcePlayer?.destroy?.()}catch{}},{once:true});
 if(kind==='external'){
  const external=String(params.get('external_source')||'');
  let valid='';try{const u=new URL(external);if(['https:','http:'].includes(u.protocol))valid=u.toString()}catch{}
  if(!valid){location.replace('/watchalong?master='+encodeURIComponent(master));return}
  const side=node('section',undefined,'watchalong-player-card watchalong-companion-card');side.append(node('div','外部片源（已登入瀏覽器 companion）','watchalong-player-head'));
  const body=node('div',undefined,'watchalong-companion-body');
  const link=node('a','開啟外部片源 ↗','primary-action');link.href=valid;link.target='_blank';link.rel='noopener noreferrer';body.append(link,node('p','外部片源留在原本登入的瀏覽器分頁；此頁只提供主時間與手動對齊，不讀取帳密或控制外部分頁。','helper'));
  const label=node('label','外部片源目前時間（HH:MM:SS 或 MM:SS）');const input=node('input');input.value='00:00';input.inputMode='numeric';label.append(input);body.append(label);
  const anchor=node('button','以目前位置建立對齊點');anchor.type='button';anchor.className='primary-action';const target=node('strong','00:00','watchalong-target');body.append(anchor,node('div','目前應播放到：'),target);
  let anchorMaster=0,anchorSource=0,correction=0;
  const parseClock=value=>{const parts=String(value||'').trim().split(':').map(Number);if(!parts.length||parts.some(v=>!Number.isFinite(v)||v<0))return null;if(parts.length===3)return parts[0]*3600+parts[1]*60+parts[2];if(parts.length===2)return parts[0]*60+parts[1];if(parts.length===1)return parts[0];return null};
  anchor.onclick=()=>{const source=parseClock(input.value);if(source===null){status.textContent='外部片源時間格式無法辨識';return}anchorMaster=Number(masterPlayer?.getCurrentTime?.()||0);anchorSource=source;correction=0};
  const adjust=node('div',undefined,'watchalong-adjust-row');for(const delta of [-5,-1,1,5]){const b=node('button',(delta>0?'+':'')+delta+' 秒');b.type='button';b.onclick=()=>{correction+=delta};adjust.append(b)}body.append(adjust);
  const externalTick=()=>{const mt=Number(masterPlayer?.getCurrentTime?.()||0);target.textContent=watchalongClock(Math.max(0,anchorSource+(mt-anchorMaster)+correction));};
  const oldTick=tick;tick=()=>{externalTick();oldTick()};
  side.append(body);layout.append(side);
 }else{
  const sourceRaw=String(params.get('source')||''),source=videoId(sourceRaw),playlist=playlistId(String(params.get('playlist')||''));
  if(youtubeMode==='single'&&!source){location.replace('/watchalong?master='+encodeURIComponent(master));return}
  if(youtubeMode==='playlist'&&!playlist){location.replace('/watchalong?master='+encodeURIComponent(master));return}
  const sourceCard=node('section',undefined,'watchalong-player-card');sourceCard.append(node('div',youtubeMode==='playlist'?'同時視聽來源（YouTube Playlist）':'同時視聽來源（YouTube）','watchalong-player-head'));
  const sourceWrap=node('div',undefined,'watchalong-player-wrap'),sourceHost=node('div');sourceHost.id='watchalong-source-player';sourceHost.className='watchalong-player';sourceWrap.append(sourceHost);sourceCard.append(sourceWrap);
  if(resolvedMode!=='live')sourceCard.append(node('div','Public API 目前不公開 source mapping / transcript，對齊保持手動；不會偽造自動時間軸。','watchalong-session-note'));
  layout.append(sourceCard);
 }
 shell.append(actions,layout,status);
 ensureWatchalongYoutubeApi(()=>{
  masterPlayer=new YT.Player('watchalong-master-player',{videoId:master,width:'100%',height:'100%',playerVars:{playsinline:1,rel:0,controls:1},events:{onReady:()=>{play.disabled=false;pause.disabled=false}}});
  if(kind==='youtube'){
   const source=videoId(String(params.get('source')||'')),playlist=playlistId(String(params.get('playlist')||''));
   const options={width:'100%',height:'100%',playerVars:{playsinline:1,rel:0,controls:1},events:{}};
   if(youtubeMode==='playlist'){options.playerVars.listType='playlist';options.playerVars.list=playlist}else options.videoId=source;
   sourcePlayer=new YT.Player('watchalong-source-player',options);
  }
  play.onclick=()=>masterPlayer?.playVideo?.();pause.onclick=()=>masterPlayer?.pauseVideo?.();tick();
  if(!statusTimer)statusTimer=setInterval(tick,500);
 });
}
renderWatchalongSession();

// 4174-style session lifecycle: the URL is the complete source of truth.
(async function restoreCustomSession(){
 if(location.pathname!=='/custom-view/session')return;
 const params=new URLSearchParams(location.search);
 const ids=[...new Set(params.getAll('stream').filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))];
 if(!ids.length){location.replace('/custom-view');return;}
 const opts={
  layout:params.get('layout'),
  ptt:params.get('ptt')==='video'?'video':'live',
  primary:Number(params.get('primary')||0),
  audio:Number(params.get('audio')||0)
 };
 const eventId=String(params.get('event')||'');
 if(eventId){
  try{
   const payload=await api('/v1/collab/events/'+encodeURIComponent(eventId));
   const event=payload?.event||payload;
   const streams=collabEventStreams(event);
   opts.collabLabel=String(event?.label||'多人連動');
   const pollable=streams.some(x=>['live','upcoming','waiting'].includes(String(x.lifecycle_state||'').toLowerCase()));
   if(pollable)opts.collabPollUrl=config.apiBase.replace(/\/$/,'')+'/v1/collab/events/'+encodeURIComponent(eventId);
   opts.streamMetadata=streams.map(x=>({videoId:x.video_id,label:String(x.title||x.channel_name||x.video_id),channelId:String(x.channel_id||'')}));
   if(event?.sync?.available===true){
    opts.verifiedTimelineStarts={};
    for(const stream of streams){
     const seconds=Date.parse(String(stream.actual_start||''))/1000;
     if(Number.isFinite(seconds))opts.verifiedTimelineStarts[stream.video_id]=seconds;
    }
   }
  }catch(_error){}
 }
 const knownMetadata=new Map((Array.isArray(opts.streamMetadata)?opts.streamMetadata:[]).map(x=>[x.videoId,x]));
 const catalogRows=new Map();
 const missing=ids.filter(id=>!knownMetadata.has(id));
 if(missing.length){
  const resolved=await Promise.all(missing.map(async id=>{
   try{
    const item=await api('/v1/catalog/videos/'+encodeURIComponent(id));
    if(item&&item.video_id===id){
     catalogRows.set(id,item);
     return {videoId:id,label:String(item.title||item.channel_name||id),channelId:String(item.channel_id||'')};
    }
    return null;
   }catch(_error){return null}
  }));
  for(const item of resolved){if(item)knownMetadata.set(item.videoId,item)}
 }
 // Thin API adapter only: preserve 4174 live/archive/unavailable PTT resolution.
 // Do not invent a frontend PTT mode from lifecycle alone.
 if(ids.length===1){
  let row=catalogRows.get(ids[0])||null;
  if(!row){
   try{row=await api('/v1/catalog/videos/'+encodeURIComponent(ids[0]));}catch(_error){}
  }
  const lifecycle=String(row?.lifecycle_state||row?.state||'').toLowerCase();
  const rawStart=String(row?.actual_start||row?.scheduled_start||row?.start_at||'');
  const startedAt=new Date(rawStart);
  let streamDay='';
  if(Number.isFinite(startedAt.getTime())){
   const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(startedAt);
   const out=Object.fromEntries(parts.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
   streamDay=out.year+'-'+out.month+'-'+out.day;
  }
  if(['live','upcoming','waiting'].includes(lifecycle)&&streamDay===taipeiDay()){
   opts.ptt='live';
   opts.pttResolve=resolveProductionPtt;
  }else if(lifecycle==='ended'&&streamDay){
   opts.ptt='archive';
   opts.pttResolve=resolveProductionPtt;
  }else{
   opts.ptt='unavailable';
  }
 }
 opts.streamMetadata=ids.map(id=>knownMetadata.get(id)).filter(Boolean);
 window.hvOpenCustomSession(ids,opts);
})();
