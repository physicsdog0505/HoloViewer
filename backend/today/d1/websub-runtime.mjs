import {handleWebSub} from './websub-receiver.mjs';
import {persistEvent} from './websub-store.mjs';
import {confirmSubscriptionChallenge} from './websub-leases.mjs';
import {runTodayScheduled} from './cloud-scheduled.mjs';

function json(body,status){
 return new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json','cache-control':'no-store'}});
}
function parseRoster(env){
 if(!env?.TODAY_APPROVED_ROSTER)throw Error('roster missing');
 const roster=JSON.parse(env.TODAY_APPROVED_ROSTER);
 if(!roster?.version||!Array.isArray(roster.channels)||roster.channels.length<1||roster.channels.length>500)
  throw Error('invalid roster');
 return roster;
}
/** Mount #47 WebSub ingress/scheduled source onto the SAME existing API Worker.
 * No second Worker, no D1 migration, no implicit enablement.
 */
export function mountTodayWebSubOnWorker(base,{fetchImpl=fetch}={}){
 if(!base||typeof base.fetch!=='function')throw Error('existing worker required');
 return {
  async fetch(request,env,ctx){
   let url;
   try{url=new URL(request.url)}catch{return json({error:'bad_request'},400)}
   if(url.pathname!=='/internal/today/websub')return base.fetch(request,env,ctx);
   if(!env?.DB||typeof env.DB.prepare!=='function'||!env.TODAY_WEBSUB_SECRET)
    return json({error:'receiver_disabled'},503);
   let roster;
   try{roster=parseRoster(env)}catch{return json({error:'receiver_disabled'},503)}
   return handleWebSub(request,{
    roster,
    secret:String(env.TODAY_WEBSUB_SECRET),
    callbackOrigin:env.TODAY_WEBSUB_CALLBACK_ORIGIN?String(env.TODAY_WEBSUB_CALLBACK_ORIGIN):url.origin,
    saveEvent:event=>persistEvent(env.DB,event),
    confirmChallenge:args=>confirmSubscriptionChallenge(env.DB,args)
   });
  },
  async scheduled(event,env,ctx){
   if(typeof base.scheduled==='function')await base.scheduled(event,env,ctx);
   const now=Number.isFinite(event?.scheduledTime)?new Date(event.scheduledTime):new Date();
   return runTodayScheduled(env,{fetchImpl,now});
  }
 };
}
