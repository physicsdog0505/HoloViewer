(()=>{
'use strict';

const SCHEMA='holodocchi.daily_digest.v1';
const TAIPEI='Asia/Taipei';
const DATE_RE=/^\d{4}-\d{2}-\d{2}$/;
const ROLES=new Set(['hero','featured','standard','compact']);

function el(tag,className,text){
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined&&text!==null)node.textContent=String(text);
  return node;
}
function text(value){return value===undefined||value===null?'':String(value).trim()}
function positiveInt(value){
  const n=Number(value);
  return Number.isInteger(n)&&n>0?n:null;
}
function taipeiDay(now=new Date()){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:TAIPEI,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const map=Object.fromEntries(parts.map(part=>[part.type,part.value]));
  return map.year+'-'+map.month+'-'+map.day;
}
function shiftDay(day,delta){
  if(!DATE_RE.test(day))return '';
  const [y,m,d]=day.split('-').map(Number);
  const date=new Date(Date.UTC(y,m-1,d+delta));
  return date.toISOString().slice(0,10);
}
function displayDay(day){return DATE_RE.test(day)?day.replaceAll('-','/') : day}
function displayTime(value){
  const raw=text(value);
  if(!raw)return '';
  const date=new Date(raw);
  if(Number.isNaN(date.getTime()))return '';
  return new Intl.DateTimeFormat('zh-TW',{timeZone:TAIPEI,hour:'2-digit',minute:'2-digit',hour12:false}).format(date);
}
function config(){
  const cfg=window.HOLOVIEWER_CONFIG?.dailyDigest;
  return cfg&&typeof cfg==='object'?cfg:{};
}
function artifactUrl(day){
  const cfg=config();
  const base=text(cfg.base).replace(/\/$/,'');
  const template=text(cfg.pathTemplate);
  if(!base||!template||!DATE_RE.test(day))return '';
  const path=template.replaceAll('{date}',encodeURIComponent(day));
  if(!path.startsWith('/'))return '';
  return base+path;
}
async function fetchArtifact(day){
  const url=artifactUrl(day);
  if(!url)return {state:'MISSING',artifact:null,reason:'unconfigured'};
  let response;
  try{
    response=await fetch(url,{credentials:'omit',cache:day===taipeiDay()?'no-cache':'force-cache'});
  }catch(_error){
    return {state:'ERROR',artifact:null,reason:'network'};
  }
  if(response.status===404)return {state:'MISSING',artifact:null,reason:'not_found'};
  if(!response.ok)return {state:'ERROR',artifact:null,reason:'http_'+response.status};
  let artifact;
  try{artifact=await response.json()}catch(_error){return {state:'ERROR',artifact:null,reason:'invalid_json'}}
  if(!artifact||artifact.schema_version!==SCHEMA)return {state:'ERROR',artifact:null,reason:'schema'};
  const artifactDay=text(artifact.day||artifact.date);
  if(artifactDay!==day)return {state:'ERROR',artifact:null,reason:'day_mismatch'};
  const state=text(artifact.status).toUpperCase();
  if(state==='MISSING')return {state:'MISSING',artifact,reason:'artifact_missing'};
  if(state!=='READY'&&state!=='PARTIAL')return {state:'ERROR',artifact:null,reason:'status'};
  return {state,artifact,reason:''};
}
function itemRole(item){
  const role=text(item?.display_role||item?.layout_role||item?.layout).toLowerCase();
  return ROLES.has(role)?role:'standard';
}
function itemLink(item){
  const candidates=[item?.internal_url,item?.viewer_url,item?.youtube_url,item?.url];
  for(const candidate of candidates){
    const value=text(candidate);
    if(value.startsWith('/')||value.startsWith('https://www.youtube.com/')||value.startsWith('https://youtu.be/'))return value;
  }
  return '';
}
function itemTitle(item){return text(item?.title)||'未命名直播'}
function itemChannel(item){return text(item?.channel_name||item?.channel||item?.talent||item?.member)}
function itemSummary(item){return text(item?.summary)}
function itemReason(item){return text(item?.recommendation_reason||item?.recommendation||item?.highlight_reason)}
function itemState(item){return text(item?.lifecycle_state||item?.state).toLowerCase()}
function itemStart(item){return text(item?.actual_start||item?.actual_start_at||item?.scheduled_start||item?.scheduled_start_at)}
function itemThumbnail(item){return text(item?.thumbnail_url||item?.thumbnail)}
function itemTags(item){
  const raw=Array.isArray(item?.tags)?item.tags:(item?.category?[item.category]:[]);
  return raw.map(text).filter(Boolean);
}
function stateLabel(state){
  return {live:'直播中',upcoming:'即將開始',waiting:'等待中',ended:'已結束'}[state]||'';
}
function createItem(item,{compact=false}={}){
  const card=el('article','daily-digest-card daily-digest-'+itemRole(item));
  const href=itemLink(item);
  const thumb=itemThumbnail(item);
  if(thumb){
    const media=href?el('a','daily-digest-media'):el('div','daily-digest-media');
    if(href){media.href=href;if(href.startsWith('http')){media.target='_blank';media.rel='noopener noreferrer'}}
    const img=el('img');
    img.src=thumb; img.alt=''; img.loading='lazy'; img.referrerPolicy='no-referrer';
    img.addEventListener('error',()=>media.remove());
    media.append(img); card.append(media);
  }
  const body=el('div','daily-digest-card-body');
  const meta=el('div','daily-digest-meta');
  const state=stateLabel(itemState(item));
  const clock=displayTime(itemStart(item));
  const channel=itemChannel(item);
  [state,clock,channel].filter(Boolean).forEach(value=>meta.append(el('span','',value)));
  if(meta.childElementCount)body.append(meta);

  const title=itemTitle(item);
  if(href){
    const titleLink=el('a','daily-digest-title',title); titleLink.href=href;
    if(href.startsWith('http')){titleLink.target='_blank';titleLink.rel='noopener noreferrer'}
    body.append(titleLink);
  }else body.append(el('h3','daily-digest-title',title));

  const reason=itemReason(item);
  if(reason)body.append(el('p','daily-digest-reason',reason));
  if(!compact){
    const summary=itemSummary(item);
    if(summary)body.append(el('p','daily-digest-summary',summary));
  }
  const tags=itemTags(item);
  if(tags.length){
    const tagRow=el('div','daily-digest-tags');
    tags.forEach(tag=>tagRow.append(el('span','',tag)));
    body.append(tagRow);
  }
  const viewers=positiveInt(item?.concurrent_viewers);
  if(viewers&&itemState(item)==='live')body.append(el('p','daily-digest-viewers','👁 '+new Intl.NumberFormat('zh-TW').format(viewers)+' 人正在觀看'));
  card.append(body);
  return card;
}
function normalizedSections(source){
  if(!source||typeof source!=='object')return [];
  if(Array.isArray(source.sections)){
    return source.sections.map((section,index)=>({
      title:text(section?.title||section?.label),
      role:text(section?.layout||section?.display_role||section?.role),
      items:Array.isArray(section?.items)?section.items:[],
      index
    }));
  }
  if(Array.isArray(source.items))return [{title:'',role:text(source.layout||source.display_role),items:source.items,index:0}];
  return [];
}
function renderArtifact(target,artifact,{compact=false,home=false}={}){
  target.replaceChildren();
  const source=home?(artifact.home&&typeof artifact.home==='object'?artifact.home:null):artifact;
  const sections=normalizedSections(source);
  for(const section of sections){
    const wrap=el('section','daily-digest-group');
    if(section.role)wrap.dataset.layout=section.role;
    if(section.title)wrap.append(el('h3','daily-digest-group-title',section.title));
    const grid=el('div','daily-digest-grid');
    section.items.forEach(item=>{if(item&&typeof item==='object')grid.append(createItem(item,{compact}))});
    if(grid.childElementCount){wrap.append(grid);target.append(wrap)}
  }
  return target.childElementCount>0;
}
function setStatus(node,message,kind=''){
  if(!node)return;
  node.textContent=message;
  node.dataset.state=kind;
  node.hidden=!message;
}
async function initHome(){
  if(location.pathname!=='/')return;
  const section=document.getElementById('home-daily-digest');
  const list=document.getElementById('home-daily-digest-content');
  const status=document.getElementById('home-daily-digest-status');
  const dayLabel=document.getElementById('home-daily-digest-day');
  if(!section||!list)return;
  const day=taipeiDay();
  if(dayLabel)dayLabel.textContent=displayDay(day);
  setStatus(status,'正在載入今日精選…','loading');
  const result=await fetchArtifact(day);
  if(result.state==='READY'||result.state==='PARTIAL'){
    const rendered=renderArtifact(list,result.artifact,{compact:true,home:true});
    section.hidden=false;
    if(rendered)setStatus(status,result.state==='PARTIAL'?'今日精選部分內容尚未完整。':'',result.state);
    else setStatus(status,'今日精選已產生，查看完整日報。',result.state);
    return;
  }
  list.replaceChildren();
  if(result.state==='ERROR'){
    section.hidden=false;
    setStatus(status,'今日精選暫時無法載入','ERROR');
  }else{
    section.hidden=true;
    setStatus(status,'','MISSING');
  }
}
function selectedDay(){
  const query=new URLSearchParams(location.search).get('date')||'';
  return DATE_RE.test(query)?query:taipeiDay();
}
function setDailyUrl(day){
  const url=new URL(location.href);
  if(day===taipeiDay())url.searchParams.delete('date');else url.searchParams.set('date',day);
  location.href=url.pathname+url.search;
}
function monthKey(day){return DATE_RE.test(day)?day.slice(0,7):taipeiDay().slice(0,7)}
function shiftMonth(key,delta){
  const [year,month]=key.split('-').map(Number);
  const date=new Date(Date.UTC(year,month-1+delta,1,12));
  return date.getUTCFullYear()+'-'+String(date.getUTCMonth()+1).padStart(2,'0');
}
function monthLabel(key){
  const [year,month]=key.split('-').map(Number);
  return new Intl.DateTimeFormat('zh-TW',{timeZone:'UTC',year:'numeric',month:'long'}).format(new Date(Date.UTC(year,month-1,1,12)));
}
function initDailyDateHub(day,today){
  const dialog=document.getElementById('dailyDigestDateHub');
  const trigger=document.getElementById('dailyDigestDateTrigger');
  const grid=document.getElementById('dailyDigestDateGrid');
  const label=document.getElementById('dailyDigestMonthLabel');
  const prev=document.getElementById('dailyDigestMonthPrev');
  const next=document.getElementById('dailyDigestMonthNext');
  const todayButton=document.getElementById('dailyDigestDateToday');
  const close=document.getElementById('dailyDigestDateClose');
  if(!dialog||!trigger||!grid||!label)return;
  let month=monthKey(day);
  trigger.textContent=displayDay(day);
  function render(){
    label.textContent=monthLabel(month);
    grid.replaceChildren();
    const [year,monthNumber]=month.split('-').map(Number);
    const first=new Date(Date.UTC(year,monthNumber-1,1,12));
    const start=first.getUTCDay();
    const days=new Date(Date.UTC(year,monthNumber,0,12)).getUTCDate();
    for(let slot=0;slot<42;slot++){
      const number=slot-start+1;
      if(number<1||number>days){grid.append(el('span','daily-date-hub-day is-empty'));continue}
      const value=month+'-'+String(number).padStart(2,'0');
      const button=el('button','daily-date-hub-day');
      button.type='button';
      button.append(el('strong','daily-date-hub-day-number',number));
      if(value===day)button.classList.add('is-selected');
      if(value===today)button.classList.add('is-today');
      if(value>today){button.disabled=true;button.classList.add('is-future')}
      else button.addEventListener('click',()=>setDailyUrl(value));
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
  const root=document.getElementById('daily-digest-page');
  if(!root)return;
  const content=document.getElementById('daily-digest-content');
  const status=document.getElementById('daily-digest-status');
  const title=document.getElementById('daily-digest-date-label');
  const day=selectedDay(),today=taipeiDay();
  if(title)title.textContent=displayDay(day)+' 日報';
  initDailyDateHub(day,today);

  setStatus(status,'正在載入今日精選…','loading');
  content.replaceChildren();
  const result=await fetchArtifact(day);
  if(result.state==='READY'||result.state==='PARTIAL'){
    const rendered=renderArtifact(content,result.artifact,{compact:false,home:false});
    if(rendered)setStatus(status,result.state==='PARTIAL'?'本日資料為 PARTIAL，以下顯示目前可用內容。':'',result.state);
    else setStatus(status,'本日 Daily Digest 沒有可顯示項目。',result.state);
  }else if(result.state==='MISSING'){
    setStatus(status,day===today?'今日精選尚未產生':displayDay(day)+' 日報尚未產生','MISSING');
  }else{
    setStatus(status,'今日精選暫時無法載入','ERROR');
  }
}
window.HOLOVIEWER_DAILY_DIGEST=Object.freeze({
  schema:SCHEMA,taipeiDay,shiftDay,displayTime,fetchArtifact,renderArtifact
});
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{initHome();initDaily()},{once:true});
})();