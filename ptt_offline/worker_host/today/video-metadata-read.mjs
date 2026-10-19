import {fetchYoutubeVideoMetadata} from './youtube-metadata-provider.mjs';

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
async function managedChannel(db,channelId){
 if(!channelId)return false;
 const row=await db.prepare('SELECT 1 AS ok FROM public_today_approved_channels WHERE channel_id=? LIMIT 1').bind(channelId).first();
 return Boolean(row?.ok);
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
export async function handleVideoMetadataRead(request,env,{fetchImpl=fetch,now=new Date()}={}){
 if(!request||request.method!=='GET')return json({error:'method_not_allowed'},405,0);
 let url;
 try{url=new URL(request.url)}catch{return json({error:'bad_request'},400,0)}
 const parts=url.pathname.split('/').filter(Boolean);
 if(parts.length!==4||parts[0]!=='v1'||parts[1]!=='videos'||parts[3]!=='metadata')return json({error:'not_found'},404,0);
 const id=parts[2];
 if(!VIDEO.test(id))return json({error:'invalid_video_id'},400,0);
 if(!env?.DB?.prepare)return json({error:'database_not_bound'},503,0);
 const catalog=await readCatalog(env.DB,id);
 if(catalog)return json({...catalog,managed_channel:await managedChannel(env.DB,catalog.channel_id),source:'catalog'},200,15);
 let meta;
 try{meta=await fetchYoutubeVideoMetadata(env,id,{fetchImpl,now});}
 catch{return json({error:'youtube_metadata_unavailable',video_id:id,lifecycle_state:'unknown'},503,0);}
 if(!meta)return json({error:'youtube_video_not_found',video_id:id,lifecycle_state:'unknown'},404,0);
 return json({...meta,managed_channel:await managedChannel(env.DB,meta.channel_id),source:'youtube-fallback'},200,15);
}
