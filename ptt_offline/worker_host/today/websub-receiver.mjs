/** #47 WebSub ingress for Cloudflare-compatible runtimes.
 * Pure route logic. Runtime must inject durable saveEvent and an owner-approved
 * versioned roster. No implicit Worker/DB/queue creation or subscription activation.
 */
const enc=new TextEncoder();
const dec=new TextDecoder();
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const HUB='https://pubsubhubbub.appspot.com/subscribe';
const TOPIC='https://www.youtube.com/xml/feeds/videos.xml?channel_id=';
function json(body,status){return new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json','cache-control':'no-store'}});}
function hex(buf){return Array.from(new Uint8Array(buf),b=>b.toString(16).padStart(2,'0')).join('');}
function equal(a,b){if(a.length!==b.length)return false;let k=0;for(let i=0;i<a.length;i++)k|=a.charCodeAt(i)^b.charCodeAt(i);return k===0}
async function signed(raw,secret,algorithm){const key=await crypto.subtle.importKey('raw',enc.encode(secret),{name:'HMAC',hash:algorithm},false,['sign']);return hex(await crypto.subtle.sign('HMAC',key,raw));}
function approved(roster,channel){return typeof roster?.version==='string'&&roster.version.length>0&&Array.isArray(roster.channels)&&roster.channels.some(x=>x.id===channel&&CHANNEL.test(channel));}
export function parseAtomEnvelope(xml){
 if(typeof xml!=='string'||xml.length>65536||/<!DOCTYPE|<!ENTITY/i.test(xml))throw Error('invalid atom XML');
 const channel=xml.match(/<yt:channelId>\s*(UC[A-Za-z0-9_-]{22})\s*<\/yt:channelId>/)?.[1];
 const video=xml.match(/<yt:videoId>\s*([A-Za-z0-9_-]{11})\s*<\/yt:videoId>/)?.[1];
 if(!channel||!CHANNEL.test(channel))throw Error('atom channel missing');
 if(video&&!VIDEO.test(video))throw Error('atom video invalid');
 // Deleted-entry notifications may legitimately omit yt:videoId. Keep event
 // raw and require a separate parser/reconciliation before publishing lifecycle.
 return {channel_id:channel,video_id:video??null};
}
export async function handleWebSub(request,{roster,secret,saveEvent,callbackOrigin,confirmChallenge,authorizeDelivery,isApprovedChannel}={}){
 const url=new URL(request.url);
 if(url.pathname!=='/internal/today/websub')return json({error:'not_found'},404);
 if(!secret||!roster||typeof saveEvent!=='function')return json({error:'receiver_disabled'},503);
 async function isApproved(channel){
  if(!CHANNEL.test(channel??''))return false;
  if(typeof isApprovedChannel!=='function')return approved(roster,channel);
  return Boolean(await isApprovedChannel(channel,roster.version));
 }
 if(request.method==='GET'){
  const mode=url.searchParams.get('hub.mode'),topic=url.searchParams.get('hub.topic');
  const challenge=url.searchParams.get('hub.challenge'),lease=url.searchParams.get('hub.lease_seconds');
  const channel=topic?.startsWith(TOPIC)?topic.slice(TOPIC.length):null;
  if(!['subscribe','unsubscribe'].includes(mode)||!channel||!challenge||challenge.length>1024||!/^\\d{1,9}$/.test(lease??''))
   return json({error:'challenge_rejected'},403);
  if(callbackOrigin&&url.origin!==callbackOrigin)return json({error:'callback_origin_mismatch'},403);
  let approvedTopic=false;
  try{approvedTopic=await isApproved(channel)}catch{return json({error:'roster_unavailable'},503)}
  if(!approvedTopic)return json({error:'challenge_rejected'},403);
  if(confirmChallenge){
   try{await confirmChallenge({channelId:channel,rosterVersion:roster.version,mode,leaseSeconds:Number(lease)})}
   catch{return json({error:'unrecognized_challenge'},403)}
  }
  return new Response(challenge,{status:200,headers:{'content-type':'text/plain; charset=utf-8','cache-control':'no-store'}});
 }
 if(request.method!=='POST')return json({error:'method_not_allowed'},405);
 const raw=await request.arrayBuffer();
 if(raw.byteLength>65536)return json({error:'oversize'},413);
 const signature=request.headers.get('x-hub-signature-256')??request.headers.get('x-hub-signature')??'';
 const match=signature.match(/^(sha1|sha256)=([a-fA-F0-9]{40}|[a-fA-F0-9]{64})$/);
 if(match && match[2].length!==(match[1]==='sha1'?40:64))return json({error:'signature_missing'},401);
 if(!match)return json({error:'signature_missing'},401);
 const expected=await signed(raw,secret,match[1]==='sha1'?'SHA-1':'SHA-256');
 if(!equal(expected,match[2].toLowerCase()))return json({error:'signature_rejected'},401);
 let event;
 try{event=parseAtomEnvelope(dec.decode(raw))}catch{return json({error:'invalid_atom'},400)}
 let approvedEvent=false;
 try{approvedEvent=await isApproved(event.channel_id)}catch{return json({error:'roster_unavailable'},503)}
 if(!approvedEvent)return json({error:'channel_not_approved'},403);
 if(authorizeDelivery){
  try{await authorizeDelivery(event.channel_id,roster.version)}catch{return json({error:'subscription_not_active'},403)}
 }
 try{
  await saveEvent({roster_version:roster.version,channel_id:event.channel_id,video_id:event.video_id,
   raw_xml:dec.decode(raw),raw_sha256:hex(await crypto.subtle.digest('SHA-256',raw))});
 }catch{return json({error:'durability_unconfirmed'},503)}
 return new Response(null,{status:204,headers:{'cache-control':'no-store'}});
}
export const subscriptionHub=HUB;
export const topicForChannel=id=>{if(!CHANNEL.test(id))throw Error('invalid channel');return TOPIC+id};
