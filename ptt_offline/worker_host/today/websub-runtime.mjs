import {handleWebSub} from './websub-receiver.mjs';
import {persistEvent} from './websub-store.mjs';
import {confirmSubscriptionChallenge,readSubscriptionLeases} from './websub-leases.mjs';
import {renewSubscriptions} from './websub-renewal-send.mjs';
import {refreshPendingVideos} from './websub-status.mjs';

const CID=/^UC[A-Za-z0-9_-]{22}$/;
const VID=/^[A-Za-z0-9_-]{11}$/;
const GROUPS=new Set(['hololive','holostars','mekpark','other']);
const HUB='https://pubsubhubbub.appspot.com/subscribe';

function json(body,status){
 return new Response(JSON.stringify(body),{status,headers:{
  'content-type':'application/json; charset=utf-8','cache-control':'no-store','x-content-type-options':'nosniff'
 }});
}
function stamp(d){return d.toISOString().replace(/\.\d{3}Z$/,'Z');}
function enabled(env,key){return env?.[key]==='true';}
function configuredCallback(env){
 const raw=env?.TODAY_WEBSUB_CALLBACK_URL;
 if(typeof raw!=='string'||raw.length>2048)return null;
 try{
  const u=new URL(raw);
  if(u.protocol!=='https:'||u.username||u.password||u.port||u.pathname!=='/internal/today/websub'||u.search||u.hash)return null;
  return u;
 }catch{return null;}
}
/** Use the D1-approved Today roster; never substitute an env/file roster or avatar registry. */
export async function loadApprovedTodayRoster(db){
 if(!db?.prepare)throw Error('Today DB unavailable');
 const meta=await db.prepare('SELECT roster_version,expected_channels FROM public_today_catalog_meta WHERE singleton=1').first();
 if(typeof meta?.roster_version!=='string'||!meta.roster_version||
   !Number.isInteger(meta.expected_channels)||meta.expected_channels<1||meta.expected_channels>500)
  throw Error('approved Today roster metadata unavailable');
 const got=await db.prepare('SELECT channel_id,channel_group FROM public_today_approved_channels WHERE roster_version=? ORDER BY channel_id')
  .bind(meta.roster_version).all();
 const rows=got.results??[];
 if(rows.length!==meta.expected_channels)throw Error('approved Today roster row count mismatch');
 const seen=new Set();
 const channels=rows.map(r=>{
  if(!CID.test(r.channel_id??'')||!GROUPS.has(r.channel_group)||seen.has(r.channel_id))
   throw Error('invalid approved Today roster row');
  seen.add(r.channel_id);
  return {id:r.channel_id,group:r.channel_group};
 });
 return {version:meta.roster_version,channels,expected_channels:meta.expected_channels};
}
function videoFetcher(env,fetchImpl){
 return async ids=>{
  if(!Array.isArray(ids)||!ids.length||ids.length>25||ids.some(id=>!VID.test(id)))throw Error('invalid bounded WebSub videos.list batch');
  const url=new URL('https://www.googleapis.com/youtube/v3/videos');
  url.searchParams.set('part','snippet,liveStreamingDetails');
  url.searchParams.set('id',ids.join(','));
  url.searchParams.set('key',String(env.YOUTUBE_API_KEY));
  const response=await fetchImpl(url.toString(),{headers:{accept:'application/json'},signal:AbortSignal.timeout(12000)});
  if(!response.ok)throw Error('YouTube videos.list failed HTTP '+response.status);
  const body=await response.json();
  if(!Array.isArray(body.items))throw Error('malformed videos.list');
  return body.items;
 }
}
function shouldRunRenewal(now){return now instanceof Date&&Number.isFinite(now.getTime())&&now.getUTCMinutes()===0;}
export {shouldRunRenewal};

export function mountTodayWebSubOnWorker(base,{fetchImpl=fetch}={}){
 if(!base||typeof base.fetch!=='function')throw Error('existing combined worker required');
 return {
  async fetch(request,env,ctx){
   let url;
   try{url=new URL(request.url)}catch{return json({error:'bad_request'},400);}
   if(url.pathname!=='/internal/today/websub')return base.fetch(request,env,ctx);
   if(!enabled(env,'TODAY_WEBSUB_RECEIVER_ENABLED'))return json({error:'receiver_disabled'},503);
   if(!env?.DB?.prepare||typeof env.TODAY_WEBSUB_SECRET!=='string'||env.TODAY_WEBSUB_SECRET.length<32)
    return json({error:'receiver_disabled'},503);
   const callback=configuredCallback(env);
   if(!callback)return json({error:'callback_not_configured'},503);
   let roster;
   try{roster=await loadApprovedTodayRoster(env.DB);}catch{return json({error:'approved_roster_unavailable'},503);}
   return handleWebSub(request,{
    roster,secret:env.TODAY_WEBSUB_SECRET,callbackOrigin:callback.origin,
    confirmChallenge:args=>confirmSubscriptionChallenge(env.DB,args),
    authorizeDelivery:async channelId=>{
     const lease=await env.DB.prepare('SELECT roster_version,state FROM public_today_websub_leases WHERE channel_id=?')
      .bind(channelId).first();
     if(!lease||lease.roster_version!==roster.version||lease.state!=='active')throw Error('no active roster-bound lease');
    },
    saveEvent:event=>persistEvent(env.DB,event)
   });
  },
  async scheduled(event,env,ctx){
   const baseResult=typeof base.scheduled==='function'?await base.scheduled(event,env,ctx):null;
   const now=Number.isFinite(event?.scheduledTime)?new Date(event.scheduledTime):new Date();
   const websub={processing:{status:'disabled',selected:0,updated:0},renewal:{status:'disabled',sent:0}};
   if(enabled(env,'TODAY_WEBSUB_PROCESS_ENABLED')){
    const roster=await loadApprovedTodayRoster(env.DB);
    if(!env?.YOUTUBE_API_KEY)throw Error('WebSub processor API credential missing');
    websub.processing=await refreshPendingVideos({
     db:env.DB,roster,fetchVideos:videoFetcher(env,fetchImpl),now,limit:25
    });
   }
   if(enabled(env,'TODAY_WEBSUB_RENEW_ENABLED')&&shouldRunRenewal(now)){
    const roster=await loadApprovedTodayRoster(env.DB);
    const callback=configuredCallback(env);
    if(!callback||typeof env?.TODAY_WEBSUB_SECRET!=='string'||env.TODAY_WEBSUB_SECRET.length<32)
     throw Error('WebSub renewal configuration missing');
    const leases=await readSubscriptionLeases(env.DB);
    websub.renewal=await renewSubscriptions({
     roster,leases,callback:callback.href,secret:env.TODAY_WEBSUB_SECRET,db:env.DB,
     enabled:true,limit:10,now,
     post:async(url,body)=>fetchImpl(url,{method:'POST',
      headers:{'content-type':'application/x-www-form-urlencoded'},
      body:body.toString(),signal:AbortSignal.timeout(12000)})
    });
   }else if(enabled(env,'TODAY_WEBSUB_RENEW_ENABLED')){
    websub.renewal={status:'cadence_skip',sent:0};
   }
   return {base:baseResult,websub};
  }
 };
}
