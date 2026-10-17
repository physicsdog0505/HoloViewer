// #48 private owner-controlled D1 writer. Never mount as public route.
// Caller supplies authenticated authority and existing holoviewer-public-api env.DB.
const LIMIT = 25;
const boundedCap=(value,fallback,maximum)=>{const n=Number(value??fallback);return Number.isInteger(n)&&n>=1&&n<=maximum?n:null;};
const canonical=value=> {
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>
   JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value);
};
export async function batchDigest(batch) {
 const payload={source_identity:batch.source_identity,day:batch.day,rows:batch.rows,
  request_cap:batch.request_cap,write_cap:batch.write_cap,retry_cap:batch.retry_cap};
 const encoded=new TextEncoder().encode(canonical(payload));
 const bytes=await crypto.subtle.digest('SHA-256',encoded);
 return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,'0')).join('');
}
const fail = message => { throw new Error(message); };
const requireTrue = (condition,message) => { if(!condition) fail(message); };
const SQL_THREAD='INSERT INTO ptt_threads(day,aid,source_url) VALUES (?,?,?) ON CONFLICT(day,aid) DO UPDATE SET source_url=excluded.source_url WHERE ptt_threads.source_url IS NULL AND excluded.source_url IS NOT NULL';
const SQL_STATE="INSERT INTO ptt_provider_state(day,aid,last_success_at,has_gap) VALUES (?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),1) ON CONFLICT(day,aid) DO UPDATE SET last_success_at=excluded.last_success_at,has_gap=1";
const SQL_PUSH='INSERT INTO ptt_pushes (push_id,aid,day,source_line,kind,author,content,occurred_at,floor,source_url,source_priority,source_record_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(push_id) DO UPDATE SET floor=COALESCE(excluded.floor,ptt_pushes.floor),kind=COALESCE(excluded.kind,ptt_pushes.kind),source_priority=MAX(ptt_pushes.source_priority,excluded.source_priority) WHERE (ptt_pushes.floor IS NULL AND excluded.floor IS NOT NULL) OR (ptt_pushes.kind IS NULL AND excluded.kind IS NOT NULL) OR ptt_pushes.source_priority<excluded.source_priority';
const SQL_EVIDENCE='INSERT INTO ptt_source_evidence(day,aid,source_record_key,push_id,source_line) VALUES(?,?,?,?,?) ON CONFLICT(day,aid,source_record_key) DO UPDATE SET push_id=excluded.push_id,source_line=excluded.source_line WHERE ptt_source_evidence.push_id<>excluded.push_id OR ptt_source_evidence.source_line<>excluded.source_line';
const DAY=/^\d{4}-\d{2}-\d{2}$/;
const PUSH=/^ptt:v1:[0-9a-f]{64}$/;
const AID=/^[A-Za-z0-9._-]{1,32}$/;
const UTC=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const PTT_ALPHABET='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_';
function aidMatchesUrl(aid,url) {
  const m=/^https:\/\/www\.ptt\.cc\/bbs\/C_Chat\/M\.(\d{9,10})\.A\.([0-9A-Fa-f]{3})\.html$/.exec(url);
  if(!m || typeof aid!=='string')return false;
  const epoch=Number(m[1]);
  if(!Number.isSafeInteger(epoch) || epoch<=0 || epoch>=2**31)return false;
  const packed=(BigInt(epoch)<<12n)|BigInt(parseInt(m[2],16));
  let computed='';
  for(let position=7;position>=0;position--)
    computed+=PTT_ALPHABET[Number((packed>>BigInt(position*6))&63n)];
  return aid.replace(/^#/,'')===computed;
}
const URL=/^https:\/\/www\.ptt\.cc\/bbs\/C_Chat\/M\.\d+\.A\.[0-9a-fA-F]{3}\.html$/;

export async function applyAuthorizedPttBatch({DB,batch,verifyAuthority,limits={}}) {
  const rowCap=boundedCap(limits.rows,5,LIMIT);
  const writeCap=boundedCap(limits.writes,20,80);
  const queryCap=boundedCap(limits.queries,30,150);
  requireTrue(rowCap!==null&&writeCap!==null&&queryCap!==null,'invalid bounded Publisher configuration');
  requireTrue(DB && typeof DB.prepare==='function' && typeof DB.batch==='function','existing D1 binding required');
  requireTrue(typeof verifyAuthority==='function','trusted independent verifier required');
  requireTrue(batch && Array.isArray(batch.rows) && batch.rows.length>0 && batch.rows.length<=rowCap,'bounded push cap exceeded');
  requireTrue(batch.request_cap===1 && batch.retry_cap===0,'unsafe request budget');
  requireTrue(typeof batch.source_identity==='string' && batch.source_identity.length>0 &&
    Number.isInteger(batch.write_cap) && batch.write_cap>=batch.rows.length && batch.write_cap<=rowCap && typeof batch.digest==='string' &&
    /^[0-9a-f]{64}$/.test(batch.digest), 'batch identity required');
  const digest=await batchDigest(batch);
  requireTrue(digest===batch.digest && batch.batch_id==='ptt48:'+digest.slice(0,24),
    'batch checksum mismatch');
  requireTrue(typeof batch.day==='string' && DAY.test(batch.day) &&
    !Number.isNaN(Date.parse(batch.day+'T00:00:00Z')) &&
    new Date(batch.day+'T00:00:00Z').toISOString().slice(0,10)===batch.day,'invalid day');
  const keys=new Set();
  for(const row of batch.rows) {
    requireTrue(row && PUSH.test(row.push_id) && AID.test(row.aid) && URL.test(row.source_url) &&
      row.day===batch.day && aidMatchesUrl(row.aid,row.source_url) && Number.isSafeInteger(row.source_line) && row.source_line>0 &&
      typeof row.author==='string' && typeof row.content==='string' &&
      typeof row.source_record_key==='string' && row.source_record_key.length>0 &&
      typeof row.occurred_at==='string' && UTC.test(row.occurred_at) &&
      !Number.isNaN(Date.parse(row.occurred_at)) &&
      new Date(Date.parse(row.occurred_at)+8*3600000).toISOString().slice(0,10)===row.day,
      'invalid canonical row');
    const key=row.aid+':'+row.source_record_key;
    requireTrue(!keys.has(key),'duplicate source identity'); keys.add(key);
    requireTrue(await verifyAuthority(row)===true,'unverified source event timestamp');
  }
  for(const row of batch.rows) {
    const existing=await DB.prepare('SELECT push_id FROM ptt_source_evidence WHERE day=? AND aid=? AND source_record_key=?')
      .bind(row.day,row.aid,row.source_record_key).first();
    requireTrue(!existing || existing.push_id===row.push_id,'existing source evidence conflict');
  }
  // Idempotent re-observation must not create account-level D1 writes. The
  // conflict preflight above still rejects source-identity disagreement before
  // mutation; SQL conflict clauses below update only genuine enrichment.
    const aids=[...new Set(batch.rows.map(row=>row.aid))].sort();
  const statements=aids.map(aid=>DB.prepare(SQL_THREAD).bind(batch.day,aid,
    batch.rows.find(row=>row.aid===aid).source_url));
  for(const row of batch.rows) {
    statements.push(DB.prepare(SQL_PUSH).bind(row.push_id,row.aid,row.day,row.source_line,row.kind??null,
      row.author,row.content,row.occurred_at,row.floor??null,row.source_url,10,row.source_record_key));
    statements.push(DB.prepare(SQL_EVIDENCE).bind(row.day,row.aid,row.source_record_key,row.push_id,row.source_line));
  }
  // A bounded write acknowledges observation, never full historical coverage.
  // Until a separately verified gap repair, Public completeness stays partial.
  for(const aid of aids)statements.push(DB.prepare(SQL_STATE).bind(batch.day,aid));
  const queries=statements.length+3*batch.rows.length;
  // Conservative pre-dispatch upper bound for this single-writer transaction:
  // at most one thread insert per AID plus one push and evidence mutation per
  // logical row. Must not rely only on post-commit meta.changes.
  const possibleWrites=2*aids.length+2*batch.rows.length;
  requireTrue(possibleWrites<=writeCap,'potential D1 write budget exceeded before dispatch');
  requireTrue(queries<=queryCap,'query budget exceeded');
  const results=await DB.batch(statements);
  requireTrue(Array.isArray(results) && results.length===statements.length,'D1 transaction failure');
  // A successful transaction response is not sufficient proof of canonical
  // visibility. Perform two exact readbacks per pushed source before ACK.
  for(const row of batch.rows){
    const push=await DB.prepare('SELECT aid,day,source_line,author,content,occurred_at,source_url FROM ptt_pushes WHERE push_id=?')
      .bind(row.push_id).first();
    const evidence=await DB.prepare('SELECT push_id,source_line FROM ptt_source_evidence WHERE day=? AND aid=? AND source_record_key=?')
      .bind(row.day,row.aid,row.source_record_key).first();
    requireTrue(push && evidence && push.aid===row.aid && push.day===row.day &&
      push.source_line===row.source_line && push.author===row.author &&
      push.content===row.content && push.occurred_at===row.occurred_at &&
      push.source_url===row.source_url && evidence.push_id===row.push_id &&
      evidence.source_line===row.source_line,
      'D1 canonical readback mismatch; remote state uncertain, do not retry');
  }
  const affected=results.reduce((sum,result)=>sum+(result?.meta?.changes??0),0);
  requireTrue(Number.isInteger(affected) && affected>=0 && affected<=writeCap,'affected-row budget exceeded');
  // meta.changes is not an authoritative account-level D1 Rows Written receipt.
  // Separate Cloudflare analytics evidence is required before live canary.
  return {status:'ACK',batch_id:batch.batch_id,digest:batch.digest,
    logical_rows_acked:batch.rows.length, d1_rows_written:affected,
    d1_query_count:queries,http_requests:1};
}
