import {readToday} from './store.mjs';

const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const DAY=/^\d{4}-\d{2}-\d{2}$/;
const EVENT_ID=/^[A-Za-z0-9:_-]{1,160}$/;
const ARK=/(?<![a-z])ARK(?![a-z])|ホロARK|ロゼキャンARK|ホロ鯖ARK/i;
const EXPLICIT=/#?ホロARK|ホロ鯖ARK|ロゼキャンARK/i;
const STOPWORDS=new Set(['hololive','ホロライブ','live','配信','初見','雑談','vtuber','ホロドリ','holodream','コラボ','collab']);
const MAX_HISTORY_ROWS=1000;

function json(body,status=200,age=30){
 return new Response(JSON.stringify(body),{status,headers:{
  'content-type':'application/json; charset=utf-8',
  'cache-control':'public, max-age='+age,
  'x-content-type-options':'nosniff'
 }});
}
function validDay(day){
 if(!DAY.test(day??''))return false;
 const d=new Date(day+'T00:00:00Z');
 return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===day;
}
function intParam(raw,{min=0,max=1000,def=0}={}){
 if(raw==null||raw==='')return def;
 if(!/^\d+$/.test(raw))return null;
 const n=Number(raw);
 return Number.isSafeInteger(n)&&n>=min&&n<=max?n:null;
}
function validTime(value){
 if(typeof value!=='string'||!value)return null;
 const ms=Date.parse(value);
 return Number.isFinite(ms)?new Date(ms):null;
}
function taipeiDayWithSixHourRollover(value){
 const d=validTime(value);
 if(!d)return null;
 const shifted=new Date(d.getTime()-6*3600_000);
 return new Intl.DateTimeFormat('en-CA',{
  timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'
 }).format(shifted);
}
function normalizeStream(row,{state=null}={}){
 const video_id=VIDEO.test(row?.video_id??'')?row.video_id:null;
 if(!video_id)return null;
 const channel_id=CHANNEL.test(row?.channel_id??row?.publisher_channel_id??'')?(row.channel_id??row.publisher_channel_id):'';
 const actual_start=typeof row?.actual_start==='string'?row.actual_start:null;
 const scheduled_start=typeof row?.scheduled_start==='string'?row.scheduled_start:null;
 const actual_end=typeof row?.actual_end==='string'?row.actual_end:null;
 const start_at=actual_start??scheduled_start??(typeof row?.start_at==='string'?row.start_at:null);
 const lifecycle=state??String(row?.lifecycle_state??row?.state??'unknown');
 return {
  video_id,
  title:typeof row?.title==='string'?row.title:'',
  channel_id,
  channel_name:typeof (row?.channel_name??row?.channel_title)==='string'?(row.channel_name??row.channel_title):'',
  source_label:typeof row?.source_label==='string'?row.source_label:'',
  lifecycle_state:['live','upcoming','ended'].includes(lifecycle)?lifecycle:'unknown',
  start_at:validTime(start_at)?.toISOString().replace(/\.\d{3}Z$/,'Z')??null,
  actual_start:validTime(actual_start)?.toISOString().replace(/\.\d{3}Z$/,'Z')??null,
  actual_end:validTime(actual_end)?.toISOString().replace(/\.\d{3}Z$/,'Z')??null,
  avatar_url:typeof row?.avatar_url==='string'?row.avatar_url:null
 };
}
function titleTokens(stream){
 const text=(stream.title+' '+stream.source_label).toLowerCase();
 const tokens=new Set();
 for(const re of [/[a-z0-9]{4,}/g,/[ァ-ヶー]{4,}/g,/[一-龠]{3,}/g]){
  for(const match of text.matchAll(re)){
   const token=match[0].toLowerCase();
   if(!STOPWORDS.has(token))tokens.add(token);
  }
 }
 return tokens;
}
function overlap(a,b){for(const x of a)if(b.has(x))return true;return false;}
function eventPayload(candidate,allStreams){
 const byId=new Map(allStreams.map(x=>[x.video_id,x]));
 const streams=candidate.video_ids.map(id=>byId.get(id)).filter(Boolean);
 const verified=streams.length>1&&streams.every(x=>x.lifecycle_state==='ended'&&x.actual_start&&x.actual_end&&Date.parse(x.actual_end)>Date.parse(x.actual_start));
 const master=verified?streams[0]:null;
 return {
  event_id:candidate.event_id,
  event_key:candidate.event_key,
  label:candidate.label,
  confidence:candidate.confidence,
  candidate:true,
  sync:{
   available:verified,
   basis:verified?'youtube_actual_start':null,
   master_video_id:master?.video_id??null,
   master_start:master?.actual_start??null
  },
  streams:streams.map(x=>({
   ...x,
   sync_offset_ms:verified?Date.parse(x.actual_start)-Date.parse(master.actual_start):null
  }))
 };
}
export function detectCollabCandidates(input){
 const rows=input.map(x=>normalizeStream(x)).filter(Boolean);
 const eligible=rows.filter(s=>ARK.test(s.title+' '+s.source_label)&&EXPLICIT.test(s.title+' '+s.source_label)&&['live','ended','upcoming'].includes(s.lifecycle_state)&&s.start_at);
 eligible.sort((a,b)=>Date.parse(a.start_at)-Date.parse(b.start_at)||a.video_id.localeCompare(b.video_id));
 const byDay=new Map();
 for(const s of eligible){
  const day=taipeiDayWithSixHourRollover(s.start_at);
  if(day)byDay.set(day,[...(byDay.get(day)??[]),s]);
 }
 const out=[];
 const claimed=new Set();
 for(const [day,cluster] of byDay){
  const byChannel=new Map();
  for(const s of cluster){
   const key=s.channel_id||s.channel_name;
   if(key&&!byChannel.has(key))byChannel.set(key,s);
  }
  if(byChannel.size>1){
   const ids=[...byChannel.values()].map(x=>x.video_id);
   ids.forEach(x=>claimed.add(x));
   out.push({label:'ホロARK · 多人連動候選',video_ids:ids,confidence:'candidate',event_key:'ark',event_id:'ark:'+day});
  }
 }
 const remaining=rows.filter(s=>!claimed.has(s.video_id)&&s.start_at&&['live','ended','upcoming'].includes(s.lifecycle_state))
   .sort((a,b)=>Date.parse(a.start_at)-Date.parse(b.start_at)||a.video_id.localeCompare(b.video_id));
 const pairs=[];
 for(let i=0;i<remaining.length;i++){
  const left=remaining[i],lc=left.channel_id||left.channel_name;
  if(!lc)continue;
  for(let j=i+1;j<remaining.length;j++){
   const right=remaining[j],rc=right.channel_id||right.channel_name;
   if(!rc||rc===lc)continue;
   if(Math.abs(Date.parse(right.start_at)-Date.parse(left.start_at))>20*60_000)continue;
   if(overlap(titleTokens(left),titleTokens(right)))pairs.push(new Set([left.video_id,right.video_id]));
  }
 }
 const groups=[];
 for(const pair of pairs){
  const hits=groups.filter(g=>overlap(g,pair));
  if(hits.length){
   const merged=new Set(pair);
   for(const h of hits){for(const id of h)merged.add(id);groups.splice(groups.indexOf(h),1);}
   groups.push(merged);
  }else groups.push(new Set(pair));
 }
 for(const group of groups){
  const ids=remaining.filter(x=>group.has(x.video_id)).map(x=>x.video_id);
  if(ids.length>1){
   const day=taipeiDayWithSixHourRollover(remaining.find(x=>x.video_id===ids[0])?.start_at)??'unknown';
   out.push({label:'多人連動',video_ids:ids,confidence:'shared-topic',event_key:'shared-topic',event_id:'shared-topic:'+day+':'+[...ids].sort()[0]});
  }
 }
 return out.map(c=>eventPayload(c,rows));
}
function nextDay(day){
 const d=new Date(day+'T00:00:00Z');
 d.setUTCDate(d.getUTCDate()+1);
 return d.toISOString().slice(0,10);
}
async function historyRows(db,day){
 // Accepted 4174 Collab event-day rolls over at 06:00 Taipei. Read the selected
 // calendar day plus the following early-morning calendar day, then filter by
 // canonical event-day so one overnight event is never split in two.
 const rows=await db.prepare(`SELECT video_id,title,channel_id,channel_name,avatar_url,actual_start,actual_end,scheduled_start
 FROM public_history WHERE taipei_day IN (?,?)
 ORDER BY COALESCE(actual_start,scheduled_start) ASC,video_id ASC LIMIT ?`)
  .bind(day,nextDay(day),MAX_HISTORY_ROWS*2+1).all();
 const raw=rows.results??[];
 const normalized=raw.map(x=>normalizeStream(x,{state:'ended'})).filter(Boolean)
  .filter(x=>x.start_at&&taipeiDayWithSixHourRollover(x.start_at)===day);
 return {
  limited:raw.length>MAX_HISTORY_ROWS*2||normalized.length>MAX_HISTORY_ROWS,
  streams:normalized.slice(0,MAX_HISTORY_ROWS)
 };
}
async function collabLive(db,{now=new Date(),profileTableEnabled=false}={}){
 const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 const today=await readToday(db,{day,limit:200,offset:0,now,profileTableEnabled});
 return {
  schema_version:'public-experience-v1',
  kind:'collab',
  scope:'live',
  day,
  completeness:today.completeness,
  events:detectCollabCandidates(today.streams)
 };
}
async function collabHistory(db,day,{limit=50,offset=0}={}){
 const source=await historyRows(db,day);
 const events=detectCollabCandidates(source.streams);
 return {
  schema_version:'public-experience-v1',
  kind:'collab',
  scope:'history',
  day,
  completeness:{limited:source.limited,has_more:offset+limit<events.length},
  total:events.length,
  limit,offset,
  events:events.slice(offset,offset+limit)
 };
}
function publicWatchEvent(row,streams){
 return {
  event_id:row.event_id,
  title:row.description,
  day:row.day,
  scheduled_time:row.scheduled_time,
  member_only:Boolean(row.member_only),
  provenance:{aid:row.aid,article_title:row.article_title,source_url:row.source_url,article_datetime:row.article_datetime,source:row.source},
  hosts:(streams.get(row.event_id)??[]).map(s=>({label:s.label,video_id:s.video_id})),
  source_mapping:null,
  capabilities:{source_mapping:false,translation:false,telemetry:false}
 };
}
async function hydrateWatchRows(db,rows){
 if(!rows.length)return [];
 const ids=rows.map(x=>x.event_id);
 const placeholders=ids.map(()=>'?').join(',');
 const s=await db.prepare(`SELECT event_id,ordinal,label,video_id FROM public_watchalong_streams WHERE event_id IN (${placeholders}) ORDER BY event_id,ordinal`).bind(...ids).all();
 const grouped=new Map();
 for(const x of s.results??[])grouped.set(x.event_id,[...(grouped.get(x.event_id)??[]),x]);
 return rows.map(x=>publicWatchEvent(x,grouped));
}
async function watchalongHistory(db,day,{limit=60,offset=0}={}){
 const rows=await db.prepare(`SELECT event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,source
 FROM public_watchalong_events WHERE day=? ORDER BY article_datetime DESC,scheduled_time DESC,event_id DESC LIMIT ? OFFSET ?`)
  .bind(day,limit+1,offset).all();
 const raw=rows.results??[],has_more=raw.length>limit;
 return {schema_version:'public-experience-v1',kind:'watchalong',scope:'history',day,limit,offset,has_more,events:await hydrateWatchRows(db,raw.slice(0,limit))};
}
async function watchalongRecent(db,{days=30,limit=60,now=new Date()}={}){
 const localDay=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
 const startDate=new Date(localDay+'T00:00:00+08:00');
 const cutoff=new Date(startDate.getTime()-(days-1)*86400_000);
 const cutoffDay=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(cutoff);
 const rows=await db.prepare(`SELECT event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,source
 FROM public_watchalong_events WHERE day>=? AND day<=? ORDER BY article_datetime DESC,scheduled_time DESC,event_id DESC LIMIT ?`)
  .bind(cutoffDay,localDay,limit+1).all();
 const raw=rows.results??[],has_more=raw.length>limit;
 return {schema_version:'public-experience-v1',kind:'watchalong',scope:'recent',days,limit,has_more,as_of:now.toISOString().replace(/\.\d{3}Z$/,'Z'),events:await hydrateWatchRows(db,raw.slice(0,limit))};
}
async function watchalongDetail(db,eventId){
 const row=await db.prepare(`SELECT event_id,aid,article_title,source_url,article_datetime,day,scheduled_time,description,member_only,source
 FROM public_watchalong_events WHERE event_id=?`).bind(eventId).first();
 if(!row)return null;
 return (await hydrateWatchRows(db,[row]))[0];
}
export async function handleExperienceRead(request,env,now=new Date()){
 if(!request||request.method!=='GET')return json({error:'method_not_allowed'},405,0);
 if(!env?.DB||typeof env.DB.prepare!=='function')return json({error:'service_unavailable'},503,0);
 let url;try{url=new URL(request.url);}catch{return json({error:'bad_request'},400,0);}
 try{
  if(url.pathname==='/v1/collab/live'){
   return json(await collabLive(env.DB,{now,profileTableEnabled:env.TODAY_PROFILES_ENABLED==='true'}));
  }
  if(url.pathname==='/v1/collab/history'){
   const day=url.searchParams.get('day')??'';
   const limit=intParam(url.searchParams.get('limit'),{min:1,max:100,def:50});
   const offset=intParam(url.searchParams.get('offset'),{min:0,max:1000,def:0});
   if(!validDay(day)||limit==null||offset==null)return json({error:'invalid_collab_query'},400,0);
   return json(await collabHistory(env.DB,day,{limit,offset}));
  }
  if(url.pathname.startsWith('/v1/collab/events/')){
   const eventId=decodeURIComponent(url.pathname.slice('/v1/collab/events/'.length));
   if(!EVENT_ID.test(eventId))return json({error:'invalid_event_id'},400,0);
   const day=url.searchParams.get('day');
   let events;
   if(day!=null){
    if(!validDay(day))return json({error:'invalid_day'},400,0);
    const source=await historyRows(env.DB,day);
    events=detectCollabCandidates(source.streams);
   }else events=(await collabLive(env.DB,{now,profileTableEnabled:env.TODAY_PROFILES_ENABLED==='true'})).events;
   const event=events.find(x=>x.event_id===eventId);
   return event?json({schema_version:'public-experience-v1',event}):json({error:'not_found'},404,0);
  }
  if(url.pathname==='/v1/watchalong/recent'){
   if(env.WATCHALONG_EVENTS_ENABLED!=='true')return json({error:'watchalong_not_enabled'},503,0);
   const days=intParam(url.searchParams.get('days'),{min:1,max:90,def:30});
   const limit=intParam(url.searchParams.get('limit'),{min:1,max:100,def:60});
   if(days==null||limit==null)return json({error:'invalid_watchalong_query'},400,0);
   return json(await watchalongRecent(env.DB,{days,limit,now}));
  }
  if(url.pathname==='/v1/watchalong/history'){
   if(env.WATCHALONG_EVENTS_ENABLED!=='true')return json({error:'watchalong_not_enabled'},503,0);
   const day=url.searchParams.get('day')??'';
   const limit=intParam(url.searchParams.get('limit'),{min:1,max:100,def:60});
   const offset=intParam(url.searchParams.get('offset'),{min:0,max:1000,def:0});
   if(!validDay(day)||limit==null||offset==null)return json({error:'invalid_watchalong_query'},400,0);
   return json(await watchalongHistory(env.DB,day,{limit,offset}));
  }
  if(url.pathname.startsWith('/v1/watchalong/events/')){
   if(env.WATCHALONG_EVENTS_ENABLED!=='true')return json({error:'watchalong_not_enabled'},503,0);
   const eventId=decodeURIComponent(url.pathname.slice('/v1/watchalong/events/'.length));
   if(!/^watch:[0-9a-f]{20}$/.test(eventId))return json({error:'invalid_event_id'},400,0);
   const event=await watchalongDetail(env.DB,eventId);
   return event?json({schema_version:'public-experience-v1',event}):json({error:'not_found'},404,0);
  }
  return json({error:'not_found'},404,0);
 }catch(error){
  return json({error:'experience_projection_unavailable'},503,0);
 }
}
