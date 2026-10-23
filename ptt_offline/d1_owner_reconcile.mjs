// #48 private read-only exact-batch reconciliation for resilient Publisher recovery.
// Authenticated with the existing PTT owner HMAC. Never mutates D1.
import {batchDigest} from './d1_owner_writer.mjs';
import {authorizePttHmac} from './ptt_owner_hmac.mjs';

const MAX_ROWS=25;
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,
  headers:{'content-type':'application/json','cache-control':'no-store'}});

export async function inspectAuthorizedPttBatch({DB,batch}) {
  if(!DB || typeof DB.prepare!=='function') throw new Error('database_unavailable');
  if(!batch || !Array.isArray(batch.rows) || batch.rows.length<1 || batch.rows.length>MAX_ROWS)
    throw new Error('invalid_batch');
  if(batch.request_cap!==1 || batch.retry_cap!==0 || typeof batch.digest!=='string')
    throw new Error('invalid_batch');
  const digest=await batchDigest(batch);
  if(digest!==batch.digest || batch.batch_id!=='ptt48:'+digest.slice(0,24))
    throw new Error('batch_checksum_mismatch');

  const pushIds=batch.rows.map(row=>row.push_id);
  const pushRead=await DB.prepare(
    'SELECT push_id,aid,day,source_line,author,content,occurred_at,source_url FROM ptt_pushes WHERE push_id IN ('+
    pushIds.map(()=>'?').join(',')+')'
  ).bind(...pushIds).all();
  if(!Array.isArray(pushRead?.results)) throw new Error('push_readback_failed');

  const evidenceWhere=batch.rows.map(()=>'(day=? AND aid=? AND source_record_key=?)').join(' OR ');
  const evidenceArgs=batch.rows.flatMap(row=>[row.day,row.aid,row.source_record_key]);
  const evidenceRead=await DB.prepare(
    'SELECT day,aid,source_record_key,push_id,source_line FROM ptt_source_evidence WHERE '+evidenceWhere
  ).bind(...evidenceArgs).all();
  if(!Array.isArray(evidenceRead?.results)) throw new Error('evidence_readback_failed');

  const pushes=new Map(pushRead.results.map(row=>[row.push_id,row]));
  const evidence=new Map(evidenceRead.results.map(row=>[
    row.day+':'+row.aid+':'+row.source_record_key,row
  ]));

  let present=0;
  let mismatched=0;
  const rows=batch.rows.map(row=>{
    const p=pushes.get(row.push_id);
    const e=evidence.get(row.day+':'+row.aid+':'+row.source_record_key);
    const none=!p && !e;
    const exact=Boolean(
      p && e &&
      p.aid===row.aid && p.day===row.day && p.source_line===row.source_line &&
      p.author===row.author && p.content===row.content &&
      p.occurred_at===row.occurred_at && p.source_url===row.source_url &&
      e.push_id===row.push_id && e.source_line===row.source_line
    );
    if(exact)present++;
    else if(!none)mismatched++;
    return {push_id:row.push_id,source_record_key:row.source_record_key,
      source_line:row.source_line,state:exact?'PRESENT':none?'ABSENT':'MISMATCH'};
  });
  const outcome=mismatched?'PARTIAL_OR_MISMATCH'
    :present===batch.rows.length?'ALL_PRESENT'
    :present===0?'NONE_PRESENT':'PARTIAL_OR_MISMATCH';
  return {status:'RECONCILE',outcome,batch_id:batch.batch_id,digest:batch.digest,
    rows_checked:batch.rows.length,present,mismatched,rows};
}

export async function handleOwnerPttReconcile(request,env,{authorize}={}) {
  if(request.method!=='POST') return json({error:'method_not_allowed'},405);
  if(!env?.DB || typeof env.DB.prepare!=='function') return json({error:'database_unavailable'},503);
  const maxBytes=131072;
  const size=Number(request.headers.get('content-length')||0);
  if(size>maxBytes) return json({error:'payload_too_large'},413);
  let raw;
  try {
    raw=await request.text();
    if(new TextEncoder().encode(raw).length>maxBytes) return json({error:'payload_too_large'},413);
  } catch {return json({error:'invalid_body'},400);}
  try {
    const verified=typeof authorize==='function'
      ? await authorize(request,env,raw)===true
      : await authorizePttHmac(request,env,raw);
    if(!verified) return json({error:'unauthorized'},401);
  } catch {return json({error:'unauthorized'},401);}
  let batch;
  try {batch=JSON.parse(raw);} catch {return json({error:'invalid_json'},400);}
  try {return json(await inspectAuthorizedPttBatch({DB:env.DB,batch}));}
  catch {return json({error:'reconcile_unavailable'},503);}
}
