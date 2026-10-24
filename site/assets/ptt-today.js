'use strict';

const config=window.HOLOVIEWER_CONFIG||{};
const PTT_POLL_MS=60000;
const $=id=>document.getElementById(id);
let pttFollowing=true;
let pttProgrammatic=false;
let pttLoadInFlight=false;
let pttLastGoodCount=0;
let pttLastGoodDay='';

function taipeiDay(){
 const parts=new Intl.DateTimeFormat('en-CA',{
  timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'
 }).formatToParts(new Date());
 const out=Object.fromEntries(parts.filter(part=>part.type!=='literal').map(part=>[part.type,part.value]));
 return out.year+'-'+out.month+'-'+out.day;
}
function clientTopbarDate(day){
 if(!/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(day||''))return '';
 const date=new Date(day+'T12:00:00Z');
 if(!Number.isFinite(date.getTime()))return '';
 const pieces=new Intl.DateTimeFormat('en-US',{
  timeZone:'Asia/Taipei',weekday:'short',month:'short',day:'2-digit',year:'numeric'
 }).formatToParts(date);
 const parts=Object.fromEntries(pieces.filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));
 return (parts.weekday+' · '+parts.month+' '+parts.day+', '+parts.year).toUpperCase();
}
function updateTopbarDate(){$('page-title').textContent=clientTopbarDate(taipeiDay())}
function node(tag,text,className){
 const el=document.createElement(tag);
 if(text!==undefined&&text!==null)el.textContent=String(text);
 if(className)el.className=className;
 return el;
}
async function api(path){
 if(!config.apiBase||!/^https:\/\//.test(config.apiBase))throw Error('尚未設定正式 Worker API');
 const base=config.apiBase.replace(/\/$/,'');
 const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});
 if(!response.ok){
  const error=new Error('API HTTP '+response.status);
  error.status=response.status;
  throw error;
 }
 return response.json();
}
async function loadPttRecentPayload(today){
 try{
  return await api('/v1/ptt/recent?limit=1000');
 }catch(error){
  if(![404,405,501].includes(Number(error?.status)))throw error;
  try{
   return await api('/v1/ptt/today?day='+encodeURIComponent(today)+'&limit=1000');
  }catch(fallbackError){
   if(![400,413,422].includes(Number(fallbackError?.status)))throw fallbackError;
   return api('/v1/ptt/today?day='+encodeURIComponent(today)+'&limit=300');
  }
 }
}
function pushKey(row){return String(row.push_id||String(row.aid||'')+':'+String(row.source_line||''))}
function pttRow(row){
 const push=node('div',undefined,'push');
 push.dataset.pushId=pushKey(row);
 const kind=String(row.kind||'→');
 const kindEl=node('div',kind,'ptt-push-kind '+(kind==='噓'?'kind-boo':kind==='→'?'kind-arrow':''));
 const when=new Date(String(row.occurred_at||''));
 const timeEl=node('time','--:--','ptt-push-time');
 if(Number.isFinite(when.getTime())){
  timeEl.textContent=new Intl.DateTimeFormat('zh-TW',{
   timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',hour12:false
  }).format(when);
 }
 const floorValue=Number.isInteger(row.floor)&&row.floor>0?row.floor:null;
 const floorEl=node('span',floorValue===null?'':floorValue+'樓','ptt-push-floor');
 if(floorValue===null)floorEl.setAttribute('aria-hidden','true');
 const body=node('div',undefined,'ptt-push-body');
 body.append(node('span',String(row.author||'unknown')+':','ptt-push-author'));
 body.append(node('span',String(row.content||''),'ptt-push-content'));
 push.append(kindEl,timeEl,floorEl,body);
 if(row.source_url){
  push.title='點兩下開啟 PTT 原文';
  push.addEventListener('dblclick',()=>window.open(String(row.source_url),'_blank','noopener,noreferrer'));
 }
 return push;
}
function pttAtBottom(){
 const list=$('ptt-list');
 return list.scrollHeight-list.scrollTop-list.clientHeight<48;
}
function pttToLatest(force=false){
 const list=$('ptt-list');
 if(!force&&!pttFollowing)return;
 pttProgrammatic=true;
 list.scrollTop=list.scrollHeight;
 requestAnimationFrame(()=>{pttProgrammatic=false});
 $('ptt-newest').hidden=true;
}
function pttApplyFloorPreference(show){
 document.body.classList.toggle('ptt-floor-hidden',!show);
 $('ptt-show-floor').checked=show;
 try{localStorage.setItem('holoviewer-ptt-show-floor',String(Boolean(show)))}catch{}
}
function setFocus(on){
 document.body.classList.toggle('ptt-focus-mode',on);
 $('ptt-focus').textContent=on?'退出專注':'⛶ 專注模式';
 $('ptt-focus').setAttribute('aria-label',on?'退出專注模式':'進入專注模式');
 $('ptt-floor-toggle').hidden=!on;
 const url=new URL(location.href);
 if(on)url.searchParams.set('focus','1');else url.searchParams.delete('focus');
 history.replaceState(null,'',url.pathname+(url.searchParams.toString()?'?'+url.searchParams.toString():''));
}
async function loadPtt(){
 if(pttLoadInFlight)return;
 const today=taipeiDay();
 updateTopbarDate();
 const meta=$('ptt-today-meta'),list=$('ptt-list'),empty=$('ptt-empty'),latest=$('ptt-newest');
 if(pttLastGoodDay&&pttLastGoodDay!==today){
  pttLastGoodDay=today;
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
  const data=await loadPttRecentPayload(today);
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
    const key=pushKey(row);
    if(!seen.has(key)){list.append(pttRow(row));seen.add(key)}
   }
   while(list.children.length>1000)list.firstElementChild?.remove();
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
 }catch{
  meta.textContent=today.replaceAll('-','/')+' · 後端暫未就緒 · 60 秒後重試 · 純 PTT 閱讀';
  if(!pttLastGoodCount){
   list.hidden=true;empty.hidden=false;latest.hidden=true;
   empty.textContent='今日 PTT 後端資料暫未就緒；頁面會每 60 秒自動重試。';
  }
 }finally{pttLoadInFlight=false}
}

function init(){
 updateTopbarDate();
 const list=$('ptt-list'),latest=$('ptt-newest');
 let show=true;try{show=localStorage.getItem('holoviewer-ptt-show-floor')!=='false'}catch{}
 pttApplyFloorPreference(show);
 latest.addEventListener('click',()=>{pttFollowing=true;pttToLatest(true)});
 list.addEventListener('wheel',event=>{
  if(event.deltaY<0)pttFollowing=false;
  else if(event.deltaY>0&&pttAtBottom())pttFollowing=true;
 },{passive:true});
 list.addEventListener('scroll',()=>{
  if(pttProgrammatic)return;
  pttFollowing=pttAtBottom();
  latest.hidden=pttFollowing;
 },{passive:true});
 $('ptt-show-floor').addEventListener('change',()=>pttApplyFloorPreference($('ptt-show-floor').checked));
 $('ptt-refresh').addEventListener('click',loadPtt);
 $('ptt-focus').addEventListener('click',()=>setFocus(!document.body.classList.contains('ptt-focus-mode')));
 $('mobileNavButton').addEventListener('click',()=>{
  const nav=$('mobileNav');
  const opening=nav.hidden;
  nav.hidden=!opening;
  $('mobileNavButton').setAttribute('aria-expanded',String(opening));
 });
 setFocus(new URLSearchParams(location.search).get('focus')==='1');
 loadPtt();
}
init();
const pollTimer=setInterval(()=>{if(!document.hidden)loadPtt()},PTT_POLL_MS);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadPtt()});
window.addEventListener('pagehide',()=>clearInterval(pollTimer),{once:true});
