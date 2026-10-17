// Proof that an owner separately reviewed the exact source row's event time.
// HMAC secret is distinct from the HTTP transport HMAC secret.
// This checks an operator attestation, NOT independently proves PTT push year.
const te=new TextEncoder();
const HEX=/^[0-9a-f]{64}$/;
export function canonicalTimeMessage(row) {
  return JSON.stringify([row.aid,row.source_line,row.source_record_key,
    row.push_id,row.occurred_at,row.source_url]);
}
export async function verifyPublisherTimeProof(row,env) {
  const secret=env?.PTT_TIME_AUTHORITY_SECRET;
  if(typeof secret!=='string'||secret.length<32||!HEX.test(row?.time_proof??''))
    return false;
  const key=await crypto.subtle.importKey('raw',te.encode(secret),
    {name:'HMAC',hash:'SHA-256'},false,['sign']);
  const result=await crypto.subtle.sign('HMAC',key,te.encode(canonicalTimeMessage(row)));
  const actual=[...new Uint8Array(result)].map(x=>x.toString(16).padStart(2,'0')).join('');
  let diff=0;
  for(let i=0;i<64;i++)diff|=actual.charCodeAt(i)^row.time_proof.charCodeAt(i);
  return diff===0;
}
