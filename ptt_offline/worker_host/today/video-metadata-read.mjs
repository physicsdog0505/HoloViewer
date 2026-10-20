import {YOUTUBE_LIVE_SOURCE} from './store.mjs';

const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const TRUSTED_TODAY='YouTube liveStreamingDetails';
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

export async function handleVideoMetadataRead(request,env){
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
 if(!cached)return json({error:'metadata_not_cached',video_id:id,lifecycle_state:'unknown'},404,0);
 return json({...cached,managed_channel:Boolean(cached.managed_channel),source:'youtube-fallback'},200,15);
}
