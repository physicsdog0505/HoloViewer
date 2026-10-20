import {legacyHistory as defaultLegacyHistory,legacyVideo as defaultLegacyVideo} from './legacy-compat.mjs';
/** #47 legacy Worker shell behavior-preserving reviewable seam. Never deploy without exact owner source comparison. */
import {handleTodayRead} from './worker-read.mjs';
import {handleExperienceRead} from './experience-read.mjs';
import {handleVideoMetadataRead} from './video-metadata-read.mjs';
import {handleChannelProfileRead} from './channel-profile-read.mjs';
function allowed(env){return new Set(String(env?.ALLOWED_ORIGIN??'').split(',').map(x=>x.trim()).filter(Boolean));}
function wrap(response,origin,origins){
 const headers=new Headers(response.headers);
 headers.set('x-content-type-options','nosniff');
 headers.set('vary','Origin');
 if(origin&&origins.has(origin)){
  headers.set('access-control-allow-origin',origin);
  headers.set('access-control-allow-methods','GET, OPTIONS');
  headers.set('access-control-allow-headers','Accept');
  if(response.status===204)headers.set('access-control-max-age','600');
 }
 return new Response(response.body,{status:response.status,headers});
}
function json(data,status=200,age=0){
 return new Response(JSON.stringify(data),{status,headers:{
  'content-type':'application/json; charset=utf-8',
  'cache-control':'public, max-age='+age,
  'x-content-type-options':'nosniff'
 }});
}
export function createExistingApiRouter({legacyHistory=defaultLegacyHistory,legacyVideo=defaultLegacyVideo,pttHandler=null}={}){
 return {async fetch(request,env,ctx){
  const u=new URL(request.url),origin=request.headers.get('origin');
  const origins=allowed(env);
  if(origin&&!origins.has(origin))return wrap(json({error:'origin_not_allowed'},403),origin,origins);
  if(request.method==='OPTIONS'){
   if(!origin)return wrap(json({error:'origin_required'},400),origin,origins);
   return wrap(new Response(null,{status:204}),origin,origins);
  }
  if(request.method!=='GET')return wrap(json({error:'method_not_allowed'},405),origin,origins);
  if(u.pathname==='/health')return wrap(json({
   service:'holoviewer-public-read',
   status:env?.DB?'database_bound':'database_not_bound',
   schema:'v1'
  },env?.DB?200:503),origin,origins);
  if(!env?.DB)return wrap(json({error:'database_not_bound'},503),origin,origins);
  let response;
  try {
  if(u.pathname==='/v1/catalog/today')response=await handleTodayRead(request,env);
  else if(/^\/v1\/videos\/[A-Za-z0-9_-]{1,64}\/metadata$/.test(u.pathname))response=await handleVideoMetadataRead(request,env,{ctx});
  else if(/^\/v1\/channels\/UC[A-Za-z0-9_-]{22}\/profile$/.test(u.pathname))response=await handleChannelProfileRead(request,env);
  else if(u.pathname.startsWith('/v1/history/videos/')||u.pathname.startsWith('/v1/collab/')||u.pathname.startsWith('/v1/watchalong/'))response=await handleExperienceRead(request,env);
  else if((u.pathname==='/v1/ptt/today'||u.pathname==='/v1/ptt/history')&&pttHandler)response=await pttHandler(request,env);
  else if(u.pathname==='/v1/history'&&legacyHistory)response=await legacyHistory(request,env);
  else if(u.pathname.startsWith('/v1/catalog/videos/')&&legacyVideo)response=await legacyVideo(request,env);
  else response=json({error:'not_found'},404);
  } catch (error) {
   response=json({error:'read_projection_unavailable'},503);
  }
  return wrap(response,origin,origins);
 }};
}
