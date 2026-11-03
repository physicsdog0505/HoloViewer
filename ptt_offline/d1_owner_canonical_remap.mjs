// Owner-only, incident-scoped canonical source-line remap forward repair.
// This is deliberately separate from ordinary publish. It has no DELETE,
// checkpoint, provider-state, thread, gap-repair, or reseed operation.
import {authorizePttHmac} from './ptt_owner_hmac.mjs';

const MAX_ROWS=5;
const PUSH=/^ptt:v1:[0-9a-f]{64}$/;
const DAY=/^\d{4}-\d{2}-\d{2}$/;
const UTC=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const INCIDENT_SCOPE=new Map([
  ['1gwHM4TF',new Set(Array.from({length:18},(_,i)=>383+i))],
  ['1gwRrK3P',new Set(Array.from({length:22},(_,i)=>1269+i))],
]);
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,
  headers:{'content-type':'application/json','cache-control':'no-store'}});
const fail=message=>{throw new Error(message)};
const requireTrue=(condition,message)=>{if(!condition)fail(message)};
const canonical=value=>{
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>
    JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
};
const identityKeys=['push_id','aid','day','source_line','kind','author','content',
  'occurred_at','floor','source_url','source_priority','source_record_key'];
const exact=(actual,expected)=>identityKeys.every(key=>(actual?.[key]??null)===(expected?.[key]??null));
const exactEvidence=(actual,identity)=>Boolean(actual && actual.day===identity.day &&
  actual.aid===identity.aid && actual.source_record_key===identity.source_record_key &&
  actual.push_id===identity.push_id && actual.source_line===identity.source_line);

export async function canonicalRemapDigest(batch) {
  const payload={repair_type:batch.repair_type,source_identity:batch.source_identity,
    day:batch.day,aid:batch.aid,source_lines:batch.source_lines,rows:batch.rows,
    request_cap:batch.request_cap,write_cap:batch.write_cap,retry_cap:batch.retry_cap};
  const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(payload)));
  return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');
}

function validateIdentity(row,day,aid,line) {
  requireTrue(row && PUSH.test(row.push_id) && row.aid===aid && row.day===day &&
    row.source_line===line && typeof row.kind==='string' &&
    typeof row.author==='string' && typeof row.content==='string' &&
    UTC.test(row.occurred_at||'') && typeof row.source_url==='string' &&
    Number.isInteger(row.source_priority) && row.source_priority>=0 &&
    row.source_record_key===aid+':'+line &&
    (row.floor===null || (Number.isSafeInteger(row.floor)&&row.floor>0)),
    'invalid remap identity');
}

async function readRemote(DB,batch) {
  const ids=[...new Set(batch.rows.flatMap(row=>[row.old.push_id,row.new.push_id]))];
  const pushRead=await DB.prepare(
    'SELECT push_id,aid,day,source_line,kind,author,content,occurred_at,floor,source_url,source_priority,source_record_key FROM ptt_pushes WHERE push_id IN ('+
    ids.map(()=>'?').join(',')+')').bind(...ids).all();
  requireTrue(Array.isArray(pushRead?.results),'remote push preflight failed');
  const where=batch.rows.map(()=>'(day=? AND aid=? AND source_record_key=?)').join(' OR ');
  const args=batch.rows.flatMap(row=>[row.old.day,row.old.aid,row.old.source_record_key]);
  const evidenceRead=await DB.prepare(
    'SELECT day,aid,source_record_key,push_id,source_line FROM ptt_source_evidence WHERE '+where
  ).bind(...args).all();
  requireTrue(Array.isArray(evidenceRead?.results),'remote evidence preflight failed');
  return {pushes:new Map(pushRead.results.map(row=>[row.push_id,row])),
    evidence:new Map(evidenceRead.results.map(row=>[
      row.day+':'+row.aid+':'+row.source_record_key,row]))};
}

export async function applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical}) {
  requireTrue(DB&&typeof DB.prepare==='function'&&typeof DB.batch==='function','existing D1 binding required');
  requireTrue(typeof verifyCanonical==='function','trusted Collector verifier required');
  requireTrue(batch?.repair_type==='CANONICAL_SOURCE_LINE_REMAP_V1','invalid repair type');
  requireTrue(Array.isArray(batch.rows)&&batch.rows.length>=1&&batch.rows.length<=MAX_ROWS,
    'bounded remap cap exceeded');
  requireTrue(batch.request_cap===1&&batch.retry_cap===0&&batch.write_cap===2*batch.rows.length,
    'unsafe remap budget');
  requireTrue(DAY.test(batch.day||'')&&INCIDENT_SCOPE.has(batch.aid)&&
    typeof batch.source_identity==='string'&&/^[0-9a-f]{64}$/.test(batch.source_identity),
    'invalid remap scope');
  requireTrue(Array.isArray(batch.source_lines)&&batch.source_lines.length===batch.rows.length,
    'exact source-line allowlist required');
  const uniqueLines=new Set(batch.source_lines);
  requireTrue(uniqueLines.size===batch.rows.length,'duplicate source-line scope');
  const scope=INCIDENT_SCOPE.get(batch.aid);
  for(const line of batch.source_lines)
    requireTrue(Number.isSafeInteger(line)&&scope.has(line),'source-line outside incident allowlist');
  const digest=await canonicalRemapDigest(batch);
  requireTrue(batch.digest===digest&&batch.batch_id==='ptt-remap-v1:'+digest.slice(0,24),
    'remap checksum mismatch');

  for(const [index,row] of batch.rows.entries()) {
    const line=batch.source_lines[index];
    validateIdentity(row.old,batch.day,batch.aid,line);
    validateIdentity(row.new,batch.day,batch.aid,line);
    requireTrue(row.old.push_id!==row.new.push_id,'remap identities must differ');
    requireTrue(await verifyCanonical(row.new,batch.source_identity)===true,
      'canonical Collector verification failed');
  }

  const before=await readRemote(DB,batch);
  let already=0;
  for(const row of batch.rows) {
    const key=row.old.day+':'+row.old.aid+':'+row.old.source_record_key;
    const oldPush=before.pushes.get(row.old.push_id);
    const newPush=before.pushes.get(row.new.push_id);
    const evidence=before.evidence.get(key);
    if(!oldPush && exact(newPush,row.new) && exactEvidence(evidence,row.new)) {
      already++;
      continue;
    }
    requireTrue(exact(oldPush,row.old)&&!newPush&&exactEvidence(evidence,row.old),
      'expected old remote identity mismatch');
  }
  if(already) {
    requireTrue(already===batch.rows.length,'mixed replay and unrepaired state rejected');
    return {status:'ALREADY_APPLIED',repair_type:batch.repair_type,batch_id:batch.batch_id,
      digest:batch.digest,logical_rows_repaired:0,rows_verified:batch.rows.length,
      d1_rows_written:0,d1_query_count:2,http_requests:1,live_checkpoint_mutations:0};
  }

  const statements=[];
  const SQL_PUSH=`UPDATE ptt_pushes SET push_id=?,aid=?,day=?,source_line=?,kind=?,author=?,content=?,occurred_at=?,floor=?,source_url=?,source_priority=?,source_record_key=?
    WHERE push_id=? AND aid=? AND day=? AND source_line=? AND kind=? AND author=? AND content=? AND occurred_at=?
      AND floor IS ? AND source_url=? AND source_priority=? AND source_record_key=?`;
  const SQL_EVIDENCE=`UPDATE ptt_source_evidence SET push_id=?,source_line=?
    WHERE day=? AND aid=? AND source_record_key=? AND push_id=? AND source_line=?`;
  for(const row of batch.rows) {
    const n=row.new,o=row.old;
    statements.push(DB.prepare(SQL_PUSH).bind(...identityKeys.map(key=>n[key]??null),
      ...identityKeys.map(key=>o[key]??null)));
    statements.push(DB.prepare(SQL_EVIDENCE).bind(n.push_id,n.source_line,o.day,o.aid,
      o.source_record_key,o.push_id,o.source_line));
  }
  requireTrue(statements.length===batch.write_cap,'remap write budget mismatch');
  const results=await DB.batch(statements);
  requireTrue(Array.isArray(results)&&results.length===statements.length&&
    results.every(result=>result?.meta?.changes===1),
    'remap transaction not exactly applied; remote state uncertain, do not retry');

  const after=await readRemote(DB,batch);
  for(const row of batch.rows) {
    const key=row.new.day+':'+row.new.aid+':'+row.new.source_record_key;
    requireTrue(!after.pushes.has(row.old.push_id)&&exact(after.pushes.get(row.new.push_id),row.new)&&
      exactEvidence(after.evidence.get(key),row.new),
      'remap readback mismatch; remote state uncertain, do not retry');
  }
  return {status:'ACK',repair_type:batch.repair_type,batch_id:batch.batch_id,
    digest:batch.digest,logical_rows_repaired:batch.rows.length,rows_verified:batch.rows.length,
    d1_rows_written:statements.length,d1_query_count:4+statements.length,
    http_requests:1,live_checkpoint_mutations:0};
}

export async function handleOwnerPttCanonicalRemap(request,env,{authorize,verifyCanonical}={}) {
  if(request.method!=='POST')return json({error:'method_not_allowed'},405);
  if(env?.PTT_CANONICAL_REMAP_ENABLED!=='true')return json({error:'canonical_remap_disabled'},503);
  if(!env?.DB||typeof env.DB.batch!=='function')return json({error:'database_unavailable'},503);
  if(typeof verifyCanonical!=='function')return json({error:'canonical_verifier_unavailable'},503);
  let raw;
  try {raw=await request.text();if(new TextEncoder().encode(raw).length>131072)return json({error:'payload_too_large'},413);}
  catch{return json({error:'invalid_body'},400);}
  try {
    const ok=typeof authorize==='function'?await authorize(request,env,raw)===true:
      await authorizePttHmac(request,env,raw);
    if(!ok)return json({error:'unauthorized'},401);
  } catch{return json({error:'unauthorized'},401);}
  let batch;try{batch=JSON.parse(raw)}catch{return json({error:'invalid_json'},400)}
  try{return json(await applyAuthorizedCanonicalRemap({DB:env.DB,batch,
    verifyCanonical:(row,sourceIdentity)=>verifyCanonical(row,sourceIdentity,env)}));}
  catch{return json({error:'canonical_remap_not_confirmed',reconcile_required:true},409);}
}

export const canonicalRemapIncidentScope=()=>new Map([...INCIDENT_SCOPE].map(([aid,lines])=>[aid,new Set(lines)]));
