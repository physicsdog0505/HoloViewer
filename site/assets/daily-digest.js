(()=>{
'use strict';

const SCHEMA_VERSION=1;
const KIND='holodocchi.daily_digest';
const TAIPEI='Asia/Taipei';
const DATE_RE=/^\d{4}-\d{2}-\d{2}$/;

function el(tag,className,text){
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined&&text!==null)node.textContent=String(text);
  return node;
}
function text(value){return value===undefined||value===null?'':String(value).trim()}
function taipeiDay(now=new Date()){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:TAIPEI,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const map=Object.fromEntries(parts.map(part=>[part.type,part.value]));
  return map.year+'-'+map.month+'-'+map.day;
}
function displayDay(day){return DATE_RE.test(day)?day.replaceAll('-','/'):day}
function config(){const cfg=window.HOLOVIEWER_CONFIG?.dailyDigest;return cfg&&typeof cfg==='object'?cfg:{}}
function artifactUrl(day){
  const cfg=config();
  const base=text(cfg.base).replace(/\/$/,'');
  const template=text(cfg.pathTemplate);
  if(!template||!DATE_RE.test(day))return '';
  const path=template.replaceAll('{date}',encodeURIComponent(day));
  if(!path.startsWith('/'))return '';
  return base?base+path:path;
}
function verificationLabel(status){
  return {
    verified_content:'已驗證',
    metadata_only:'僅基本資料',
    unverified:'未驗證',
    missing:'缺少資料'
  }[text(status)]||'';
}
function streamMap(artifact){
  return new Map((Array.isArray(artifact?.streams)?artifact.streams:[]).map(row=>[String(row?.video_id||''),row]));
}
function youtubeUrl(videoId){return /^[A-Za-z0-9_-]{11}$/.test(String(videoId||''))?'https://www.youtube.com/watch?v='+videoId:''}
function thumbnailUrl(videoId){return /^[A-Za-z0-9_-]{11}$/.test(String(videoId||''))?'https://i.ytimg.com/vi/'+videoId+'/mqdefault.jpg':''}
function streamReference(videoId,byId){
  const row=byId.get(videoId);
  const card=el('a','daily-stream-ref');
  const href=text(row?.youtube_url)||youtubeUrl(videoId);
  if(href){card.href=href;card.target='_blank';card.rel='noopener noreferrer'}
  const thumb=thumbnailUrl(videoId);
  if(thumb){
    const img=el('img');img.src=thumb;img.alt='';img.loading='lazy';img.referrerPolicy='no-referrer';card.append(img);
  }
  const copy=el('span','daily-stream-ref-copy');
  copy.append(el('strong','',text(row?.channel_name)||videoId));
  copy.append(el('span','',text(row?.title)||videoId));
  const status=text(row?.verification_status);
  if(status)copy.append(el('em','daily-verify daily-verify-'+status,verificationLabel(status)));
  card.append(copy);
  return card;
}
function appendReferences(parent,ids,byId){
  const valid=(Array.isArray(ids)?ids:[]).map(String).filter(id=>byId.has(id));
  if(!valid.length)return;
  const refs=el('div','daily-stream-refs');
  valid.forEach(id=>refs.append(streamReference(id,byId)));
  parent.append(refs);
}
function section(title,className=''){
  const wrap=el('section','daily-v1-section'+(className?' '+className:''));
  wrap.append(el('h2','daily-v1-section-title',title));
  return wrap;
}
function renderCoverage(target,artifact){
  const c=artifact?.coverage;
  if(!c||typeof c!=='object')return;
  const bar=el('div','daily-coverage');
  bar.append(el('span','',String(c.total_streams||0)+' 場直播'));
  bar.append(el('span','daily-verify daily-verify-verified_content',String(c.verified_content||0)+' 已驗證'));
  if(Number(c.metadata_only)>0)bar.append(el('span','daily-verify daily-verify-metadata_only',String(c.metadata_only)+' 僅基本資料'));
  if(Number(c.unverified)>0)bar.append(el('span','daily-verify daily-verify-unverified',String(c.unverified)+' 未驗證'));
  if(Number(c.missing)>0)bar.append(el('span','daily-verify daily-verify-missing',String(c.missing)+' 缺少'));
  target.append(bar);
}
function renderOverview(target,artifact){
  const overview=artifact?.overview||{};
  const wrap=section('今日總覽','daily-overview');
  if(text(overview.summary))wrap.append(el('p','daily-overview-summary',overview.summary));
  const highlights=Array.isArray(overview.highlights)?overview.highlights.filter(Boolean):[];
  if(highlights.length){
    const list=el('ol','daily-highlight-list');
    highlights.forEach(item=>list.append(el('li','',item)));
    wrap.append(list);
  }
  target.append(wrap);
}
function renderStories(target,artifact,byId){
  const stories=Array.isArray(artifact?.stories)?artifact.stories:[];
  if(!stories.length)return;
  const wrap=section('今日主題','daily-stories'),list=el('div','daily-story-list');
  stories.forEach(story=>{
    const card=el('article','daily-story-card'),meta=el('div','daily-story-meta');
    meta.append(el('span','daily-story-rank','#'+String(story.rank||'')));
    const role=text(story?.editorial_signals?.recommended_role);
    if(role)meta.append(el('span','daily-story-role',role==='lead_candidate'?'主題候選':role==='secondary_candidate'?'次要主題':'一般'));
    card.append(meta);
    if(text(story.title))card.append(el('h3','daily-story-title',story.title));
    if(text(story.summary))card.append(el('p','daily-story-summary',story.summary));
    const subs=Array.isArray(story.sub_events)?story.sub_events:[];
    if(subs.length){
      const subWrap=el('div','daily-sub-events');
      subs.forEach(sub=>{
        const item=el('article','daily-sub-event');
        if(text(sub.title))item.append(el('h4','',sub.title));
        if(text(sub.summary))item.append(el('p','',sub.summary));
        appendReferences(item,sub.video_ids,byId);
        subWrap.append(item);
      });
      card.append(subWrap);
    }
    appendReferences(card,story.video_ids,byId);
    list.append(card);
  });
  wrap.append(list);target.append(wrap);
}
function renderAnnouncements(target,artifact,byId){
  const rows=Array.isArray(artifact?.announcements)?artifact.announcements:[];
  if(!rows.length)return;
  const wrap=section('公告與預告','daily-announcements'),grid=el('div','daily-announcement-grid');
  rows.forEach(row=>{
    const card=el('article','daily-announcement-card'),meta=el('div','daily-announcement-meta');
    if(text(row.type))meta.append(el('span','',row.type));
    if(text(row.event_date_text))meta.append(el('span','',row.event_date_text));
    if(meta.childElementCount)card.append(meta);
    if(text(row.title))card.append(el('h3','',row.title));
    if(text(row.summary))card.append(el('p','',row.summary));
    appendReferences(card,row.video_ids,byId);
    grid.append(card);
  });
  wrap.append(grid);target.append(wrap);
}
function renderCategories(target,artifact,byId){
  const rows=Array.isArray(artifact?.categories)?artifact.categories:[];
  if(!rows.length)return;
  const wrap=section('分類','daily-categories');
  rows.forEach(row=>{
    const group=el('details','daily-category');
    group.append(el('summary','',text(row.label)||text(row.key)||'分類'));
    appendReferences(group,row.video_ids,byId);
    wrap.append(group);
  });
  target.append(wrap);
}
function renderUnverified(target,artifact,byId){
  const rows=Array.isArray(artifact?.unverified)?artifact.unverified:[];
  if(!rows.length)return;
  const wrap=section('未驗證項目','daily-unverified');
  wrap.append(el('p','daily-unverified-note','以下內容未取得足以核實直播內容的資料，不視為已驗證資訊。'));
  rows.forEach(row=>{
    const item=el('article','daily-unverified-item'),stream=byId.get(String(row.video_id||''));
    item.append(el('span','daily-verify daily-verify-unverified','未驗證'));
    item.append(el('strong','',text(stream?.channel_name)||String(row.video_id||'')));
    if(text(stream?.title))item.append(el('span','',stream.title));
    if(text(row.reason))item.append(el('p','',row.reason));
    appendReferences(item,[row.video_id],byId);
    wrap.append(item);
  });
  target.append(wrap);
}
function renderArtifact(target,artifact){
  target.replaceChildren();
  const byId=streamMap(artifact);
  renderCoverage(target,artifact);
  renderOverview(target,artifact);
  renderStories(target,artifact,byId);
  renderAnnouncements(target,artifact,byId);
  renderCategories(target,artifact,byId);
  renderUnverified(target,artifact,byId);
  return target.childElementCount>0;
}
async function fetchArtifact(day){
  const url=artifactUrl(day);
  if(!url)return {state:'MISSING',artifact:null,reason:'unconfigured'};
  let response;
  try{response=await fetch(url,{credentials:'omit',cache:day===taipeiDay()?'no-cache':'force-cache'})}
  catch{return {state:'ERROR',artifact:null,reason:'network'}}
  if(response.status===404)return {state:'MISSING',artifact:null,reason:'not_found'};
  if(!response.ok)return {state:'ERROR',artifact:null,reason:'http_'+response.status};
  let artifact;
  try{artifact=await response.json()}catch{return {state:'ERROR',artifact:null,reason:'invalid_json'}}
  if(!artifact||artifact.schema_version!==SCHEMA_VERSION||artifact.kind!==KIND)return {state:'ERROR',artifact:null,reason:'schema'};
  if(text(artifact.target_day)!==day||artifact.timezone!==TAIPEI)return {state:'ERROR',artifact:null,reason:'day_mismatch'};
  return {state:artifact?.coverage?.complete===true?'READY':'PARTIAL',artifact,reason:''};
}
function setStatus(node,message,kind=''){if(!node)return;node.textContent=message;node.dataset.state=kind;node.hidden=!message}
function selectedDay(){const query=new URLSearchParams(location.search).get('date')||'';return DATE_RE.test(query)?query:taipeiDay()}
function setDailyUrl(day){const url=new URL(location.href);url.searchParams.set('date',day);location.href=url.pathname+url.search}
function monthKey(day){return DATE_RE.test(day)?day.slice(0,7):taipeiDay().slice(0,7)}
function shiftMonth(key,delta){const [year,month]=key.split('-').map(Number);const date=new Date(Date.UTC(year,month-1+delta,1,12));return date.getUTCFullYear()+'-'+String(date.getUTCMonth()+1).padStart(2,'0')}
function monthLabel(key){const [year,month]=key.split('-').map(Number);return new Intl.DateTimeFormat('zh-TW',{timeZone:'UTC',year:'numeric',month:'long'}).format(new Date(Date.UTC(year,month-1,1,12)))}
function initDailyDateHub(day,today){
  const dialog=document.getElementById('dailyDigestDateHub'),trigger=document.getElementById('dailyDigestDateTrigger'),grid=document.getElementById('dailyDigestDateGrid'),label=document.getElementById('dailyDigestMonthLabel'),prev=document.getElementById('dailyDigestMonthPrev'),next=document.getElementById('dailyDigestMonthNext'),todayButton=document.getElementById('dailyDigestDateToday'),close=document.getElementById('dailyDigestDateClose');
  if(!dialog||!trigger||!grid||!label)return;
  let month=monthKey(day);trigger.textContent=displayDay(day);
  function render(){
    label.textContent=monthLabel(month);grid.replaceChildren();
    const [year,monthNumber]=month.split('-').map(Number),first=new Date(Date.UTC(year,monthNumber-1,1,12)),start=first.getUTCDay(),days=new Date(Date.UTC(year,monthNumber,0,12)).getUTCDate();
    for(let slot=0;slot<42;slot++){
      const number=slot-start+1;
      if(number<1||number>days){grid.append(el('span','daily-date-hub-day is-empty'));continue}
      const value=month+'-'+String(number).padStart(2,'0'),button=el('button','daily-date-hub-day');
      button.type='button';button.append(el('strong','daily-date-hub-day-number',number));
      if(value===day)button.classList.add('is-selected');
      if(value===today)button.classList.add('is-today');
      if(value>today){button.disabled=true;button.classList.add('is-future')}else button.addEventListener('click',()=>setDailyUrl(value));
      grid.append(button);
    }
    next.disabled=month>=monthKey(today);
  }
  trigger.addEventListener('click',()=>{month=monthKey(day);render();dialog.showModal()});
  prev.addEventListener('click',()=>{month=shiftMonth(month,-1);render()});
  next.addEventListener('click',()=>{if(month<monthKey(today)){month=shiftMonth(month,1);render()}});
  todayButton.addEventListener('click',()=>setDailyUrl(today));
  close.addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});
}
async function initDaily(){
  const root=document.getElementById('daily-digest-page');if(!root)return;
  const content=document.getElementById('daily-digest-content'),status=document.getElementById('daily-digest-status'),title=document.getElementById('daily-digest-date-label');
  const day=selectedDay(),today=taipeiDay();
  if(title)title.textContent=displayDay(day)+' 日報';
  initDailyDateHub(day,today);
  setStatus(status,'正在載入日報…','loading');content.replaceChildren();
  const result=await fetchArtifact(day);
  if(result.state==='READY'||result.state==='PARTIAL'){
    const rendered=renderArtifact(content,result.artifact);
    if(rendered)setStatus(status,result.state==='PARTIAL'?'本日資料尚未完整，未驗證項目不會視為已驗證內容。':'',result.state);
    else setStatus(status,'本日 Daily Digest 沒有可顯示內容。',result.state);
  }else if(result.state==='MISSING')setStatus(status,displayDay(day)+' 日報尚未產生','MISSING');
  else setStatus(status,'日報暫時無法載入','ERROR');
}
window.HOLOVIEWER_DAILY_DIGEST=Object.freeze({schemaVersion:SCHEMA_VERSION,kind:KIND,taipeiDay,fetchArtifact,renderArtifact});
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',initDaily,{once:true});
})();