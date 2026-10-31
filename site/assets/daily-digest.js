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

const PUBLIC_LAYOUTS=new Set(['brief','lead','split','editorial','compact','rail','timeline','chips']);

function publicText(value){
  return text(value)
    .replace(/\x60[A-Za-z0-9_-]{11}\x60/g,'')
    .replace(/\(\s*\)/g,'')
    .replace(/（\s*）/g,'')
    .replace(/\s{2,}/g,' ')
    .trim();
}
function clampText(value,max=46){
  const raw=publicText(value);
  if(raw.length<=max)return raw;
  return raw.slice(0,Math.max(1,max-1)).trimEnd()+'…';
}
function shortHeadline(value,max=42){
  const raw=publicText(value);
  if(!raw)return '';
  const parts=raw.split(/[：:]/);
  const candidate=parts[0]&&parts[0].length>=8?parts[0]:raw;
  return clampText(candidate,max);
}
function paragraphChunks(value,{min=2,max=3}={}){
  const raw=publicText(value);
  if(!raw)return [];
  const sentences=raw.match(/[^。！？!?]+[。！？!?]?/g)?.map(item=>item.trim()).filter(Boolean)||[raw];
  if(sentences.length<=1)return [raw];
  const target=Math.min(max,Math.max(min,Math.ceil(raw.length/150)));
  const size=Math.ceil(sentences.length/target);
  const chunks=[];
  for(let i=0;i<sentences.length;i+=size)chunks.push(sentences.slice(i,i+size).join(''));
  return chunks.slice(0,max);
}
function appendParagraphs(parent,value,className){
  const chunks=paragraphChunks(value);
  chunks.forEach(chunk=>parent.append(el('p',className,chunk)));
}
function storyVisual(videoIds,byId){
  const ids=[...new Set((Array.isArray(videoIds)?videoIds:[]).map(String).filter(id=>byId.has(id)))].slice(0,6);
  if(!ids.length)return null;
  const visual=el('div','daily-story-visual');
  visual.dataset.count=String(ids.length);
  ids.forEach((id,index)=>{
    const figure=el('figure','daily-story-visual-item');
    figure.dataset.slot=String(index+1);
    const img=thumbnailImage(id);
    if(img)figure.append(img);
    const row=byId.get(id),name=publicText(row?.channel_name);
    if(name)figure.append(el('figcaption','',name));
    visual.append(figure);
  });
  return visual;
}
function publicLayout(source,fallback){
  const requested=text(source?.layout_template||source?.display_template||source?.layout).toLowerCase();
  return PUBLIC_LAYOUTS.has(requested)?requested:fallback;
}
function streamMap(artifact){
  return new Map((Array.isArray(artifact?.streams)?artifact.streams:[]).map(row=>[String(row?.video_id||''),row]));
}
function youtubeUrl(videoId){return /^[A-Za-z0-9_-]{11}$/.test(String(videoId||''))?'https://www.youtube.com/watch?v='+videoId:''}
function thumbnailCandidates(videoId){
  const id=String(videoId||'');
  if(!/^[A-Za-z0-9_-]{11}$/.test(id))return [];
  return [
    'https://i.ytimg.com/vi/'+id+'/maxresdefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/sddefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/hqdefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/mqdefault.jpg'
  ];
}
function thumbnailUrl(videoId){return thumbnailCandidates(videoId)[0]||''}
function thumbnailImage(videoId,{loading='lazy'}={}){
  const candidates=thumbnailCandidates(videoId);
  if(!candidates.length)return null;
  const img=el('img');img.alt='';img.loading=loading;img.referrerPolicy='no-referrer';
  let index=0;
  const next=()=>{if(index<candidates.length)img.src=candidates[index++]};
  img.addEventListener('error',next);
  next();
  return img;
}
function publicTypeLabel(type){
  return {
    merch_and_event:'活動・周邊',
    concert:'演出',
    music:'音樂',
    outfit_reveal:'新衣裝',
    membership_and_schedule:'近期行程',
    collab_preview:'合作預告',
    sponsored_and_schedule:'工商・行程',
    sponsored_and_merch:'工商・商品'
  }[text(type)]||'近期資訊';
}
function streamReference(videoId,byId){
  const row=byId.get(videoId);
  const details=el('details','daily-stream-ref');
  const head=el('summary','daily-stream-ref-head');
  const thumb=thumbnailUrl(videoId);
  if(thumb){
    const img=thumbnailImage(videoId);
    if(img)head.append(img);
  }
  const copy=el('span','daily-stream-ref-copy');
  copy.append(el('strong','',publicText(row?.channel_name)||'直播'));
  copy.append(el('span','',clampText(row?.title||'直播資訊',62)));
  head.append(copy);
  details.append(head);

  const body=el('div','daily-stream-ref-detail');
  const summary=publicText(row?.summary);
  if(summary)body.append(el('p','',summary));
  const topics=Array.isArray(row?.topics)?row.topics.map(publicText).filter(Boolean).slice(0,4):[];
  if(topics.length){
    const chips=el('div','daily-stream-topic-chips');
    topics.forEach(topic=>chips.append(el('span','',topic)));
    body.append(chips);
  }
  const href=text(row?.youtube_url)||youtubeUrl(videoId);
  if(href){
    const link=el('a','daily-stream-youtube','在 YouTube 開啟 ↗');
    link.href=href;link.target='_blank';link.rel='noopener noreferrer';body.append(link);
  }
  details.append(body);
  return details;
}
function appendReferences(parent,ids,byId,{label='相關直播'}={}){
  const valid=[...new Set((Array.isArray(ids)?ids:[]).map(String).filter(id=>byId.has(id)))];
  if(!valid.length)return;
  const drawer=el('details','daily-source-drawer');
  drawer.append(el('summary','daily-source-drawer-label',label+' '+valid.length+' 場'));
  const refs=el('div','daily-stream-refs');
  valid.forEach(id=>refs.append(streamReference(id,byId)));
  drawer.append(refs);
  parent.append(drawer);
}
function section(title,className='',layout=''){
  const wrap=el('section','daily-v1-section'+(className?' '+className:''));
  if(layout)wrap.dataset.layout=layout;
  wrap.append(el('h2','daily-v1-section-title',title));
  return wrap;
}
function renderCoverage(target,artifact){
  const total=Number(artifact?.coverage?.total_streams||0);
  if(!total)return;
  const bar=el('div','daily-coverage daily-public-coverage');
  bar.append(el('span','daily-coverage-label','本日收錄'));
  bar.append(el('strong','',String(total)+' 場直播'));
  target.append(bar);
}
function renderOverview(target,artifact,byId){
  const overview=artifact?.overview||{};
  const highlights=Array.isArray(overview.highlights)?overview.highlights.map(publicText).filter(Boolean):[];
  if(!highlights.length&&!publicText(overview.summary))return;
  const wrap=section('今天發生什麼','daily-overview','brief');
  const intro=publicText(overview.public_summary||overview.summary);
  if(intro){
    const cleaned=intro.replace(/^.*?共計\s*\d+\s*場[^。]*。\s*/,'');
    const first=cleaned.split('。').filter(Boolean).slice(0,2).join('。');
    if(first)appendParagraphs(wrap,first+'。','daily-overview-summary');
  }
  if(highlights.length){
    const stories=Array.isArray(artifact?.stories)?artifact.stories:[];
    const grid=el('div','daily-highlight-grid');
    highlights.slice(0,5).forEach((item,index)=>{
      const card=el('article','daily-highlight-card');
      card.dataset.accent=String((index%3)+1);
      const story=stories[index];
      const firstVideo=(Array.isArray(story?.video_ids)?story.video_ids:[]).map(String).find(id=>byId.has(id));
      if(firstVideo){
        const media=el('div','daily-highlight-media');
        const img=thumbnailImage(firstVideo,{loading:index===0?'eager':'lazy'});
        if(img)media.append(img);
        const row=byId.get(firstVideo),name=publicText(row?.channel_name);
        if(name)media.append(el('span','daily-highlight-channel',name));
        card.append(media);
      }
      const copy=el('div','daily-highlight-copy');
      const parts=item.split(/[：:]/);
      copy.append(el('h3','',shortHeadline(parts[0]||item,36)));
      const rest=parts.length>1?parts.slice(1).join('：'):item;
      copy.append(el('p','',clampText(rest,150)));
      card.append(copy);
      grid.append(card);
    });
    wrap.append(grid);
  }
  target.append(wrap);
}
function storyAutoLayout(story,index){
  const subs=Array.isArray(story?.sub_events)?story.sub_events.length:0;
  const refs=Array.isArray(story?.video_ids)?story.video_ids.length:0;
  if(index===0)return 'lead';
  if(subs>=3)return 'split';
  if(refs>=8)return 'editorial';
  return index%2?'compact':'split';
}
function renderStories(target,artifact,byId){
  const stories=Array.isArray(artifact?.stories)?artifact.stories:[];
  if(!stories.length)return;
  const wrap=section('今日主題','daily-stories','editorial');
  const list=el('div','daily-story-list');
  stories.forEach((story,index)=>{
    const layout=publicLayout(story,storyAutoLayout(story,index));
    const card=el('article','daily-story-card');
    card.dataset.layout=layout;

    const eyebrow=el('div','daily-story-eyebrow');
    const members=Array.isArray(story.member_names)?story.member_names.map(publicText).filter(Boolean):[];
    eyebrow.append(el('span','',index===0?'今日焦點':'今日話題'));
    if(members.length)eyebrow.append(el('span','',members.slice(0,3).join('・')+(members.length>3?' 等':'')));
    card.append(eyebrow);

    const headline=publicText(story.short_title)||shortHeadline(story.title,layout==='lead'?50:42);
    if(headline)card.append(el('h3','daily-story-title',headline));

    const summary=publicText(story.public_summary||story.summary);
    if(summary){
      const copy=el('div','daily-story-summary-block');
      appendParagraphs(copy,summary,'daily-story-summary');
      card.append(copy);
    }
    const visual=storyVisual(story.video_ids,byId);
    if(visual)card.append(visual);

    const subs=Array.isArray(story.sub_events)?story.sub_events:[];
    if(subs.length){
      const subWrap=el('div','daily-sub-events');
      const visible=layout==='lead'?3:2;
      subs.slice(0,visible).forEach(sub=>{
        const item=el('details','daily-sub-event');
        const head=el('summary','daily-sub-event-head');
        const firstVideo=(Array.isArray(sub.video_ids)?sub.video_ids:[]).find(id=>byId.has(String(id)));
        if(firstVideo){
          const img=thumbnailImage(String(firstVideo));
          if(img)head.append(img);
        }
        const headCopy=el('span','daily-sub-event-head-copy');
        if(publicText(sub.title))headCopy.append(el('h4','',shortHeadline(sub.short_title||sub.title,38)));
        if(publicText(sub.summary))headCopy.append(el('p','',clampText(sub.summary,120)));
        head.append(headCopy);
        item.append(head);
        const detail=el('div','daily-sub-event-detail');
        if(publicText(sub.summary))appendParagraphs(detail,sub.summary,'');
        appendReferences(detail,sub.video_ids,byId,{label:'相關直播'});
        item.append(detail);
        subWrap.append(item);
      });
      if(subs.length>visible){
        const more=el('details','daily-sub-more');
        more.append(el('summary','','展開更多整理（'+String(subs.length-visible)+'）'));
        subs.slice(visible).forEach(sub=>{
          const item=el('details','daily-sub-event');
          const head=el('summary','daily-sub-event-head');
          const firstVideo=(Array.isArray(sub.video_ids)?sub.video_ids:[]).find(id=>byId.has(String(id)));
          if(firstVideo){
            const img=thumbnailImage(String(firstVideo));
          if(img)head.append(img);
          }
          const headCopy=el('span','daily-sub-event-head-copy');
          if(publicText(sub.title))headCopy.append(el('h4','',shortHeadline(sub.title,38)));
          if(publicText(sub.summary))headCopy.append(el('p','',clampText(sub.summary,120)));
          head.append(headCopy);item.append(head);
          const detail=el('div','daily-sub-event-detail');
          if(publicText(sub.summary))appendParagraphs(detail,sub.summary,'');
          appendReferences(detail,sub.video_ids,byId,{label:'相關直播'});
          item.append(detail);more.append(item);
        });
        subWrap.append(more);
      }
      card.append(subWrap);
    }
    appendReferences(card,story.video_ids,byId,{label:'這個主題用到的直播'});
    list.append(card);
  });
  wrap.append(list);target.append(wrap);
}
function renderAnnouncements(target,artifact,byId){
  const rows=Array.isArray(artifact?.announcements)?artifact.announcements:[];
  if(!rows.length)return;
  const wrap=section('接下來值得注意','daily-announcements','timeline');
  const timeline=el('div','daily-announcement-timeline');
  rows.forEach(row=>{
    const card=el('article','daily-announcement-card');
    const when=el('div','daily-announcement-when');
    when.append(el('span','daily-announcement-type',publicTypeLabel(row.type)));
    if(publicText(row.event_date_text))when.append(el('time','',publicText(row.event_date_text)));
    card.append(when);
    if(publicText(row.title))card.append(el('h3','',shortHeadline(row.short_title||row.title,44)));
    if(publicText(row.summary))card.append(el('p','',publicText(row.summary)));
    appendReferences(card,row.video_ids,byId,{label:'來源直播'});
    timeline.append(card);
  });
  wrap.append(timeline);target.append(wrap);
}
function renderCategories(target,artifact,byId){
  const rows=(Array.isArray(artifact?.categories)?artifact.categories:[])
    .filter(row=>text(row?.key)!=='unverified_streams');
  if(!rows.length)return;
  const wrap=section('依內容瀏覽','daily-categories','chips');
  wrap.append(el('p','daily-category-intro','從主題切入，需要時再展開相關直播；不再把全部直播重複鋪滿整頁。'));
  const chips=el('div','daily-category-chips');
  const panels=el('div','daily-category-panels');
  rows.forEach((row,index)=>{
    const ids=[...new Set((Array.isArray(row.video_ids)?row.video_ids:[]).map(String).filter(id=>byId.has(id)))];
    if(!ids.length)return;
    const id='daily-category-'+String(index);
    const button=el('button','daily-category-chip',shortHeadline(row.label||row.key,30));
    button.type='button';
    button.append(el('span','',String(ids.length)));
    button.addEventListener('click',()=>{
      const panel=document.getElementById(id);
      if(panel){panel.open=!panel.open;if(panel.open)panel.scrollIntoView({behavior:'smooth',block:'nearest'})}
    });
    chips.append(button);

    const panel=el('details','daily-category');
    panel.id=id;
    panel.append(el('summary','',publicText(row.label)||'分類'));
    const refs=el('div','daily-stream-refs');
    ids.forEach(videoId=>refs.append(streamReference(videoId,byId)));
    panel.append(refs);panels.append(panel);
  });
  wrap.append(chips,panels);target.append(wrap);
}
function renderUnverified(target,artifact,byId){
  const debug=new URLSearchParams(location.search).get('debug')==='1';
  if(!debug)return;
  const rows=Array.isArray(artifact?.unverified)?artifact.unverified:[];
  if(!rows.length)return;
  const wrap=section('內部檢查：未驗證項目','daily-unverified','compact');
  wrap.append(el('p','daily-unverified-note','僅在 ?debug=1 顯示；Public 預設不呈現未驗證內容。'));
  rows.forEach(row=>{
    const item=el('article','daily-unverified-item'),stream=byId.get(String(row.video_id||''));
    item.append(el('strong','',publicText(stream?.channel_name)||'未驗證直播'));
    if(publicText(stream?.title))item.append(el('span','',publicText(stream.title)));
    if(publicText(row.reason))item.append(el('p','',publicText(row.reason)));
    wrap.append(item);
  });
  target.append(wrap);
}
function renderArtifact(target,artifact){
  target.replaceChildren();
  const byId=streamMap(artifact);
  renderCoverage(target,artifact);
  renderOverview(target,artifact,byId);
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