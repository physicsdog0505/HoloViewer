import {fetchYoutubeVideoMetadata} from './youtube-metadata-provider.mjs';
import {writeEvidence,YOUTUBE_LIVE_SOURCE} from './store.mjs';
import {signature} from './today-private-post.mjs';

const enc=new TextEncoder();
const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const VIDEO_COOLDOWN_MS=60_000;
const BUDGET_WINDOW_MS=10*60_000;
const BUDGET_MAX_CALLS=30;
function stamp(ms){return new Date(ms).toISOString().replace(/\.\d{3}Z$/,'Z');}
function windowStart(ms){return Math.floor(ms/BUDGET_WINDOW_MS)*BUDGET_WINDOW_MS;}
function retryAfterSeconds(nowMs){return Math.max(1,Math.ceil((windowStart(nowMs)+BUDGET_WINDOW_MS-nowMs)/1000));}
async function reserveProviderBudget(db,nowMs){
 const bucket=stamp(windowStart(nowMs));
 const budget=await db.prepare(
  'INSERT INTO public_video_metadata_recovery_budget(window_start,calls,updated_at) VALUES(?,1,?) '+
  'ON CONFLICT(window_start) DO UPDATE SET calls=public_video_metadata_recovery_budget.calls+1,updated_at=excluded.updated_at '+
  'WHERE public_video_metadata_recovery_budget.calls<?'
 ).bind(bucket,stamp(nowMs),BUDGET_MAX_CALLS).run();
 return Number(budget?.meta?.changes??budget?.changes??0)!==0;
}
async function cachedWithinCooldown(db,videoId,nowMs){
 const cached=await db.prepare('SELECT video_id,channel_id,title,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,managed_channel,source,observed_at FROM public_video_metadata_cache WHERE video_id=? LIMIT 1').bind(videoId).first();
 return cached&&Date.parse(cached.observed_at)>=nowMs-VIDEO_COOLDOWN_MS?cached:null;
}
function reply(body,status){return new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});}
function equal(a,b){if(!/^[a-f0-9]{64}$/.test(a)||b.length!==64)return false;let diff=0;for(let i=0;i<64;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);return diff===0;}
async function approvedMembership(db,channelId){
 return await db.prepare('SELECT ac.roster_version,ac.channel_group FROM public_today_approved_channels ac JOIN public_today_catalog_meta m ON m.singleton=1 AND m.roster_version=ac.roster_version WHERE ac.channel_id=? LIMIT 1').bind(channelId).first();
}
export async function recoverVideoMetadataServerOwned(env,videoId,{fetchImpl=fetch,now=new Date()}={}){
 if(!VIDEO.test(videoId??''))return {status:400,body:{error:'invalid_video_id'}};
 if(!env?.DB||!env?.YOUTUBE_API_KEY)return {status:503,body:{error:'recovery_disabled'}};
 const nowMs=now.getTime();
 const cached=await cachedWithinCooldown(env.DB,videoId,nowMs);
 if(cached)return {status:200,body:{status:'cached',video_id:videoId,managed_channel:Boolean(cached.managed_channel),source:'youtube-fallback',cooldown_seconds:60}};
 if(!(await reserveProviderBudget(env.DB,nowMs)))return {status:429,body:{error:'recovery_budget_exhausted',retry_after_seconds:retryAfterSeconds(nowMs)}};
 let meta;
 try{meta=await fetchYoutubeVideoMetadata(env,videoId,{fetchImpl,now});}
 catch{return {status:503,body:{error:'youtube_metadata_unavailable'}}}
 if(!meta)return {status:404,body:{error:'youtube_video_not_found'}};
 const membership=await approvedMembership(env.DB,meta.channel_id);
 const managed=Boolean(membership);
 const observed_at=stamp(nowMs);
 await env.DB.prepare('INSERT INTO public_video_metadata_cache(video_id,channel_id,title,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,managed_channel,source,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,title=excluded.title,channel_name=excluded.channel_name,lifecycle_state=excluded.lifecycle_state,scheduled_start=excluded.scheduled_start,actual_start=excluded.actual_start,actual_end=excluded.actual_end,managed_channel=excluded.managed_channel,source=excluded.source,observed_at=excluded.observed_at WHERE excluded.observed_at>=public_video_metadata_cache.observed_at')
  .bind(meta.video_id,meta.channel_id,meta.title??'',meta.channel_name??'',meta.lifecycle_state,meta.scheduled_start??null,meta.actual_start??null,meta.actual_end??null,managed?1:0,'youtube-fallback',observed_at).run();
 let ingestion={status:'not_managed_or_not_livestream'};
 if(managed&&meta.is_livestream){
  const lifecycle=meta.lifecycle_state==='waiting'?'upcoming':meta.lifecycle_state;
  ingestion=await writeEvidence(env.DB,{video_id:meta.video_id,channel_id:meta.channel_id,roster_version:membership.roster_version,group:membership.channel_group,title:meta.title??'',channel_name:meta.channel_name??'',lifecycle_state:lifecycle,observed_at,scheduled_start:meta.scheduled_start??null,actual_start:meta.actual_start??null,actual_end:meta.actual_end??null,source_label:YOUTUBE_LIVE_SOURCE},{projectHistory:false});
 }
 const history_candidate=managed&&meta.lifecycle_state==='ended'&&Boolean(meta.actual_start&&meta.actual_end&&Date.parse(meta.actual_end)>Date.parse(meta.actual_start));
 return {status:200,body:{status:'recovered',video_id:meta.video_id,managed_channel:managed,is_livestream:meta.is_livestream,ingestion,history_candidate,source:'youtube-fallback'}};
}

export async function processVideoMetadataDemands(env,{fetchImpl=fetch,now=new Date(),limit=4,preferredVideoId=''}={}){
 if(!env?.DB||!env?.YOUTUBE_API_KEY)return {processed:0,resolved:0,pending:0,budget_exhausted:false};
 const nowIso=stamp(now.getTime());
 const staleBefore=stamp(now.getTime()-2*60_000);
 await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='pending',updated_at=?,next_attempt_at=?,last_error='stale_processing_requeued' WHERE status='processing' AND updated_at<?")
  .bind(nowIso,nowIso,staleBefore).run();
 let rows=[];
 if(preferredVideoId){
  const row=await env.DB.prepare("SELECT * FROM public_video_metadata_recovery_demand WHERE video_id=? AND status='pending' AND next_attempt_at<=? LIMIT 1").bind(preferredVideoId,nowIso).first();
  if(row)rows=[row];
 }
 if(rows.length<limit){
  const extra=await env.DB.prepare("SELECT * FROM public_video_metadata_recovery_demand WHERE status='pending' AND next_attempt_at<=? AND video_id<>? ORDER BY priority ASC, requested_at ASC LIMIT ?").bind(nowIso,preferredVideoId||'',Math.max(0,limit-rows.length)).all();
  rows.push(...(extra?.results??[]));
 }
 let processed=0,resolved=0,budget_exhausted=false;
 for(const row of rows){
  const claim=await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='processing',updated_at=? WHERE video_id=? AND status='pending'").bind(nowIso,row.video_id).run();
  if(Number(claim?.meta?.changes??claim?.changes??0)===0)continue;
  processed++;
  const result=await recoverVideoMetadataServerOwned(env,row.video_id,{fetchImpl,now});
  if(result.status===200){
   await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='resolved',updated_at=?,attempts=attempts+1,last_error=NULL WHERE video_id=?").bind(nowIso,row.video_id).run();
   resolved++;
   continue;
  }
  if(result.status===429){
   const next=stamp(now.getTime()+Number(result.body.retry_after_seconds||1)*1000);
   await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='pending',updated_at=?,next_attempt_at=?,last_error='recovery_budget_exhausted' WHERE video_id=?").bind(nowIso,next,row.video_id).run();
   budget_exhausted=true;
   break;
  }
  if(result.status===404){
   const next=stamp(now.getTime()+10*60_000);
   await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='not_found',updated_at=?,next_attempt_at=?,attempts=attempts+1,last_error='youtube_video_not_found' WHERE video_id=?").bind(nowIso,next,row.video_id).run();
   continue;
  }
  const next=stamp(now.getTime()+60_000);
  await env.DB.prepare("UPDATE public_video_metadata_recovery_demand SET status='pending',updated_at=?,next_attempt_at=?,attempts=attempts+1,last_error=? WHERE video_id=?").bind(nowIso,next,String(result.body?.error||'recovery_failed'),row.video_id).run();
 }
 const pendingRow=await env.DB.prepare("SELECT COUNT(*) AS n FROM public_video_metadata_recovery_demand WHERE status='pending'").first();
 return {processed,resolved,pending:Number(pendingRow?.n??0),budget_exhausted};
}

export async function handleVideoMetadataRecovery(request,env,{fetchImpl=fetch,now=new Date()}={}){
 const url=new URL(request.url);
 if(url.pathname!=='/internal/videos/metadata/recover')return reply({error:'not_found'},404);
 if(request.method!=='POST')return reply({error:'method_not_allowed'},405);
 if(env?.TODAY_PUBLISH_ENABLED!=='true'||!env?.TODAY_PUBLISH_HMAC_SECRET||!env?.DB||!env?.YOUTUBE_API_KEY)return reply({error:'recovery_disabled'},503);
 const timestamp=request.headers.get('x-today-timestamp')??'';
 const mac=request.headers.get('x-today-signature')??'';
 if(!/^\d{13}$/.test(timestamp)||Math.abs(now.getTime()-Number(timestamp))>120000)return reply({error:'invalid_timestamp'},401);
 const raw=await request.text();
 if(enc.encode(raw).length>4096)return reply({error:'payload_too_large'},413);
 const expected=await signature(env.TODAY_PUBLISH_HMAC_SECRET,timestamp,raw);
 if(!equal(mac,expected))return reply({error:'bad_signature'},401);
 let body;try{body=JSON.parse(raw)}catch{return reply({error:'invalid_json'},400)}
 const videoId=body?.video_id;
 if(!VIDEO.test(videoId??''))return reply({error:'invalid_video_id'},400);

 const nowMs=now.getTime();
 const replayKey=mac;
 await env.DB.prepare('DELETE FROM public_video_metadata_recovery_replay WHERE expires_at<?').bind(stamp(nowMs)).run();
 const replay=await env.DB.prepare('INSERT OR IGNORE INTO public_video_metadata_recovery_replay(replay_key,accepted_at,expires_at) VALUES(?,?,?)')
  .bind(replayKey,stamp(nowMs),stamp(nowMs+120000)).run();
 if(Number(replay?.meta?.changes??replay?.changes??0)===0)return reply({status:'replay_suppressed',video_id:videoId},200);
 const result=await recoverVideoMetadataServerOwned(env,videoId,{fetchImpl,now});
 return reply(result.body,result.status);
}

export function mountVideoMetadataRecoveryOnWorker(base,{fetchImpl=fetch}={}){
 if(!base||typeof base.fetch!=='function')throw Error('existing worker required');
 return {
  async fetch(request,env,ctx){
   const path=new URL(request.url).pathname;
   if(path==='/internal/videos/metadata/recover')return handleVideoMetadataRecovery(request,env,{fetchImpl});
   return base.fetch(request,env,ctx);
  },
  async scheduled(event,env,ctx){
   const baseResult=typeof base.scheduled==='function'?await base.scheduled(event,env,ctx):undefined;
   const now=Number.isFinite(event?.scheduledTime)?new Date(event.scheduledTime):new Date();
   const recovery=await processVideoMetadataDemands(env,{now,limit:4});
   return {base:baseResult,recovery};
  }
 };
}
