'use strict';
const config=window.HOLOVIEWER_CONFIG||{};
const $=id=>document.getElementById(id);
const names={home:'今日直播',single:'自訂觀看',multi:'多人連動',history:'歷史直播',ptt:'PTT 今日專串',watchalong:'同時視聽','custom-session':'自訂觀看','ptt-focus':'PTT 今日專串'};
const stored=(()=>{try{return JSON.parse(sessionStorage.getItem('hvMulti')||'[]')}catch{return []}})();
const state={multi:Array.isArray(stored)?stored.filter(x=>typeof x==='string'&&/^[\w-]{11}$/.test(x)):[],offset:0};
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
function single(id,target='single-player'){if(!id){if($(target))message(target,'請輸入有效的 YouTube 網址或影片 ID。');return}if(!$(target)){openStandaloneViewer([id],{pttMode:'video'});return}$(target).replaceChildren(frame(id))}
function renderMulti(){sessionStorage.setItem('hvMulti',JSON.stringify(state.multi))}

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


function route(r){
 // Hash query belongs to the session, not the route key.
 r=String(r||'').split('?')[0];
 if(!names[r])r='home';
 // A viewing route without mounted players must never display an empty workspace.
 if(r==='custom-session'&&!viewing.ids.length){
  const params=new URLSearchParams(location.hash.split('?').slice(1).join('?'));
  let recoverable=params.getAll('stream').some(id=>/^[A-Za-z0-9_-]{11}$/.test(id));
  try{const saved=JSON.parse(sessionStorage.getItem('hvCustomViewing')||'null');recoverable=recoverable||(Array.isArray(saved?.ids)&&saved.ids.some(id=>typeof id==='string'&&/^[A-Za-z0-9_-]{11}$/.test(id)));}catch{}
  if(!recoverable)r='single';
 }
 const pageId=r==='ptt-focus'?'ptt':r;
 document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id===pageId));
 const activeNav=r==='custom-session'?'single':pageId;
 document.querySelectorAll('[data-route]').forEach(el=>el.classList.toggle('active',el.dataset.route===activeNav));
 document.querySelectorAll('[data-mobile-route]').forEach(el=>el.classList.toggle('active',el.dataset.mobileRoute===activeNav));
 updateClientTopbar(r);$('mobileNav').hidden=true;$('mobileNavButton').setAttribute('aria-expanded','false');
 // Preserve session stream parameters while entering the player.
 const sessionHash=r==='custom-session'&&viewing.ids.length
  ?'#custom-session?'+new URLSearchParams([
    ...viewing.ids.map(id=>['stream',id]),
    ['layout',viewing.layout],['primary',String(viewing.primary)],
    ['audio',String(viewing.audio)],['ptt',viewing.ptt||'video']
   ]).toString()
  :r==='custom-session'&&location.hash.startsWith('#custom-session?')?location.hash:'#'+r;
 history.replaceState(null,'',sessionHash);
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
 if(r==='home')loadHome();
 if(r==='history')loadHistory();
 if(r==='ptt'||r==='ptt-focus')loadPtt();
 if(r==='single')loadCustomLibrary();
 if(r==='multi')loadCollab();
}
async function api(path){if(!config.apiBase||!/^https:\/\//.test(config.apiBase))throw Error('尚未設定正式 Worker API');const base=config.apiBase.replace(/\/$/,'');const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});if(!response.ok)throw Error('API HTTP '+response.status);return response.json()}
function catalogCard(item,container){if(!item||! /^[\w-]{11}$/.test(item.video_id||''))return;const card=node('div',undefined,'card');card.append(node('strong',String(item.title||item.video_id)));card.append(node('p',String(item.channel_name||item.lifecycle_state||''),'sub'));const btn=node('button','單人觀看');btn.onclick=()=>openStandaloneViewer([item.video_id],{pttMode:'video'});card.append(btn);card.append(' ');const multi=node('button','加入多人','secondary');multi.onclick=()=>{if(!state.multi.includes(item.video_id))state.multi.push(item.video_id);renderMulti();openStandaloneViewer(state.multi.slice(),{pttMode:'video'})};card.append(multi);container.append(card)}
const HOME_FILTER_KEY='holoviewer-live-filter';
const HOME_FILTERS=new Set(['hololive','holostars','mekpark','all']);
const selectedHomeVideos=new Set();
const historyVodWindows=new Map();
const PTT_ARCHIVE_ANCHOR='youtube-liveStreamingDetails-actualStartTime';
function trustedArchiveWindow(item){
 const videoId=String(item?.video_id||'');
 const start=String(item?.actual_start||'');
 const end=String(item?.actual_end||'');
 const startMs=Date.parse(start),endMs=Date.parse(end);
 if(!/^[A-Za-z0-9_-]{11}$/.test(videoId)||!Number.isFinite(startMs)||!Number.isFinite(endMs)||endMs<=startMs)return null;
 return {videoId,start,end,anchorSource:PTT_ARCHIVE_ANCHOR};
}
function archiveScheduledStart(item,window){
 const scheduledStart=String(item?.scheduled_start||'');
 const scheduledMs=Date.parse(scheduledStart),actualMs=Date.parse(String(window?.start||''));
 return Number.isFinite(scheduledMs)&&Number.isFinite(actualMs)&&Math.abs(scheduledMs-actualMs)<=43200000?scheduledStart:'';
}
function appendArchiveWindow(query,window){
 if(!window)return;
 query.append('ptt_window',[window.videoId,window.start,window.end,window.anchorSource,window.scheduledStart||''].join('|'));
}
async function resolveVideoMetadata(id){
 try{
  const result=await window.HoloViewerVideoMetadata?.resolve(id,{
   apiBase:config.apiBase,preferCatalog:true,waitForRecovery:false,maxAttempts:1
  });
  return result?.status==='ready'?result.row:null;
 }catch{return null}
}
async function resolveVodWindow(id){
 const row=await resolveVideoMetadata(id);
 if(!row||String(row?.lifecycle_state||row?.state||'').toLowerCase()!=='ended')return null;
 const window=trustedArchiveWindow({...row,video_id:String(row?.video_id||id)});
 if(!window)return null;
 window.scheduledStart=archiveScheduledStart(row,window);
 return window;
}
function homeFilter(){try{const x=localStorage.getItem(HOME_FILTER_KEY);return HOME_FILTERS.has(x)?x:'hololive'}catch{return 'hololive'}}
function setHomeFilter(value){if(!HOME_FILTERS.has(value))return;try{localStorage.setItem(HOME_FILTER_KEY,value)}catch{}applyHomeFilter(value)}
function applyHomeFilter(value=homeFilter()){
 document.querySelectorAll('#homeDynamic .stream-card').forEach(card=>{card.hidden=value!=='all'&&card.dataset.group!==value});
 document.querySelectorAll('#live-channel-list .live-channel-rail-item').forEach(card=>{card.hidden=(value!=='all'&&card.dataset.group!==value)||(watchMode==='multi'&&viewing.ids.includes(card.dataset.liveVideoId))});
 document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.classList.toggle('active',button.dataset.filter===value));
}
function homeSelection(){
 document.querySelectorAll('#homeDynamic .stream-card[data-multiview-id],#historyDynamic .stream-card[data-multiview-id]').forEach(card=>{const on=selectedHomeVideos.has(card.dataset.multiviewId);card.classList.toggle('multi-selected',on);card.setAttribute('aria-selected',String(on))});
 const count=selectedHomeVideos.size;for(const [bar,countEl,watch] of [['multiSelectBar','multiSelectCount','multiWatch'],['historyMultiSelectBar','historyMultiSelectCount','historyMultiWatch']]){
  $(bar).hidden=!count;$(countEl).textContent='已選 '+count+' 個影片';$(watch).textContent=count>1?'開始多視角觀看':'觀看選取影片';
 }
}
function standaloneViewerUrl(ids,{vodWindows=null,pttMode=''}={}){
 const clean=[...new Set(ids.filter(id=>/^[A-Za-z0-9_-]{11}$/.test(String(id||''))))];
 if(!clean.length)return '';
 const q=new URLSearchParams();
 clean.forEach(id=>q.append('stream',id));
 q.set('layout','equal');
 q.set('primary','0');
 q.set('audio','0');
 q.set('mode',clean.length>1?'multi':'single');
 if(pttMode==='live'||pttMode==='video')q.set('ptt',pttMode);
 if(vodWindows)clean.forEach(id=>appendArchiveWindow(q,vodWindows.get(id)));
 return '/viewer/?'+q.toString();
}
function openStandaloneViewer(ids,options={}){
 const href=standaloneViewerUrl(ids,options);
 if(href)location.href=href;
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
 const raw=String(item?.start_at||item?.actual_start||item?.scheduled_start||'').trim();
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
  return ['yt3.ggpht.com','yt3.googleusercontent.com','i.ytimg.com'].includes(u.hostname)?u.href:'';
 }catch{return ''}
}
function homeAvatarChild(item,name){
 const url=homeAvatarUrl(item);
 if(url){const img=node('img',undefined,'channel-avatar-img');img.src=url;img.alt='';img.loading='lazy';return img}
 const first=[...name].find(c=>/[a-zA-Z0-9]/.test(c))||'H';
 return node('span',first.toUpperCase(),'channel-avatar-fallback');
}

function homeDisplayMetadataByChannel(rows){
 const byChannel=new Map();
 for(const row of Array.isArray(rows)?rows:[]){
  const channelId=String(row?.channel_id||'');
  if(!channelId||byChannel.has(channelId))continue;
  byChannel.set(channelId,row);
 }
 return byChannel;
}
function historyDisplayRow(item,byChannel){
 const channelId=String(item?.channel_id||'');
 const profile=byChannel?.get(channelId);
 if(!profile)return item;
 return {
  ...item,
  channel_name:item.channel_name||profile.channel_name||profile.channel_title||'',
  channel_title:item.channel_title||profile.channel_title||profile.channel_name||'',
  avatar_url:item.avatar_url||profile.avatar_url||'',
  member_accent:item.member_accent||profile.member_accent||'',
  member_accent_dual:Array.isArray(item.member_accent_dual)&&item.member_accent_dual.length?item.member_accent_dual:profile.member_accent_dual,
  support_mode:item.support_mode||profile.support_mode||'',
  support_color_source:item.support_color_source||profile.support_color_source||null,
  group:item.group||profile.group||profile.channel_group||item.channel_group||'other'
 };
}

let homeCollabEvents=[],homeCollabByVideo=new Map();
function collabEventStreams(event){
 return Array.isArray(event?.streams)?event.streams.filter(x=>x&&/^[A-Za-z0-9_-]{11}$/.test(String(x.video_id||''))):[];
}
function collabEventMap(data,historyDay=''){
 const events=data?.schema_version==='public-experience-v1'&&data?.kind==='collab'&&Array.isArray(data.events)?data.events:[];
 const map=new Map();
 for(const raw of events){
  const event=historyDay?{...raw,_history_day:historyDay}:raw;
  if(collabEventStreams(event).length<2)continue;
  for(const stream of collabEventStreams(event))map.set(stream.video_id,event);
 }
 return map;
}
function setHomeCollabEvents(data){
 const events=data?.schema_version==='public-experience-v1'&&data?.kind==='collab'&&Array.isArray(data.events)?data.events:[];
 homeCollabEvents=events.filter(event=>collabEventStreams(event).length>1);
 homeCollabByVideo=collabEventMap(data);
}
function collabDetailUrl(event){
 const eventId=String(event?.event_id||'');if(!eventId||!config.apiBase)return '';
 return config.apiBase.replace(/\/$/,'')+'/v1/collab/events/'+encodeURIComponent(eventId);
}
function verifiedTimelineStartsForEvent(event){
 if(event?.sync?.available!==true)return {};
 const starts={};
 for(const stream of collabEventStreams(event)){
  const seconds=Date.parse(String(stream.actual_start||''))/1000;
  if(Number.isFinite(seconds))starts[stream.video_id]=seconds;
 }
 return starts;
}
function openStandaloneCollab(event){
 const roster=collabEventStreams(event);
 if(roster.length<2)return;
 const isLive=roster.some(x=>['live','upcoming','waiting'].includes(String(x.lifecycle_state||'').toLowerCase()));
 const initial=isLive
  ?roster.filter(x=>String(x.lifecycle_state||'').toLowerCase()==='live')
  :roster;
 const fallback=isLive&&initial.length===0
  ?roster.filter(x=>['upcoming','waiting'].includes(String(x.lifecycle_state||'').toLowerCase()))
  :initial;
 const ids=(fallback.length?fallback:roster).map(x=>x.video_id).slice(0,16);
 const q=new URLSearchParams();
 ids.forEach(id=>q.append('stream',id));
 q.set('layout','equal');
 q.set('workspace','sidebar');
 q.set('ptt',isLive?'live':'video');
 q.set('primary','0');
 q.set('audio','0');
 q.set('mode','multi');
 q.set('collab_event',String(event.event_id||''));
 q.set('collab_kind',isLive?'live':'vod');
 if(!isLive){
  if(event?.sync?.available===true)q.set('collab_sync','verified');
  for(const row of roster){
   const window=trustedArchiveWindow(row);
   if(window)appendArchiveWindow(q,{...window,scheduledStart:archiveScheduledStart(row,window)});
  }
 }
 const collabDay=String(event._history_day||event.day||'');
 if(/^\d{4}-\d{2}-\d{2}$/.test(collabDay))q.set('collab_day',collabDay);
 location.href='/viewer/?'+q.toString();
}
function openCollabEvent(event){openStandaloneCollab(event)}
function collabEntry(event){
 const streams=collabEventStreams(event);
 if(streams.length<2)return null;
 const entry=node('span',undefined,'stream-collab-entry');
 entry.dataset.collabEventId=String(event.event_id||'');
 entry.setAttribute('role','button');
 entry.tabIndex=0;
 entry.title='開啟多人連動';
 entry.append(node('span','👥','collab-glyph'),node('span','多人','collab-entry-label'));
 entry.querySelector('.collab-glyph').setAttribute('aria-hidden','true');
 entry.onclick=e=>{e.preventDefault();e.stopPropagation();openStandaloneCollab(event)};
 entry.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();openStandaloneCollab(event)}};
 return entry;
}
function homeLifecycleBucket(item){
 const lifecycle=String(item?.lifecycle_state||'unknown').toLowerCase();
 if(lifecycle==='live')return item?.stale===true?'unknown':'live';
 if(lifecycle==='unknown')return 'unknown';
 if(lifecycle==='upcoming'||lifecycle==='waiting')return 'upcoming';
 if(lifecycle==='ended')return 'ended';
 return 'unknown';
}
function homeCard(item,container,{collabMap=homeCollabByVideo,history=false}={}){
 if(!item||! /^[A-Za-z0-9_-]{11}$/.test(item.video_id||''))return;
 if(history&&String(item.lifecycle_state||item.state||'').toLowerCase()!=='ended')return;
 const id=item.video_id;const lifecycle=String(item.lifecycle_state||'unknown').toLowerCase();
 const lifecycleBucket=homeLifecycleBucket(item);
 const group=String(item.group||item.channel_group||'other').toLowerCase();
 const archiveWindow=history?trustedArchiveWindow(item):null;
 if(history&&archiveWindow)historyVodWindows.set(id,{...archiveWindow,scheduledStart:archiveScheduledStart(item,archiveWindow)});
 const href=standaloneViewerUrl([id],{vodWindows:history?historyVodWindows:null,pttMode:history?'video':''});
 const card=node('a',undefined,'client-card stream-card');card.href=href;card.dataset.group=group;card.id='stream-'+id;
 applyHomeSupportStyle(card,item);
 const states={live:['LIVE','live'],waiting:['等待中','upcoming'],upcoming:['即將開始','upcoming'],ended:['已結束','ended'],unknown:['狀態待更新','']};
 const status=lifecycleBucket==='unknown'?states.unknown:(states[lifecycle]||states.unknown);
 if(lifecycleBucket!=='unknown'){card.dataset.multiviewId=id;card.setAttribute('aria-selected','false')}
 const thumb=node('div',undefined,'card-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
 const youTube=node('span','YouTube ↗','youtube-source-link');youTube.role='link';youTube.tabIndex=0;youTube.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;thumb.append(youTube);
 const overlay=node('div',undefined,'thumb-overlay');
 if(!history)overlay.append(node('span',status[0],'thumb-badge '+status[1]));
 const time=homeStartLabel(item);overlay.append(node('span',time,'thumb-time'));thumb.append(overlay);card.append(thumb);
 const meta=node('div',undefined,'yt-meta');const ring=node('span',undefined,'channel-avatar-ring');const name=String(item.channel_title||item.channel_name||'頻道資訊待補');
 ring.append(homeAvatarChild(item,name));meta.append(ring);
 const copy=node('div',undefined,'yt-copy');copy.append(node('h3',String(item.title||id),'stream-title'));copy.append(node('div',name,'channel-name'));meta.append(copy);card.append(meta);
 const collab=collabMap.get(id);const collabButton=collabEntry(collab);if(collabButton)card.append(collabButton);
 card.addEventListener('click',event=>{
  if(event.target.closest('.stream-collab-entry'))return;
  const source=event.target.closest('[data-youtube-href]');
  if(source){event.preventDefault();event.stopPropagation();window.open(source.dataset.youtubeHref,'_blank','noopener,noreferrer');return}
  event.preventDefault();if(!card.dataset.multiviewId){openStandaloneViewer([id]);return}
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
 if(bestScore&&homeLifecycleBucket(item)==='live')bestScore+=5;
 return {score:bestScore,label:bestLabel};
}
function chooseHomeHighlights(rows){
 const seen=new Set();const candidates=[];
 for(const row of rows){
  const id=String(row?.video_id||'');
  if(!/^[A-Za-z0-9_-]{11}$/.test(id)||seen.has(id))continue;
  seen.add(id);
  const bucket=homeLifecycleBucket(row);
  if(bucket!=='live'&&bucket!=='upcoming')continue;
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
   const link=node('a');link.href=standaloneViewerUrl([pick.row.video_id],{pttMode:'video'});
   link.append(node('strong',pick.label),document.createTextNode(' · '+String(pick.row.channel_title||pick.row.channel_name||'Hololive')+'：'+String(pick.row.title||'')));
   link.onclick=e=>{e.preventDefault();openStandaloneViewer([pick.row.video_id],{pttMode:'video'})};
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
  const card=node('a',undefined,'home-highlight');card.href=standaloneViewerUrl([id],{pttMode:'video'});
  card.onclick=e=>{if(e.target.closest('[data-youtube-href]'))return;e.preventDefault();openStandaloneViewer([id],{pttMode:'video'})};
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

const HOME_CATALOG_CACHE_KEY='holoviewer-home-catalog-v1';
let homeLoadInFlight=false;
let homeCatalogRows=[];
function readHomeCatalogCache(){
 try{
  const cached=JSON.parse(sessionStorage.getItem(HOME_CATALOG_CACHE_KEY)||'null');
  if(!cached||cached.day!==taipeiDay()||!Array.isArray(cached.rows))return [];
  return cached.rows;
 }catch{return []}
}
function writeHomeCatalogCache(rows){
 try{sessionStorage.setItem(HOME_CATALOG_CACHE_KEY,JSON.stringify({day:taipeiDay(),savedAt:Date.now(),rows}))}catch{}
}
function renderHomeRows(rows){
 homeCatalogRows=rows;
 customCatalogCache=rows;
 window.hvCustomCatalog?.(rows);
 const buckets=homeBuckets(rows);
 for(const key of Object.keys(buckets)){
  const el=$('home-'+key);
  el.replaceChildren();
  if(key==='unknown'){
   $('home-unknown-section').hidden=true;
   continue;
  }
  buckets[key].forEach(item=>homeCard(item,el));
  $('home-'+key+'-section').hidden=!el.children.length;
 }
 const allowed=new Set(rows.map(item=>item.video_id));
 for(const id of selectedHomeVideos){if(!allowed.has(id))selectedHomeVideos.delete(id)}
 homeSelection();
 homeRail(buckets.live);
 renderHomeHighlights(rows);
 applyHomeFilter();
 $('home-empty').textContent=rows.length?'':'目前沒有今天的直播資料。';
 document.documentElement.classList.add('home-hydrated');
}
function homeTimestamp(item,fields){
 for(const field of fields){
  const raw=String(item?.[field]||'').trim();
  if(!raw)continue;
  const ms=Date.parse(raw);
  if(Number.isFinite(ms))return ms;
 }
 return null;
}
function homeStartTimestamp(item){return homeTimestamp(item,['actual_start','scheduled_start','start_at'])}
function homeEndTimestamp(item){return homeTimestamp(item,['actual_end','end_at'])}
function homeStableId(item){return String(item?.video_id||'')}
function homeBuckets(rows){
 const buckets={live:[],upcoming:[],unknown:[],ended:[]};
 rows.forEach(item=>{
  buckets[homeLifecycleBucket(item)].push(item);
 });
 const chronological=(a,b)=>{
  const at=homeStartTimestamp(a),bt=homeStartTimestamp(b);
  if(at===null&&bt!==null)return 1;
  if(at!==null&&bt===null)return -1;
  if(at!==null&&bt!==null&&at!==bt)return at-bt;
  return homeStableId(a).localeCompare(homeStableId(b));
 };
 buckets.live.sort(chronological);
 buckets.upcoming.sort(chronological);
 buckets.unknown.sort(chronological);
 buckets.ended.sort((a,b)=>{
  const ae=homeEndTimestamp(a),be=homeEndTimestamp(b);
  const aVerified=ae!==null,bVerified=be!==null;
  if(aVerified!==bVerified)return aVerified?-1:1;
  const av=aVerified?ae:homeStartTimestamp(a);
  const bv=bVerified?be:homeStartTimestamp(b);
  if(av===null&&bv!==null)return 1;
  if(av!==null&&bv===null)return -1;
  if(av!==null&&bv!==null&&av!==bv)return bv-av;
  return homeStableId(b).localeCompare(homeStableId(a));
 });
 return buckets;
}
async function loadHomeCollab(){
 try{
  const collabData=await api('/v1/collab/live');
  setHomeCollabEvents(collabData);
  if(homeCatalogRows.length)renderHomeRows(homeCatalogRows);
 }catch{}
}
async function loadHome(){
 if(homeLoadInFlight)return;
 const cachedRows=homeCatalogRows.length?[]:readHomeCatalogCache();
 if(cachedRows.length)renderHomeRows(cachedRows);
 if(!config.apiBase){
  document.documentElement.classList.add('home-hydrated');
  $('home-empty').textContent='正式直播資料 API 尚未接通。';
  return;
 }
 homeLoadInFlight=true;
 if(!cachedRows.length)$('home-empty').textContent='';
 try{
  const data=await api('/v1/catalog/today');
  const rows=data.streams||data.items;
  if(!Array.isArray(rows))throw Error('資料格式錯誤');
  writeHomeCatalogCache(rows);
  renderHomeRows(rows);
  $('connection').textContent='API 已連線';
  loadHomeCollab();
 }catch(e){
  document.documentElement.classList.add('home-hydrated');
  if(!homeCatalogRows.length)$('home-empty').textContent='無法讀取正式直播資料：'+e.message;
 }
 finally{homeLoadInFlight=false}
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
 if($('history').classList.contains('active'))updateClientTopbar('history');
}
async function loadHistory(){
 historyChrome();const day=$('historyDate').value;const error=$('history-error');error.hidden=true;error.textContent='';
 const list=$('history-list');list.replaceChildren();const pagination=$('history-pagination');pagination.replaceChildren();$('history-empty').hidden=true;
 if(!config.apiBase){error.textContent='History 正式 API 尚未接通。';error.hidden=false;return}
 try{
  const historyPromise=api('/v1/history?day='+encodeURIComponent(day)+'&limit=50&offset='+state.offset);
  const collabPromise=api('/v1/collab/history?day='+encodeURIComponent(day)+'&limit=100&offset=0').catch(()=>null);
  const catalogPromise=homeCatalogRows.length
   ?Promise.resolve({streams:homeCatalogRows})
   :api('/v1/catalog/today').catch(()=>null);
  const [data,collabData,catalogData]=await Promise.all([historyPromise,collabPromise,catalogPromise]);
  if(!Array.isArray(data.items))throw Error('資料格式錯誤');
  const catalogRows=Array.isArray(catalogData?.streams||catalogData?.items)?(catalogData.streams||catalogData.items):[];
  const displayByChannel=homeDisplayMetadataByChannel(catalogRows);
  const endedItems=data.items.map(item=>historyDisplayRow({...item,lifecycle_state:'ended'},displayByChannel));
  const historyCollabByVideo=collabData?collabEventMap(collabData,day):new Map();
  historyVodWindows.clear();
  endedItems.forEach(item=>homeCard(item,list,{collabMap:historyCollabByVideo,history:true}));
  const ids=new Set(endedItems.map(item=>item.video_id));for(const id of selectedHomeVideos){if(!ids.has(id))selectedHomeVideos.delete(id)}homeSelection();
  const total=Number(data.total||0);if(!endedItems.length)$('history-empty').hidden=false;
  if(!collabData&&endedItems.length){error.textContent='歷史直播已載入；多人連動資料暫時無法讀取。';error.hidden=false}
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
 const ordered=streams.slice().sort((a,b)=>Date.parse(a.actual_start||a.scheduled_start||a.start_at||0)-Date.parse(b.actual_start||b.scheduled_start||b.start_at||0)||String(a.video_id).localeCompare(String(b.video_id)));
 const first=ordered[0],status=collabEventState(event);
 const card=node('a',undefined,'collab-event-card '+status);card.href='#custom-session';
 card.onclick=e=>{e.preventDefault();if(e.target.closest('[data-youtube-href]'))return;openCollabEvent(event)};
 const thumb=node('div',undefined,'collab-event-thumb');const img=node('img');img.src='https://i.ytimg.com/vi/'+first.video_id+'/hqdefault.jpg';img.alt='';img.loading='lazy';thumb.append(img);
 const youtube=node('span','YouTube ↗','youtube-source-link');youtube.role='link';youtube.tabIndex=0;youtube.dataset.youtubeHref='https://www.youtube.com/watch?v='+first.video_id;
 youtube.onclick=e=>{e.preventDefault();e.stopPropagation();window.open(youtube.dataset.youtubeHref,'_blank','noopener,noreferrer')};
 youtube.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();window.open(youtube.dataset.youtubeHref,'_blank','noopener,noreferrer')}};
 thumb.append(youtube);
 thumb.append(node('span',status==='live'?'LIVE':status==='upcoming'?'稍後':'已結束','status-pill '+status));card.append(thumb);
 const dateTimes=streams.map(x=>Date.parse(x.actual_start||x.scheduled_start||x.start_at||'')).filter(Number.isFinite);
 const dateLabel=dateTimes.length?new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(Math.max(...dateTimes)):'日期未明';
 const copy=node('div',undefined,'collab-event-copy');const kicker=node('div',undefined,'collab-event-kicker');
 kicker.append(node('span',dateLabel),node('span',String(event.confidence||'candidate')));copy.append(kicker);
 copy.append(node('h3',String(event.label||'多人連動').replace(/候選/g,'').replace(/[ ·]+$/g,'')||'多人連動'));
 const avatars=node('div',undefined,'collab-avatars'),seenChannels=new Set();
 for(const stream of ordered){
  const channel=String(stream.channel_id||stream.channel_name||stream.video_id);if(seenChannels.has(channel))continue;seenChannels.add(channel);
  const avatar=node('span',undefined,'collab-avatar');avatar.title=String(stream.channel_name||'');
  const url=homeAvatarUrl(stream);if(url){const av=node('img');av.src=url;av.alt='';av.loading='lazy';avatar.append(av)}else avatar.append(node('span',(String(stream.channel_name||'H')[0]||'H').toUpperCase()));
  avatars.append(avatar);
 }
 copy.append(avatars);
 const live=streams.filter(x=>x.lifecycle_state==='live').length;
 const upcoming=streams.filter(x=>['upcoming','waiting'].includes(x.lifecycle_state)).length;
 const ended=streams.filter(x=>x.lifecycle_state==='ended').length;
 const parts=[streams.length+' 個 POV'];
 if(live)parts.push(live+' 個直播中');
 if(upcoming)parts.push(upcoming+' 個稍後開始');
 if(ended)parts.push(ended+' 個已結束');
 copy.append(node('p',parts.join(' · ')+' · 進入多人連動畫面'));card.append(copy);return card;
}
function collabHistoryBounds(){
 const today=taipeiDay();
 return {earliest:shiftDay(today,-30),latest:shiftDay(today,-1)};
}
function collabHistoryDateValid(day){
 const b=collabHistoryBounds();
 return /^\d{4}-\d{2}-\d{2}$/.test(day)&&day>=b.earliest&&day<=b.latest;
}
async function loadCollabHistory(day){
 const bounds=collabHistoryBounds(),input=$('collabHistoryDate');
 input.min=bounds.earliest;input.max=bounds.latest;
 const selected=collabHistoryDateValid(day)?day:(collabHistoryDateValid(input.value)?input.value:bounds.latest);
 input.value=selected;
 const section=$('collab-history'),grid=section.querySelector('.collab-event-grid'),empty=$('collab-history-empty');
 grid.replaceChildren();section.hidden=true;empty.hidden=false;
 empty.textContent='讀取 '+selected.replaceAll('-','/')+' 多人連動中…';
 $('collab-history-heading').textContent=selected.replaceAll('-','/')+' 歷史連動';
 try{
  const data=await api('/v1/collab/history?day='+encodeURIComponent(selected)+'&limit=50&offset=0');
  const events=Array.isArray(data?.events)?data.events:[];
  for(const raw of events){
   const event={...raw,_history_day:selected};
   const card=collabEventCard(event);
   if(card)grid.append(card);
  }
  section.hidden=!grid.children.length;
  empty.hidden=Boolean(grid.children.length);
  if(!grid.children.length)empty.textContent=selected.replaceAll('-','/')+' 沒有偵測到多人連動。';
 }catch(e){
  empty.hidden=false;empty.textContent='歷史多人連動暫時無法讀取：'+e.message;
 }
}
async function loadCollab(){
 for(const id of ['collab-live','collab-upcoming','collab-ended']){
  const section=$(id);section.hidden=true;section.querySelector('.collab-event-grid').replaceChildren();
 }
 $('collab-empty').hidden=false;$('collab-empty').textContent='讀取多人連動中…';
 const bounds=collabHistoryBounds(),input=$('collabHistoryDate');
 input.min=bounds.earliest;input.max=bounds.latest;if(!collabHistoryDateValid(input.value))input.value=bounds.latest;
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
 await loadCollabHistory(input.value);
}
$('collab-history-picker').onsubmit=event=>{event.preventDefault();loadCollabHistory($('collabHistoryDate').value)};

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
}
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
   if(wasEmpty||nearBottom){pttFollowing=true;requestAnimationFrame(()=>requestAnimationFrame(()=>pttToLatest(true)))}
   else{list.scrollTop=previousScroll;latest.hidden=false}
  }
 }catch(e){
  meta.textContent=today.replaceAll('-','/')+' · 後端暫未就緒 · 60 秒後重試 · 純 PTT 閱讀';
  if(!pttLastGoodCount){
   list.hidden=true;empty.hidden=false;latest.hidden=true;
   empty.textContent='今日 PTT 後端資料暫未就緒；頁面會每 60 秒自動重試。';
  }
 }finally{pttLoadInFlight=false}
}
pttInitControls();
document.querySelectorAll('#homeDynamic .stream-filter-button').forEach(button=>button.addEventListener('click',()=>setHomeFilter(button.dataset.filter)));
window.addEventListener('storage',event=>{if(event.key===HOME_FILTER_KEY){applyHomeFilter();applyCustomLibraryFilter()}});
$('historyMultiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('historyMultiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openStandaloneViewer(ids,{vodWindows:historyVodWindows,pttMode:'video'})};
$('multiClear').onclick=()=>{selectedHomeVideos.clear();homeSelection()};
$('multiWatch').onclick=()=>{const ids=[...selectedHomeVideos];if(!ids.length)return;openStandaloneViewer(ids)};
$('ptt-refresh').onclick=event=>{event.preventDefault();loadPtt()};
$('ptt-focus').onclick=event=>{event.preventDefault();route($('ptt').classList.contains('active')&&document.body.classList.contains('ptt-focus-mode')?'ptt':'ptt-focus')};
document.querySelectorAll('[data-page-link]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();route(link.dataset.pageLink)}));
let customCatalogCache=null;
const customHistoryCache=new Map();
function customLibraryFilter(){return homeFilter()}
function applyCustomLibraryFilter(value=customLibraryFilter()){
 document.querySelectorAll('#custom-live-picker .live-picker-item,#custom-history-picker .live-picker-item').forEach(card=>{
  card.hidden=value!=='all'&&card.dataset.group!==value;
 });
 document.querySelectorAll('[data-custom-filter]').forEach(button=>{
  button.classList.toggle('active',button.dataset.customFilter===value);
 });
 const liveBox=$('custom-live-picker'),historyBox=$('custom-history-picker');
 const liveVisible=[...liveBox.children].some(card=>!card.hidden);
 const historyVisible=[...historyBox.children].some(card=>!card.hidden);
 if(liveBox.children.length)$('custom-live-empty').hidden=liveVisible;
 if(historyBox.children.length)$('custom-history-empty').hidden=historyVisible;
}
function setCustomLibraryFilter(value){
 if(!HOME_FILTERS.has(value))return;
 setHomeFilter(value);
 applyCustomLibraryFilter(value);
}
let customHistoryLoadInFlight=false;
function customHistoryBounds(){
 const today=taipeiDay();
 return {earliest:shiftDay(today,-30),latest:today};
}
function customHistoryDateValid(day){
 const b=customHistoryBounds();
 return /^\d{4}-\d{2}-\d{2}$/.test(day)&&day>=b.earliest&&day<=b.latest;
}
async function loadCustomLibrary(){
 try{
  if(customCatalogCache===null){
   const data=await api('/v1/catalog/today');
   if(!Array.isArray(data.streams||data.items))throw Error('資料格式錯誤');
   customCatalogCache=data.streams||data.items;
  }
  window.hvCustomCatalog?.(customCatalogCache);
 }catch(e){
  $('custom-live-empty').textContent='無法讀取目前直播：'+e.message;
  $('custom-live-empty').hidden=false;
 }
}
async function loadCustomHistory(day){
 if(customHistoryLoadInFlight)return;
 const bounds=customHistoryBounds();
 const input=$('customHistoryDate');
 input.min=bounds.earliest;input.max=bounds.latest;
 const selected=customHistoryDateValid(day)?day:(customHistoryDateValid(input.value)?input.value:bounds.latest);
 input.value=selected;
 const empty=$('custom-history-empty');
 if(customHistoryCache.has(selected)){
  window.hvCustomHistory?.(customHistoryCache.get(selected),selected);
  return;
 }
 customHistoryLoadInFlight=true;
 empty.hidden=false;empty.textContent='讀取 '+selected.replaceAll('-','/')+' 歷史影片中…';
 try{
  let rows;
  if(selected===taipeiDay()){
   if(customCatalogCache===null){
    const data=await api('/v1/catalog/today');
    if(!Array.isArray(data.streams||data.items))throw Error('資料格式錯誤');
    customCatalogCache=data.streams||data.items;
   }
   rows=homeBuckets(customCatalogCache).ended;
  }else{
   const data=await api('/v1/history?day='+encodeURIComponent(selected)+'&limit=50&offset=0');
   if(!Array.isArray(data.items))throw Error('資料格式錯誤');
   rows=data.items;
  }
  customHistoryCache.set(selected,rows);
  window.hvCustomHistory?.(rows,selected);
 }catch(e){
  empty.hidden=false;empty.textContent='無法讀取歷史影片：'+e.message;
 }finally{customHistoryLoadInFlight=false}
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
window.hvOpenCustomSession=function(ids,opts={}){
 const clean=[...new Set(ids.map(id=>videoId(String(id||''))).filter(Boolean))];
 if(!clean.length)return;
 const savedSession={ids:clean,layout:opts.layout||'auto',ptt:opts.ptt||'video',primary:opts.primary||0,audio:opts.audio||0};
 if(typeof opts.collabPollUrl==='string'&&opts.collabPollUrl)savedSession.collabPollUrl=opts.collabPollUrl;
 if(typeof opts.collabLabel==='string'&&opts.collabLabel)savedSession.collabLabel=opts.collabLabel;
 if(opts.verifiedTimelineStarts&&typeof opts.verifiedTimelineStarts==='object')savedSession.verifiedTimelineStarts=opts.verifiedTimelineStarts;
 if(Array.isArray(opts.streamMetadata)&&opts.streamMetadata.length)savedSession.streamMetadata=opts.streamMetadata;
 try{sessionStorage.setItem('hvCustomViewing',JSON.stringify(savedSession));}catch{}
 viewing.ids=clean;
 viewing.ptt=opts.ptt==='live'?'live':'video';
 viewing.layout=['auto','equal','primary'].includes(opts.layout)?opts.layout:'auto';
 viewing.primary=Math.max(0,Math.min(clean.length-1,Number(opts.primary)||0));
 viewing.audio=Math.max(0,Math.min(clean.length-1,Number(opts.audio)||0));
 replacementTarget=0;
 watchMode=clean.length>1?'multi':'single';

 const section=$('custom-session');
 if(typeof window.render4174SharedViewerDOM!=='function'||typeof window.mount4174SharedViewer!=='function'){
  section.replaceChildren(Object.assign(document.createElement('p'),{className:'form-error',textContent:'4174 viewer transplant assets failed to load.'}));
  route('custom-session');
  return;
 }
 section.replaceChildren(window.render4174SharedViewerDOM(viewing.ptt==='live'));
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
  singlePttKind:viewing.ptt==='live'?'live':'',
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
function navigateSidebarLink(event,destination){
 if(destination==='ptt'){
  // PTT is a standalone route. Keep the accepted sidebar marker, but allow
  // the browser to navigate normally so the SPA does not mount legacy PTT.
  if(event.detail>0)event.currentTarget.blur();
  return;
 }
 event.preventDefault();route(destination);
 // Pointer clicks must not leave :focus-within latched after SPA navigation.
 // Keep keyboard focus for accessible navigation and rail expansion.
 if(event.detail>0)event.currentTarget.blur();
}
document.querySelectorAll('[data-route]').forEach(link=>link.addEventListener('click',event=>navigateSidebarLink(event,link.dataset.route)));document.querySelectorAll('[data-mobile-route]').forEach(link=>link.addEventListener('click',event=>navigateSidebarLink(event,link.dataset.mobileRoute)));document.querySelectorAll('.rail-brand,.mobile-top-brand').forEach(link=>link.addEventListener('click',event=>navigateSidebarLink(event,'home')));$('mobileNavButton').onclick=()=>{const opening=$('mobileNav').hidden;$('mobileNav').hidden=!opening;$('mobileNavButton').setAttribute('aria-expanded',String(opening))};$('history-picker').onsubmit=event=>{event.preventDefault();state.offset=0;loadHistory()};$('historyDate').value=historyBounds().latest;renderMulti();
const hashRoute=location.hash.substring(1).split('?')[0];
const pathRoute=location.pathname==='/history'?'history':
 location.pathname==='/ptt-today'?(new URLSearchParams(location.search).get('focus')==='1'?'ptt-focus':'ptt'):
 location.pathname==='/custom-view'?'single':
 location.pathname==='/collab'?'multi':
 location.pathname==='/watchalong'?'watchalong':
 location.pathname==='/'?'home':'';
route(hashRoute||pathRoute||'home');

const homePollTimer=setInterval(()=>{
 if(!document.hidden&&($('home').classList.contains('active')||$('custom-session').classList.contains('active')))loadHome();
},30000);
const PTT_POLL_MS=60000;
const pttPollTimer=setInterval(()=>{
 if(!document.hidden&&$('ptt').classList.contains('active'))loadPtt();
},PTT_POLL_MS);
document.addEventListener('visibilitychange',()=>{
 if(document.hidden)return;
 if($('home').classList.contains('active')||$('custom-session').classList.contains('active'))loadHome();
 if($('ptt').classList.contains('active'))loadPtt();
});
window.addEventListener('pagehide',()=>{
 clearInterval(homePollTimer);clearInterval(pttPollTimer);
},{once:true});

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
function bindCustomPicker(box){
 box.addEventListener('click',event=>{
  const button=event.target.closest('[data-live-pick]');if(!button)return;
  if(event.target.closest('[data-youtube-href]')){event.preventDefault();event.stopPropagation();window.open('https://www.youtube.com/watch?v='+button.dataset.livePick,'_blank','noopener,noreferrer');return}
  const value=button.dataset.livePick;if(items.includes(value))items.splice(items.indexOf(value),1);else addStream(value);render();
 });
 box.addEventListener('keydown',event=>{
  if(event.key!=='Enter'&&event.key!==' ')return;
  const button=event.target.closest('[data-live-pick]');if(!button)return;
  event.preventDefault();event.stopPropagation();
  if(event.target.closest('[data-youtube-href]')){window.open('https://www.youtube.com/watch?v='+button.dataset.livePick,'_blank','noopener,noreferrer');return}
  button.click();
 });
}
bindCustomPicker(document.getElementById('custom-live-picker'));
bindCustomPicker(document.getElementById('custom-history-picker'));
document.querySelectorAll('[data-custom-filter]').forEach(button=>button.addEventListener('click',()=>setCustomLibraryFilter(button.dataset.customFilter)));
document.querySelectorAll('[data-library-tab]').forEach(tab=>tab.addEventListener('click',()=>{
  const history=tab.dataset.libraryTab==='history';
  document.querySelectorAll('[data-library-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===tab)));
  document.getElementById('liveLibrary').hidden=history;
  document.getElementById('historyLibrary').hidden=!history;
  if(history)loadCustomHistory(document.getElementById('customHistoryDate').value);
}));
document.getElementById('customHistoryDate').addEventListener('change',event=>loadCustomHistory(event.target.value));
document.getElementById('displayMode').onclick=()=>{
  const gallery=document.querySelector('.live-picker-list');if(!gallery)return;
  gallery.classList.toggle('compact');document.getElementById('displayMode').textContent=gallery.classList.contains('compact')?'詳細卡片':'精簡列表';
};
audio.addEventListener('change',()=>{audioId=items[Number(audio.value)]||null;});
document.getElementById('add').onclick=()=>{const value=input.value.trim();if(!value){document.getElementById('custom-error').textContent='請先貼上 YouTube 網址或影片 ID。';document.getElementById('custom-error').hidden=false;return;}if(addStream(value))input.value='';input.focus();};
input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();document.getElementById('add').click();}});
document.getElementById('start').onclick=async()=>{
  if(!items.length){alert('請先加入至少一個影片。');return;}
  const missing=items.filter(id=>!historyVodWindows.has(id));
  if(missing.length){
    await Promise.all(missing.map(async id=>{
      const window=await resolveVodWindow(id);
      if(window)historyVodWindows.set(id,window);
    }));
  }
  const q=new URLSearchParams();items.forEach(v=>q.append('stream',v));
  q.set('layout',items.length===1?'equal':document.getElementById('layout').value);
  const selectedHistory=items.length>0&&items.every(id=>historyVodWindows.has(id));
  const pttMode=selectedHistory?'video':document.getElementById('pttMode').value;
  q.set('ptt',pttMode);
  if(selectedHistory)items.forEach(id=>appendArchiveWindow(q,historyVodWindows.get(id)));
  q.set('primary',String(Math.max(0,items.indexOf(primaryId))));
  q.set('audio',String(Math.max(0,items.indexOf(audioId))));
  q.set('mode',items.length>1?'multi':'single');
  location.href='/viewer/?'+q.toString();
};
render();
applyCustomLibraryFilter();
{
 const bounds=customHistoryBounds(),input=document.getElementById('customHistoryDate');
 input.min=bounds.earliest;input.max=bounds.latest;if(!customHistoryDateValid(input.value))input.value=bounds.latest;
}

function renderCustomLibraryRows(rows,box,empty){
 box.replaceChildren();
 for(const row of rows){
  const id=String(row?.video_id||'');if(!/^[A-Za-z0-9_-]{11}$/.test(id))continue;
  const channel=String(row.channel_title||row.channel_name||'Hololive');const title=String(row.title||id);
  const avatar=String(row.avatar_url||'');
  streamMetadata.set(id,{channel,title,avatar:/^https:\/\/(yt3\.ggpht\.com|i\.ytimg\.com)\//.test(avatar)?avatar:''});
  const card=node('div',undefined,'live-picker-item');card.setAttribute('role','button');card.tabIndex=0;card.dataset.livePick=id;card.dataset.group=String(row.group||row.channel_group||'other').toLowerCase();card.setAttribute('aria-pressed',String(items.includes(id)));
  const cover=node('div');cover.style.position='relative';const img=node('img');img.src='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';img.alt='';img.loading='lazy';cover.append(img);
  const source=node('span','YouTube ↗','youtube-source-link');source.setAttribute('role','link');source.tabIndex=0;source.dataset.youtubeHref='https://www.youtube.com/watch?v='+id;cover.append(source);card.append(cover);
  const label=node('span');const strong=node('strong',channel);label.append(strong,document.createTextNode(' · '+title));card.append(label);box.append(card);
 }
 empty.hidden=box.childElementCount>0;
 applyCustomLibraryFilter();
}
window.hvCustomCatalog=function(rows){
 const liveRows=homeBuckets(Array.isArray(rows)?rows:[]).live;
 renderCustomLibraryRows(liveRows,document.getElementById('custom-live-picker'),document.getElementById('custom-live-empty'));
 render();
};
window.hvCustomHistory=function(rows,day){
 const box=document.getElementById('custom-history-picker'),empty=document.getElementById('custom-history-empty');
 const historyRows=(Array.isArray(rows)?rows:[]).slice().sort((a,b)=>{
  const at=homeStartTimestamp(a),bt=homeStartTimestamp(b);
  if(at===null&&bt!==null)return 1;
  if(at!==null&&bt===null)return -1;
  if(at!==null&&bt!==null&&at!==bt)return bt-at;
  return homeStableId(b).localeCompare(homeStableId(a));
 });
 historyRows.forEach(row=>{
  const window=trustedArchiveWindow(row);
  if(!window)return;
  window.scheduledStart=archiveScheduledStart(row,window);
  historyVodWindows.set(window.videoId,window);
 });
 renderCustomLibraryRows(historyRows,box,empty);
 if(!box.childElementCount){empty.hidden=false;empty.textContent=day.replaceAll('-','/')+' 沒有歷史影片。'}
 render();
};
window.hvCustomAdd=addStream;

})();


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
const watchalongStaticGrid=document.getElementById('watchalongStaticGrid');
const watchalongStaticEmpty=document.getElementById('watchalongStaticEmpty');
const watchalongTodaySection=document.getElementById('watchalong-today');
const watchalongTodayGrid=document.getElementById('watchalongTodayGrid');
const watchalongTodayEmpty=document.getElementById('watchalongTodayEmpty');
const watchalongPastGrid=document.getElementById('watchalongPastGrid');
const watchalongPastEmpty=document.getElementById('watchalongPastEmpty');
function watchalongCandidateTitle(title){
 return /(同時視聴|同時視聽|watch\s*along)/i.test(String(title||''));
}
function watchalongHostLabel(title){
 const text=String(title||'');
 const jp=text.match(/【[^】]*\/([^/【】]+)】\s*$/);
 return jp?.[1]?.trim()||'Hololive';
}
function watchalongProfile(label,rows=[]){
 const key=String(label||'').toLocaleLowerCase();
 const matched=(Array.isArray(rows)?rows:[]).find(row=>{
  const names=[row?.channel_name,row?.channel_title].map(x=>String(x||'').toLocaleLowerCase()).filter(Boolean);
  return names.some(name=>name===key||name.includes(key)||key.includes(name));
 });
 return matched?{...matched,channel_name:matched.channel_name||matched.channel_title||label}:{channel_name:label};
}
function watchalongCardImage(videoId,title,badge=''){
 const thumb=document.createElement('div');thumb.className='watchalong-static-thumb';
 const img=document.createElement('img');
 img.src='https://i.ytimg.com/vi/'+encodeURIComponent(videoId)+'/hqdefault.jpg';
 img.alt=String(title||'');
 img.loading='lazy';thumb.append(img);
 if(badge){const pill=document.createElement('span');pill.className='watchalong-card-badge';pill.textContent=badge;thumb.append(pill)}
 return thumb;
}
function watchalongIdentity(profile,label){
 const identity=document.createElement('div');identity.className='watchalong-card-identity';
 const avatar=document.createElement('span');avatar.className='watchalong-card-avatar';
 const avatarUrl=homeAvatarUrl(profile||{});
 if(avatarUrl){
  const img=document.createElement('img');img.className='channel-avatar-img';img.src=avatarUrl;img.alt='';img.loading='lazy';avatar.append(img);
 }else{
  const fallback=document.createElement('span');fallback.className='watchalong-avatar-fallback';
  const name=String(label||profile?.channel_name||profile?.channel_title||'Holo').trim();
  fallback.textContent=([...[...name]].find(c=>/[A-Za-z0-9一-龠ぁ-んァ-ヶ]/.test(c))||'H').toUpperCase();
  avatar.append(fallback);
 }
 const name=document.createElement('span');name.className='watchalong-card-host';name.textContent=String(label||'Hololive');
 identity.append(avatar,name);return identity;
}
function watchalongLandingCard({videoId,title,day='',detail='',action='開始同時視聽 →',href='',onpick=null,status='',profile=null,hostLabel='',featured=false,compact=false,badge=''}) {
 if(!/^[A-Za-z0-9_-]{11}$/.test(String(videoId||'')))return null;
 const item=profile||{channel_name:hostLabel};
 const label=hostLabel||item.channel_name||item.channel_title||'Hololive';
 const card=document.createElement('a');card.className='watchalong-static-card'+(featured?' watchalong-featured-card':'')+(compact?' watchalong-compact-card':'');
 applyHomeSupportStyle(card,{...item,channel_name:label});
 card.href=href||'#manual';
 if(typeof onpick==='function')card.onclick=event=>{if(event.target.closest('[data-youtube-href]'))return;event.preventDefault();onpick()};
 card.append(watchalongCardImage(videoId,title,badge));
 const body=document.createElement('div');body.className='watchalong-static-body';
 const meta=document.createElement('div');meta.className='watchalong-static-meta';
 if(day){const dayEl=document.createElement('span');dayEl.textContent=String(day);meta.append(dayEl)}
 if(detail){const detailEl=document.createElement('span');detailEl.textContent=String(detail);meta.append(detailEl)}
 if(status){const statusEl=document.createElement('span');statusEl.className='watchalong-card-status';statusEl.textContent=String(status);meta.append(statusEl)}
 const titleEl=document.createElement('strong');titleEl.textContent=String(title||videoId);
 const actions=document.createElement('div');actions.className='watchalong-card-actions';
 const actionEl=document.createElement('span');actionEl.className='watchalong-static-action';actionEl.textContent=action;
 const youtube=document.createElement('span');youtube.className='watchalong-youtube-link';youtube.role='link';youtube.tabIndex=0;youtube.dataset.youtubeHref='https://www.youtube.com/watch?v='+videoId;youtube.textContent='YouTube ↗';
 youtube.onclick=event=>{event.preventDefault();event.stopPropagation();window.open(youtube.dataset.youtubeHref,'_blank','noopener,noreferrer')};
 youtube.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();window.open(youtube.dataset.youtubeHref,'_blank','noopener,noreferrer')}};
 actions.append(actionEl,youtube);
 body.append(meta,watchalongIdentity(item,label),titleEl,actions);card.append(body);return card;
}
function pickWatchalongHost(videoId){
 const input=document.querySelector('#watchalongBuilder input[name="master"]');
 if(!input)return;
 input.value='https://www.youtube.com/watch?v='+videoId;
 document.getElementById('manual')?.scrollIntoView({behavior:'smooth',block:'start'});
 input.focus();
}
async function loadWatchalongLanding(){
 if(!watchalongStaticGrid||!watchalongStaticEmpty)return;
 watchalongStaticGrid.replaceChildren();
 watchalongTodayGrid?.replaceChildren();
 watchalongPastGrid?.replaceChildren();
 try{
  const [manifestResponse,todayResult,recentResult]=await Promise.all([
   fetch('/data/watchalong/manifest.json',{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}}),
   api('/v1/catalog/today').catch(()=>null),
   api('/v1/watchalong/recent?days=90&limit=100').catch(()=>null)
  ]);
  if(!manifestResponse.ok)throw new Error('HTTP '+manifestResponse.status);
  const manifest=await manifestResponse.json();
  if(manifest?.schema_version!=='holoviewer-watchalong-manifest-v1'||!Array.isArray(manifest.events))throw new Error('manifest');
  const todayRows=Array.isArray(todayResult?.streams||todayResult?.items)?(todayResult.streams||todayResult.items):[];
  const curatedHosts=new Set();
  const events=manifest.events.slice().sort((a,b)=>String(b.session_day||'').localeCompare(String(a.session_day||'')));
  for(const entry of events){
   const eventId=String(entry?.event_id||'');
   const videoId=String(entry?.master_video_id||eventId);
   if(!/^[A-Za-z0-9_-]{11}$/.test(eventId)||!/^[A-Za-z0-9_-]{11}$/.test(videoId))continue;
   curatedHosts.add(videoId);
   const hostLabel=watchalongHostLabel(entry.title);
   const profile=watchalongProfile(hostLabel,todayRows);
   const card=watchalongLandingCard({
    videoId,title:String(entry.title||eventId),day:String(entry.session_day||''),
    detail:String(entry.source_count||0)+' 集',hostLabel,profile,featured:true,badge:'HoloDocchi 精選',
    action:'直接開始觀看 →',
    href:'/watchalong-viewer/?watchalong_event='+encodeURIComponent(eventId)
   });
   if(card)watchalongStaticGrid.append(card);
  }
  watchalongStaticEmpty.hidden=watchalongStaticGrid.childElementCount>0;
  if(!watchalongStaticGrid.childElementCount)watchalongStaticEmpty.textContent='目前沒有可直接觀看的精選同時視聽。';

  const recentEvents=recentResult?.schema_version==='public-experience-v1'&&recentResult?.kind==='watchalong'&&Array.isArray(recentResult.events)
   ?recentResult.events:[];
  for(const event of recentEvents){
   const hosts=Array.isArray(event?.hosts)?event.hosts:[];
   const host=hosts.find(row=>/^[A-Za-z0-9_-]{11}$/.test(String(row?.video_id||'')));
   if(!host)continue;
   const videoId=String(host.video_id);
   const label=String(host.label||watchalongHostLabel(event.title)||'Hololive');
   const profile=watchalongProfile(label,todayRows);
   const isCurated=curatedHosts.has(videoId);
   const pastCard=watchalongLandingCard({
    videoId,title:String(event.title||videoId),day:String(event.day||''),
    status:isCurated?'精選已收錄':(event.member_only?'會員限定':'已結束'),
    action:isCurated?'直接開始觀看 →':'使用這場建立 →',
    hostLabel:label,profile,compact:true,
    href:isCurated?'/watchalong-viewer/?watchalong_event='+encodeURIComponent(videoId):'',
    onpick:isCurated?null:()=>pickWatchalongHost(videoId)
   });
   if(pastCard)watchalongPastGrid?.append(pastCard);
  }
  if(watchalongPastEmpty){
   watchalongPastEmpty.hidden=Boolean(watchalongPastGrid?.childElementCount);
   if(!watchalongPastGrid?.childElementCount)watchalongPastEmpty.textContent=recentResult?'目前沒有過去同時視聽直播。':'過去直播暫時無法載入。';
  }

  const candidates=todayRows.filter(row=>watchalongCandidateTitle(row?.title));
  for(const row of candidates){
   const videoId=String(row?.video_id||'');
   const state=String(row?.lifecycle_state||'');
   const status=state==='live'?'直播中':(['upcoming','waiting'].includes(state)?'稍後':'今天');
   const label=String(row?.channel_name||row?.channel_title||'Hololive');
   const card=watchalongLandingCard({
    videoId,title:String(row?.title||videoId),day:taipeiDay(),status,
    hostLabel:label,profile:row,compact:true,action:'使用這場建立 →',onpick:()=>pickWatchalongHost(videoId)
   });
   if(card)watchalongTodayGrid?.append(card);
  }
  if(watchalongTodayEmpty){
   watchalongTodayEmpty.hidden=Boolean(watchalongTodayGrid?.childElementCount);
   if(!watchalongTodayGrid?.childElementCount)watchalongTodayEmpty.textContent='今天目前沒有符合同時視聽辨識規則的直播。';
  }
  if(watchalongTodaySection)watchalongTodaySection.hidden=!watchalongTodayGrid?.childElementCount;
 }catch{
  watchalongStaticGrid.replaceChildren();
  watchalongStaticEmpty.hidden=false;
  watchalongStaticEmpty.textContent='精選同時視聽暫時無法載入。';
  if(watchalongPastEmpty){watchalongPastEmpty.hidden=false;watchalongPastEmpty.textContent='過去同時視聽直播暫時無法載入。'}
  if(watchalongTodayEmpty){watchalongTodayEmpty.hidden=false;watchalongTodayEmpty.textContent='今日同時視聽暫時無法載入。'}
 }
}
loadWatchalongLanding();

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
 const error=document.getElementById('watch-error');
 if(!master){error.textContent='Hololive 主影片無法辨識，請確認 YouTube URL 或 Video ID。';error.hidden=false;return}
 if(form.get('source_kind')==='external'){
  error.textContent='第一版同時視聽先支援 YouTube 片源；外部平台仍保留在 4174 規格，但 Public 暫不啟動。';error.hidden=false;return;
 }
 const q=new URLSearchParams();q.set('host',master);
 if(form.get('youtube_mode')==='playlist'){
  let playlist='';
  try{const u=new URL(String(form.get('playlist')||''));playlist=u.searchParams.get('list')||''}catch{}
  if(!/^[A-Za-z0-9_-]{10,64}$/.test(playlist)){error.textContent='請提供有效的 YouTube Playlist URL。';error.hidden=false;return}
  q.set('playlist',playlist);
  const start=Math.max(1,Number(form.get('playlist_start'))||1);q.set('playlist_start',String(start));
 }else{
  const source=videoId(String(form.get('source')||''));
  if(!source){error.textContent='請提供有效的 YouTube 片源網址或 Video ID。';error.hidden=false;return}
  q.set('source',source);
 }
 error.hidden=true;location.href='/watchalong-viewer/?'+q.toString();
});
})();

// Recover the last explicitly opened session after a tab reload/deep link.
// Without saved valid IDs, route to selection rather than an empty player shell.
(function restoreCustomSession(){
 if(location.hash.split('?')[0]!=='#custom-session')return;
 const params=new URLSearchParams(location.hash.split('?').slice(1).join('?'));
 const urls=params.getAll('stream');
 // An explicit URL is authoritative: never substitute an unrelated saved session.
 const ids=urls.length
  ?[...new Set(urls.filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))]
  :[];
 let saved=null;try{saved=JSON.parse(sessionStorage.getItem('hvCustomViewing')||'null')}catch{}
 const recovered=urls.length?ids:(Array.isArray(saved?.ids)?saved.ids.filter(id=>typeof id==='string'&&/^[A-Za-z0-9_-]{11}$/.test(id)):[]);
 if(!recovered.length){route('single');return;}
 const legacyPtt=urls.length?params.get('ptt'):saved?.ptt;
 openStandaloneViewer(recovered,{pttMode:legacyPtt==='live'?'live':'video'});
})();
