/** Private signed canonical Collab live publication.
 *
 * This is a runtime publication boundary, not a detector. The accepted producer
 * sends a complete public-collab-projection-v1 live projection. The Worker only
 * validates identity/integrity and atomically applies it to the existing D1
 * canonical Collab tables consumed by PR #197.
 */
const enc=new TextEncoder();
const EVENT_ID=/^[A-Za-z0-9:_-]{1,160}$/;
const VIDEO_ID=/^[A-Za-z0-9_-]{11}$/;
const REVISION=/^sha256:[0-9a-f]{64}$/;
const PUBLISHABLE=new Set(['candidate','approved','needs_review']);
const MAX_EVENTS=100;
const MAX_BODY_BYTES=512*1024;

function reply(body,status){
 return new Response(JSON.stringify(body),{
  status,
  headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}
 });
}
function hex(bytes){
 return Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
}
function canonical(value){
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object'){
  return '{'+Object.keys(value).sort().map(
   key=>JSON.stringify(key)+':'+canonical(value[key])
  ).join(',')+'}';
 }
 return JSON.stringify(value);
}
async function sha256Hex(text){
 return hex(await crypto.subtle.digest('SHA-256',enc.encode(text)));
}
export async function collabSignature(secret,timestamp,body){
 const key=await crypto.subtle.importKey(
  'raw',enc.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']
 );
 return hex(await crypto.subtle.sign('HMAC',key,enc.encode(timestamp+'.'+body)));
}
function equal(a,b){
 if(!/^[a-f0-9]{64}$/.test(a)||b.length!==64)return false;
 let diff=0;
 for(let i=0;i<64;i++)diff|=a.charCodeAt(i)^b.charCodeAt(i);
 return diff===0;
}
function iso(value,label){
 if(typeof value!=='string'||!value||Number.isNaN(Date.parse(value)))
  throw Error('invalid '+label);
 return value;
}
function validateEvent(row){
 if(!row||typeof row!=='object'||!EVENT_ID.test(row.event_id??''))
  throw Error('invalid event_id');
 if(typeof row.event_key!=='string'||!row.event_key)
  throw Error('invalid event_key');
 if(typeof row.label!=='string'||typeof row.confidence!=='string')
  throw Error('invalid event metadata');
 if(!/^\d{4}-\d{2}-\d{2}$/.test(row.event_date??''))
  throw Error('invalid event_date');
 iso(row.start_at,'start_at'); iso(row.end_at,'end_at');
 if(!PUBLISHABLE.has(row.review_status))
  throw Error('invalid review_status');
 if(typeof row.live_scope!=='boolean')
  throw Error('invalid live_scope');
 const payload=row.payload;
 if(!payload||typeof payload!=='object'||payload.event_id!==row.event_id||
    payload.event_key!==row.event_key||payload.label!==row.label||
    payload.confidence!==row.confidence||payload.event_date!==row.event_date||
    payload.event_start_at!==row.start_at||payload.event_end_at!==row.end_at)
  throw Error('payload identity mismatch');
 if(!Array.isArray(payload.streams)||payload.streams.length<2)
  throw Error('published event requires >=2 POVs');
 const videos=new Set();
 for(const stream of payload.streams){
  if(!stream||typeof stream!=='object'||!VIDEO_ID.test(stream.video_id??''))
   throw Error('invalid video_id');
  if(videos.has(stream.video_id))throw Error('duplicate video_id');
  videos.add(stream.video_id);
 }
 return row;
}
export async function validateLiveProjection(doc){
 if(!doc||doc.schema_version!=='public-collab-projection-v1'||doc.projection_key!=='live')
  throw Error('unsupported projection');
 if(!REVISION.test(doc.source_revision??''))throw Error('invalid source_revision');
 const generated=iso(doc.generated_at,'generated_at');
 const source=doc.source;
 if(!source||typeof source!=='object'||source.detection_version!=='collab-event-v2')
  throw Error('invalid source');
 const rangeStart=iso(source.range_start,'range_start');
 const rangeEnd=iso(source.range_end,'range_end');
 const span=Date.parse(rangeEnd)-Date.parse(rangeStart);
 if(!(span>0&&span<=31*86400000))throw Error('invalid source range');
 if(!Array.isArray(doc.events)||doc.events.length>MAX_EVENTS)
  throw Error('invalid event list');
 const ids=new Set();
 const events=doc.events.map(row=>{
  validateEvent(row);
  if(ids.has(row.event_id))throw Error('duplicate event_id');
  ids.add(row.event_id);
  return row;
 });
 if(!Number.isInteger(doc.source_event_count)||!Number.isInteger(doc.effective_event_count)||
    doc.effective_event_count!==events.length||
    doc.source_event_count<doc.effective_event_count)
  throw Error('event count mismatch');
 const basis={
  projection_key:'live',
  range_start:rangeStart,
  range_end:rangeEnd,
  detection_version:source.detection_version,
  events
 };
 const expected='sha256:'+await sha256Hex(canonical(basis));
 if(expected!==doc.source_revision)throw Error('source_revision mismatch');
 return {events,generated,rangeStart,rangeEnd};
}
function q(value){
 return value===null?'NULL':"'" + String(value).replaceAll("'","''") + "'";
}
async function readLiveMembership(DB){
 const result=await DB.prepare(
  'SELECT event_id,source_revision FROM public_collab_events WHERE is_current=1 AND live_scope=1 ORDER BY event_id'
 ).all();
 if(!Array.isArray(result?.results))
  throw Error('live membership readback unavailable; do not retry');
 const rows=result.results;
 return rows.map(row=>({event_id:String(row?.event_id??''),source_revision:String(row?.source_revision??'')}));
}
function verifyLiveMembership(rows,events,revision){
 const expected=events.filter(row=>row.live_scope).map(row=>row.event_id).sort();
 const actual=rows.map(row=>row.event_id).sort();
 if(actual.length!==expected.length||actual.some((eventId,index)=>eventId!==expected[index]))
  throw Error('live membership readback mismatch; do not retry');
 if(rows.some(row=>row.source_revision!==revision))
  throw Error('live source revision readback mismatch; do not retry');
 return expected.length;
}
function upsertSql(row,revision,published){
 const payload=canonical(row.payload);
 return `INSERT INTO public_collab_events(
event_id,event_key,label,confidence,event_date,start_at,end_at,review_status,
payload_json,live_scope,is_current,source_revision,published_at
) VALUES(${[
  row.event_id,row.event_key,row.label,row.confidence,row.event_date,
  row.start_at,row.end_at,row.review_status,payload
 ].map(q).join(',')},${row.live_scope?1:0},1,${q(revision)},${q(published)})
ON CONFLICT(event_id) DO UPDATE SET
event_key=excluded.event_key,label=excluded.label,confidence=excluded.confidence,
event_date=excluded.event_date,start_at=excluded.start_at,end_at=excluded.end_at,
review_status=excluded.review_status,payload_json=excluded.payload_json,
live_scope=excluded.live_scope,is_current=1,source_revision=excluded.source_revision,
published_at=excluded.published_at`;
}
export async function applyLiveProjection(DB,doc){
 if(!DB||typeof DB.prepare!=='function'||typeof DB.batch!=='function')
  throw Error('existing D1 binding required');
 const valid=await validateLiveProjection(doc);
 const previous=await DB.prepare(
  'SELECT source_revision,effective_event_count FROM public_collab_projection_meta WHERE projection_key=?'
 ).bind('live').first();
 if(previous?.source_revision===doc.source_revision){
  if(Number(previous.effective_event_count)!==doc.effective_event_count)
   throw Error('projection meta readback mismatch; do not retry');
  const liveRows=await readLiveMembership(DB);
  const liveEventCount=verifyLiveMembership(liveRows,valid.events,doc.source_revision);
  return {
   status:'unchanged',
   projection_key:'live',
   source_revision:doc.source_revision,
   effective_event_count:doc.effective_event_count,
   live_event_count:liveEventCount,
   d1_batch_statements:0
  };
 }
 const statements=[
  DB.prepare('UPDATE public_collab_events SET live_scope=0 WHERE is_current=1 AND live_scope=1')
 ];
 for(const row of valid.events)
  statements.push(DB.prepare(upsertSql(row,doc.source_revision,valid.generated)));
 statements.push(DB.prepare(
  `INSERT INTO public_collab_projection_meta(
projection_key,source_revision,published_at,range_start,range_end,source_event_count,effective_event_count
) VALUES(${q('live')},${q(doc.source_revision)},${q(valid.generated)},${q(valid.rangeStart)},${q(valid.rangeEnd)},${doc.source_event_count},${doc.effective_event_count})
ON CONFLICT(projection_key) DO UPDATE SET
source_revision=excluded.source_revision,published_at=excluded.published_at,
range_start=excluded.range_start,range_end=excluded.range_end,
source_event_count=excluded.source_event_count,effective_event_count=excluded.effective_event_count`
 ));
 const results=await DB.batch(statements);
 if(!Array.isArray(results)||results.length!==statements.length)
  throw Error('D1 batch failure; remote state uncertain, do not retry');
 const meta=await DB.prepare(
  'SELECT source_revision,effective_event_count FROM public_collab_projection_meta WHERE projection_key=?'
 ).bind('live').first();
 if(!meta||meta.source_revision!==doc.source_revision||
    Number(meta.effective_event_count)!==doc.effective_event_count)
  throw Error('projection meta readback mismatch; do not retry');
 const liveRows=await readLiveMembership(DB);
 const expectedLive=verifyLiveMembership(liveRows,valid.events,doc.source_revision);
 return {
  status:'verified',
  projection_key:'live',
  source_revision:doc.source_revision,
  effective_event_count:doc.effective_event_count,
  live_event_count:expectedLive,
  d1_batch_statements:statements.length
 };
}
export async function handleCollabPrivatePost(request,env,{now=Date.now()}={}){
 if(new URL(request.url).pathname!=='/internal/collab/live')
  return reply({error:'not_found'},404);
 if(request.method!=='POST')return reply({error:'method_not_allowed'},405);
 const secret=env?.COLLAB_PUBLISH_HMAC_SECRET;
 if(env?.COLLAB_PUBLISH_ENABLED!=='true'||typeof secret!=='string'||secret.length<32||!env?.DB)
  return reply({error:'publisher_disabled'},503);
 const timestamp=request.headers.get('x-collab-timestamp')??'';
 const mac=request.headers.get('x-collab-signature')??'';
 if(!/^\d{13}$/.test(timestamp)||Math.abs(now-Number(timestamp))>120000)
  return reply({error:'invalid_timestamp'},401);
 const raw=await request.text();
 if(enc.encode(raw).length>MAX_BODY_BYTES)return reply({error:'payload_too_large'},413);
 const expected=await collabSignature(secret,timestamp,raw);
 if(!equal(mac,expected))return reply({error:'bad_signature'},401);
 let data;
 try{data=JSON.parse(raw)}catch{return reply({error:'invalid_json'},400)}
 try{
  const outcome=await applyLiveProjection(env.DB,data);
  return reply(outcome,200);
 }catch(error){
  return reply({
   error:'collab_publish_failed_stop_no_auto_retry',
   detail:String(error.message).slice(0,180)
  },409);
 }
}
export function mountCanonicalCollabPublisherOnCombinedApi(combinedApi){
 if(!combinedApi||typeof combinedApi.fetch!=='function')
  throw Error('combined existing API Worker required');
 return {async fetch(request,env,context){
  const path=new URL(request.url).pathname;
  if(path==='/internal/collab/live')return handleCollabPrivatePost(request,env);
  return combinedApi.fetch(request,env,context);
 }};
}
