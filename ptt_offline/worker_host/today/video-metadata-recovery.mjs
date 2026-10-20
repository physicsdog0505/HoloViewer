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
function reply(body,status){return new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});}
function equal(a,b){if(!/^[a-f0-9]{64}$/.test(a)||b.length!==64)return false;let diff=0;for(let i=0;i<64;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);return diff===0;}
async function approvedMembership(db,channelId){
 return await db.prepare('SELECT ac.roster_version,ac.channel_group FROM public_today_approved_channels ac JOIN public_today_catalog_meta m ON m.singleton=1 AND m.roster_version=ac.roster_version WHERE ac.channel_id=? LIMIT 1').bind(channelId).first();
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

 const cached=await env.DB.prepare('SELECT video_id,channel_id,title,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,managed_channel,source,observed_at FROM public_video_metadata_cache WHERE video_id=? LIMIT 1').bind(videoId).first();
 if(cached&&Date.parse(cached.observed_at)>=nowMs-VIDEO_COOLDOWN_MS){
  return reply({status:'cached',video_id:videoId,managed_channel:Boolean(cached.managed_channel),source:'youtube-fallback',cooldown_seconds:60},200);
 }

 const bucket=stamp(windowStart(nowMs));
 const budget=await env.DB.prepare(
  'INSERT INTO public_video_metadata_recovery_budget(window_start,calls,updated_at) VALUES(?,1,?) '+
  'ON CONFLICT(window_start) DO UPDATE SET calls=public_video_metadata_recovery_budget.calls+1,updated_at=excluded.updated_at '+
  'WHERE public_video_metadata_recovery_budget.calls<?'
 ).bind(bucket,stamp(nowMs),BUDGET_MAX_CALLS).run();
 if(Number(budget?.meta?.changes??budget?.changes??0)===0){
  return reply({error:'recovery_budget_exhausted',retry_after_seconds:Math.max(1,Math.ceil((windowStart(nowMs)+BUDGET_WINDOW_MS-nowMs)/1000))},429);
 }
 let meta;try{meta=await fetchYoutubeVideoMetadata(env,videoId,{fetchImpl,now});}catch{return reply({error:'youtube_metadata_unavailable'},503)}
 if(!meta)return reply({error:'youtube_video_not_found'},404);
 const membership=await approvedMembership(env.DB,meta.channel_id);
 const managed=Boolean(membership);
 const observed_at=now.toISOString().replace(/\.\d{3}Z$/,'Z');
 await env.DB.prepare('INSERT INTO public_video_metadata_cache(video_id,channel_id,title,channel_name,lifecycle_state,scheduled_start,actual_start,actual_end,managed_channel,source,observed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET channel_id=excluded.channel_id,title=excluded.title,channel_name=excluded.channel_name,lifecycle_state=excluded.lifecycle_state,scheduled_start=excluded.scheduled_start,actual_start=excluded.actual_start,actual_end=excluded.actual_end,managed_channel=excluded.managed_channel,source=excluded.source,observed_at=excluded.observed_at WHERE excluded.observed_at>=public_video_metadata_cache.observed_at')
  .bind(meta.video_id,meta.channel_id,meta.title??'',meta.channel_name??'',meta.lifecycle_state,meta.scheduled_start??null,meta.actual_start??null,meta.actual_end??null,managed?1:0,'youtube-fallback',observed_at).run();
 let ingestion={status:'not_managed_or_not_livestream'};
 if(managed&&meta.is_livestream){
  const lifecycle=meta.lifecycle_state==='waiting'?'upcoming':meta.lifecycle_state;
  ingestion=await writeEvidence(env.DB,{video_id:meta.video_id,channel_id:meta.channel_id,roster_version:membership.roster_version,group:membership.channel_group,title:meta.title??'',channel_name:meta.channel_name??'',lifecycle_state:lifecycle,observed_at,scheduled_start:meta.scheduled_start??null,actual_start:meta.actual_start??null,actual_end:meta.actual_end??null,source_label:YOUTUBE_LIVE_SOURCE},{projectHistory:false});
 }
 const history_candidate=managed&&meta.lifecycle_state==='ended'&&Boolean(meta.actual_start&&meta.actual_end&&Date.parse(meta.actual_end)>Date.parse(meta.actual_start));
 return reply({status:'recovered',video_id:meta.video_id,managed_channel:managed,is_livestream:meta.is_livestream,ingestion,history_candidate,source:'youtube-fallback'},200);
}

export function mountVideoMetadataRecoveryOnWorker(base,{fetchImpl=fetch}={}){
 if(!base||typeof base.fetch!=='function')throw Error('existing worker required');
 return {
  async fetch(request,env,ctx){
   const path=new URL(request.url).pathname;
   if(path==='/internal/videos/metadata/recover')return handleVideoMetadataRecovery(request,env,{fetchImpl});
   return base.fetch(request,env,ctx);
  },
  async scheduled(event,env,ctx){return typeof base.scheduled==='function'?base.scheduled(event,env,ctx):undefined;}
 };
}
