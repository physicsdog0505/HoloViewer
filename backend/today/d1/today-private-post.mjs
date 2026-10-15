/** Owner-gated Cloudflare one-shot Today ingest: private HMAC POST only.
 * Never mounted by the public GET router without an explicit integration.
 */
import {buildOneShotPlan,executeOneShot} from './one-shot-writer.mjs';
const enc=new TextEncoder();
function reply(body,status){return new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});}
function hex(bytes){return Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');}
export async function signature(secret,timestamp,body){
 const k=await crypto.subtle.importKey('raw',enc.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 return hex(await crypto.subtle.sign('HMAC',k,enc.encode(timestamp+'.'+body)));
}
function equal(a,b){
 if(!/^[a-f0-9]{64}$/.test(a)||b.length!==64)return false;
 let diff=0;for(let i=0;i<64;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);
 return diff===0;
}
export async function handleTodayPrivatePost(request,env,{now=Date.now()}={}){
 if(new URL(request.url).pathname!=='/internal/today/one-shot')return reply({error:'not_found'},404);
 if(request.method!=='POST')return reply({error:'method_not_allowed'},405);
 if(env?.TODAY_PUBLISH_ENABLED!=='true'||!env?.TODAY_PUBLISH_HMAC_SECRET||!env?.DB)
  return reply({error:'publisher_disabled'},503);
 const timestamp=request.headers.get('x-today-timestamp')??'';
 const mac=request.headers.get('x-today-signature')??'';
 if(!/^\d{13}$/.test(timestamp)||Math.abs(now-Number(timestamp))>120000)
  return reply({error:'invalid_timestamp'},401);
 const raw=await request.text();
 if(enc.encode(raw).length>131072)return reply({error:'payload_too_large'},413);
 const expected=await signature(env.TODAY_PUBLISH_HMAC_SECRET,timestamp,raw);
 if(!equal(mac,expected))return reply({error:'bad_signature'},401);
 let data;
 try{data=JSON.parse(raw)}catch{return reply({error:'invalid_json'},400)}
 try{
  const plan=buildOneShotPlan(data.receipt,data.approved_channels);
  const outcome=await executeOneShot(plan,env.DB,{explicitApproved:true});
  return reply({status:'verified',...outcome},200);
 }catch(error){
  return reply({error:'one_shot_failed_stop_no_auto_retry',detail:String(error.message).slice(0,180)},409);
 }
}
