// #48 HMAC control-plane request authentication; existing API Worker only.
// Signature covers exact raw body and freshness timestamp, with no secrets logged.
// The caller must supply env.PTT_PUBLISH_HMAC_SECRET as a managed secret.
// Replays within the freshness window are safe only when upstream batch
// identity is idempotent; never use this alone as a single-writer lock.
const te=new TextEncoder();
const HEX=/^[a-f0-9]{64}$/;
function equalConstantTime(left,right) {
  if(left.length!==right.length)return false;
  let diff=0;for(let i=0;i<left.length;i++) diff |= left.charCodeAt(i)^right.charCodeAt(i);
  return diff===0;
}
export async function authorizePttHmac(request,env,body,{nowMs=Date.now()}={}) {
  const secret=env?.PTT_PUBLISH_HMAC_SECRET;
  if(typeof secret!=='string' || secret.length<32 || typeof body!=='string')return false;
  const stamp=request.headers.get('x-ptt-timestamp');
  const signed=request.headers.get('x-ptt-signature');
  if(!/^\d{13}$/.test(stamp||'') || !HEX.test(signed||''))return false;
  const when=Number(stamp);
  if(!Number.isSafeInteger(when) || Math.abs(nowMs-when)>60000)return false;
  const key=await crypto.subtle.importKey('raw',te.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const value=await crypto.subtle.sign('HMAC',key,te.encode(stamp+'\n'+body));
  const actual=[...new Uint8Array(value)].map(b=>b.toString(16).padStart(2,'0')).join('');
  return equalConstantTime(actual,signed);
}
