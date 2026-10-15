/**
 * #47 reconstructable existing API routing seam.
 * This module is NOT a byte-for-byte export of the deployed Worker: original
 * complete source has not been committed. Do not deploy without comparing to
 * Owner-supplied code, CORS origins and compatibility routes.
 */
import {handleTodayRead} from './worker-read.mjs';
const DEFAULT_ORIGINS=['https://holoviewer-public.singlebagel.workers.dev'];
function decorate(response,origin,approved){
  const h=new Headers(response.headers);
  h.set('x-content-type-options','nosniff');
  h.set('vary','Origin');
  if(origin && approved.has(origin)){h.set('access-control-allow-origin',origin);h.set('access-control-allow-methods','GET, OPTIONS');h.set('access-control-allow-headers','Content-Type');}
  return new Response(response.body,{status:response.status,headers:h});
}
function json(data,status=200){return new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});}
export function createExistingApiRouter({allowedOrigins=DEFAULT_ORIGINS,legacyHistory,legacyVideo,pttHandler=null}={}){
 const approved=new Set(allowedOrigins);
 return {async fetch(request,env){
   const u=new URL(request.url),origin=request.headers.get('origin');
   const validOrigin=!origin||approved.has(origin);
   if(!validOrigin)return decorate(json({error:'forbidden_origin'},403),origin,approved);
   if(request.method==='OPTIONS')return decorate(new Response(null,{status:204}),origin,approved);
   if(request.method!=='GET')return decorate(json({error:'method_not_allowed'},405),origin,approved);
   if(u.pathname==='/health')return decorate(json({ok:Boolean(env?.DB)} ,env?.DB?200:503),origin,approved);
   if(!env?.DB)return decorate(json({error:'service_unavailable'},503),origin,approved);
   let result;
   if(u.pathname==='/v1/catalog/today')result=await handleTodayRead(request,env);
   else if((u.pathname==='/v1/ptt/today'||u.pathname==='/v1/ptt/history')&&pttHandler)result=await pttHandler(request,env);
   else if(u.pathname==='/v1/history'&&legacyHistory)result=await legacyHistory(request,env);
   else if(/^\/v1\/catalog\/videos\/[A-Za-z0-9_-]{11}$/.test(u.pathname)&&legacyVideo)result=await legacyVideo(request,env);
   else result=json({error:'not_found'},404);
   return decorate(result,origin,approved);
 }};
}
