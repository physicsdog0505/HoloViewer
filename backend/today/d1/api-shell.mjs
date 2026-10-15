/** #47 legacy Worker shell behavior-preserving reviewable seam. Never deploy without exact owner source comparison. */
import {handleTodayRead} from './worker-read.mjs';
function allowed(env){return new Set(String(env?.ALLOWED_ORIGIN??'').split(',').map(x=>x.trim()).filter(Boolean));}
function wrap(response,origin,origins){
 const headers=new Headers(response.headers);
 headers.set('x-content-type-options','nosniff');
 headers.set('vary','Origin');
 if(origin&&origins.has(origin)){
  headers.set('access-control-allow-origin',origin);
  headers.set('access-control-allow-methods','GET, OPTIONS');
  headers.set('access-control-allow-headers','Accept');
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
export function createExistingApiRouter({legacyHistory,legacyVideo,pttHandler=null}={}){
 return {async fetch(request,env){
  const u=new URL(request.url),origin=request.headers.get('origin');
  const origins=allowed(env);
  if(origin&&!origins.has(origin))return wrap(json({error:'origin_not_allowed'},403),origin,origins);
  if(request.method==='OPTIONS'){
   if(!origin)return wrap(json({error:'origin_required'},400),origin,origins);
   return wrap(new Response(null,{status:204,headers:{'cache-control':'public, max-age=0'}}),origin,origins);
  }
  if(request.method!=='GET')return wrap(json({error:'method_not_allowed'},405),origin,origins);
  if(u.pathname==='/health')return wrap(json({
   service:'holoviewer-public-read',
   status:env?.DB?'database_bound':'database_not_bound',
   schema:'v1'
  },env?.DB?200:503),origin,origins);
  if(!env?.DB)return wrap(json({error:'database_not_bound'},503),origin,origins);
  let response;
  if(u.pathname==='/v1/catalog/today')response=await handleTodayRead(request,env);
  else if((u.pathname==='/v1/ptt/today'||u.pathname==='/v1/ptt/history')&&pttHandler)response=await pttHandler(request,env);
  else if(u.pathname==='/v1/history'&&legacyHistory)response=await legacyHistory(request,env);
  else if(/^\/v1\/catalog\/videos\/[A-Za-z0-9_-]{11}$/.test(u.pathname)&&legacyVideo)response=await legacyVideo(request,env);
  else response=json({error:'not_found'},404);
  return wrap(response,origin,origins);
 }};
}
