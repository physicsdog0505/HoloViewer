import {YOUTUBE_LIVE_SOURCE} from './store.mjs';

const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const TRUSTED_TODAY='YouTube liveStreamingDetails';
const ADMISSION_WINDOW_MS=10*60_000;
const ADMISSION_MAX_NEW=120;
const ACTIVE_DEMAND_MAX=1000;
const TERMINAL_RETENTION_MS=24*60*60_000;
const TRUSTED_HISTORY=new Set([
  'stream-catalog-v1:youtube-liveStreamingDetails',
  'youtube-videos-list:liveStreamingDetails'
]);

function json(body,status=200,age=15){
 return new Response(JSON.stringify(body),{status,headers:{
  'content-type':'application/json; charset=utf-8',
  'cache-control':'public, max-age='+age,
  'x-content-type-options':'nosniff'
 }});
}
function validTime(x){return typeof x==='string'&&Number.isFinite(Date.parse(x));}
function trustedBounds(row,trusted){
 const actual_start=trusted&&validTime(row?.actual_start)?row.actual_start:null;
 const actual_end=trusted&&validTime(row?.actual_end)?row.actual_end:null;
 if(actual_start&&actual_end&&Date.parse(actual_end)<=Date.parse(actual_start)){
  return {actual_start:null,actual_end:null};
 }
 return {actual_start,actual_end};
}
async function managedMembership(db,channelId){
 if(!channelId)return null;
 return await db.prepare(
  'SELECT ac.roster_version,ac.channel_group FROM public_today_approved_channels ac '+
  'JOIN public_today_catalog_meta m ON m.singleton=1 AND m.roster_version=ac.roster_version '+
  'WHERE ac.channel_id=? LIMIT 1'
 ).bind(channelId).first();
}
async function verifiedPttPriority(db,url){
 const day=String(url.searchParams.get('ptt_day')||'');
 if(!/^\d{4}-\d{2}-\d{2}$/.test(day))return {priority:2,ptt_day:null};
 try{
  const row=await db.prepare("SELECT aid FROM ptt_threads WHERE day=? AND verified_at IS NOT NULL LIMIT 1").bind(day).first();
  return row?{priority:1,ptt_day:day}:{priority:2,ptt_day:null};
 }catch{
  return {priority:2,ptt_day:null};
 }
}
function stamp(ms){return new Date(ms).toISOString().replace(/\.\d{3}Z$/,'Z');}
function admissionWindowStart(ms){return Math.floor(ms/ADMISSION_WINDOW_MS)*ADMISSION_WINDOW_MS;}
function admissionRetryAfterSeconds(nowMs){return Math.max(1,Math.ceil((admissionWindowStart(nowMs)+ADMISSION_WINDOW_MS-nowMs)/1000));}
async function cleanupDemandState(db,now){
 const nowMs=now.getTime(),nowIso=stamp(nowMs),terminalBefore=stamp(nowMs-TERMINAL_RETENTION_MS),ledgerBefore=stamp(nowMs-TERMINAL_RETENTION_MS);
 await db.prepare("DELETE FROM public_video_metadata_recovery_demand WHERE status='resolved' AND updated_at<?").bind(terminalBefore).run();
 await db.prepare("DELETE FROM public_video_metadata_recovery_demand WHERE status='not_found' AND next_attempt_at<=?").bind(nowIso).run();
 await db.prepare("DELETE FROM public_video_metadata_recovery_admission_budget WHERE window_start<?").bind(ledgerBefore).run();
}
async function reserveAdmissionBudget(db,nowMs){
 const bucket=stamp(admissionWindowStart(nowMs));
 const result=await db.prepare(
  'INSERT INTO public_video_metadata_recovery_admission_budget(window_start,admissions,updated_at) VALUES(?,1,?) '+
  'ON CONFLICT(window_start) DO UPDATE SET admissions=public_video_metadata_recovery_admission_budget.admissions+1,updated_at=excluded.updated_at '+
  'WHERE public_video_metadata_recovery_admission_budget.admissions<?'
 ).bind(bucket,stamp(nowMs),ADMISSION_MAX_NEW).run();
 return Number(result?.meta?.changes??result?.changes??0)!==0;
}
async function registerDemand(db,id,{priority,ptt_day,now}){
 const nowMs=now.getTime(),nowIso=stamp(nowMs);
 await cleanupDemandState(db,now);
 const existing=await db.prepare('SELECT video_id,priority,status,ptt_day,requested_at,updated_at,next_attempt_at,attempts,last_error FROM public_video_metadata_recovery_demand WHERE video_id=? LIMIT 1').bind(id).first();
 if(existing?.status==='not_found'&&Date.parse(existing.next_attempt_at)>nowMs)return {demand:existing,admitted:true,reused:true};
 if(existing){
  await db.prepare(
   "UPDATE public_video_metadata_recovery_demand SET "+
   "priority=MIN(priority,?),ptt_day=COALESCE(ptt_day,?),"+
   "status=CASE WHEN status='processing' THEN 'processing' ELSE 'pending' END,"+
   "updated_at=?,next_attempt_at=CASE WHEN status='processing' THEN next_attempt_at ELSE ? END "+
   "WHERE video_id=?"
  ).bind(priority,ptt_day,nowIso,nowIso,id).run();
  const reused=await db.prepare('SELECT video_id,priority,status,ptt_day,requested_at,updated_at,next_attempt_at,attempts,last_error FROM public_video_metadata_recovery_demand WHERE video_id=? LIMIT 1').bind(id).first();
  return {demand:reused,admitted:true,reused:true};
 }
 const active=await db.prepare("SELECT COUNT(*) AS n FROM public_video_metadata_recovery_demand WHERE status IN ('pending','processing')").first();
 if(Number(active?.n??0)>=ACTIVE_DEMAND_MAX){
  return {demand:null,admitted:false,reused:false,reason:'active_queue_cap',retry_after_seconds:admissionRetryAfterSeconds(nowMs)};
 }
 if(!(await reserveAdmissionBudget(db,nowMs))){
  return {demand:null,admitted:false,reused:false,reason:'admission_budget',retry_after_seconds:admissionRetryAfterSeconds(nowMs)};
 }
 const inserted=await db.prepare(
  "INSERT OR IGNORE INTO public_video_metadata_recovery_demand(video_id,priority,status,ptt_day,requested_at,updated_at,next_attempt_at,attempts,last_error) VALUES(?,?, 'pending', ?, ?, ?, ?, 0, NULL)"
 ).bind(id,priority,ptt_day,nowIso,nowIso,nowIso).run();
 if(Number(inserted?.meta?.changes??inserted?.changes??0)===0){
  const raced=await db.prepare('SELECT video_id,priority,status,ptt_day,requested_at,updated_at,next_attempt_at,attempts,last_error FROM public_video_metadata_recovery_demand WHERE video_id=? LIMIT 1').bind(id).first();
  return {demand:raced,admitted:true,reused:true};
 }
 const demand=await db.prepare('SELECT video_id,priority,status,ptt_day,requested_at,updated_at,next_attempt_at,attempts,last_error FROM public_video_metadata_recovery_demand WHERE video_id=? LIMIT 1').bind(id).first();
 return {demand,admitted:true,reused:false};
}

async function readCatalog(db,id){
 const today=await db.prepare('SELECT video_id,title,publisher_channel_id AS channel_id,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,source_label FROM public_today_canonical WHERE video_id=? LIMIT 1').bind(id).first();
 if(today){
  const bounds=trustedBounds(today,today.source_label===TRUSTED_TODAY);
  return {video_id:today.video_id,channel_id:today.channel_id??'',title:today.title??'',channel_name:today.channel_name??'',lifecycle_state:today.lifecycle_state??'unknown',scheduled_start:validTime(today.scheduled_start)?today.scheduled_start:null,...bounds};
 }
 const history=await db.prepare('SELECT video_id,title,channel_id,channel_name,scheduled_start,actual_start,actual_end,source_revision FROM public_history WHERE video_id=? LIMIT 1').bind(id).first();
 if(history){
  const bounds=trustedBounds(history,TRUSTED_HISTORY.has(history.source_revision));
  return {video_id:history.video_id,channel_id:history.channel_id??'',title:history.title??'',channel_name:history.channel_name??'',lifecycle_state:'ended',scheduled_start:validTime(history.scheduled_start)?history.scheduled_start:null,...bounds};
 }
 const legacy=await db.prepare('SELECT video_id,title,channel_id,channel_name,lifecycle_state,scheduled_start FROM public_catalog WHERE video_id=? LIMIT 1').bind(id).first();
 if(!legacy)return null;
 return {video_id:legacy.video_id,channel_id:legacy.channel_id??'',title:legacy.title??'',channel_name:legacy.channel_name??'',lifecycle_state:legacy.lifecycle_state??'unknown',scheduled_start:validTime(legacy.scheduled_start)?legacy.scheduled_start:null,actual_start:null,actual_end:null};
}

export async function handleVideoMetadataRead(request,env,{now=new Date()}={}){
 if(!request||request.method!=='GET')return json({error:'method_not_allowed'},405,0);
 let url;
 try{url=new URL(request.url)}catch{return json({error:'bad_request'},400,0)}
 const parts=url.pathname.split('/').filter(Boolean);
 if(parts.length!==4||parts[0]!=='v1'||parts[1]!=='videos'||parts[3]!=='metadata')return json({error:'not_found'},404,0);
 const id=parts[2];
 if(!VIDEO.test(id))return json({error:'invalid_video_id'},400,0);
 if(!env?.DB?.prepare)return json({error:'database_not_bound'},503,0);
 const catalog=await readCatalog(env.DB,id);
 if(catalog){const membership=await managedMembership(env.DB,catalog.channel_id);return json({...catalog,managed_channel:Boolean(membership),source:'catalog'},200,15);}
 const cached=await env.DB.prepare('SELECT video_id,channel_id,title,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,managed_channel,source,observed_at FROM public_video_metadata_cache WHERE video_id=? LIMIT 1').bind(id).first();
 if(cached)return json({...cached,managed_channel:Boolean(cached.managed_channel),source:'youtube-fallback'},200,15);

 const ptt=await verifiedPttPriority(env.DB,url);
 const registered=await registerDemand(env.DB,id,{...ptt,now});
 if(!registered.admitted){
  return json({error:'recovery_queue_busy',status:'queue_busy',video_id:id,lifecycle_state:'unknown',
   retry_after_seconds:Number(registered.retry_after_seconds||60),
   reason:String(registered.reason||'admission_limited'),
   priority:ptt.priority,ptt_priority:false},429,0);
 }
 const demand=registered.demand;
 if(demand?.status==='not_found'&&Date.parse(demand.next_attempt_at)>now.getTime()){
  return json({error:'metadata_not_found_cached',status:'not_found',video_id:id,lifecycle_state:'unknown',
   retry_after_seconds:Math.max(1,Math.ceil((Date.parse(demand.next_attempt_at)-now.getTime())/1000)),
   priority:Number(demand.priority),ptt_priority:Boolean(Number(demand.priority)===1)},404,0);
 }
 return json({status:'metadata_pending',video_id:id,lifecycle_state:'unknown',
  retry_after_seconds:60,priority:Number(demand?.priority??ptt.priority),
  ptt_priority:Boolean(Number(demand?.priority??ptt.priority)===1),
  demand_state:String(demand?.status||'pending'),
  demand_reused:Boolean(registered.reused)},202,0);
}
