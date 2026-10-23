import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyLiveProjection,
  collabSignature,
  handleCollabPrivatePost,
  mountCanonicalCollabPublisherOnCombinedApi,
} from './collab-private-post.mjs';

const SECRET='s'.repeat(32);
const NOW=1792754400000; // deterministic fixture clock
const enc=new TextEncoder();

function canonical(value){
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(value&&typeof value==='object')
  return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value);
}
async function digest(text){
 const bytes=await crypto.subtle.digest('SHA-256',enc.encode(text));
 return [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
async function artifact(){
 const events=[{
  event_id:'holoserver-hide-and-seek:fixture',
  event_key:'holoserver-hide-and-seek',
  label:'#ホロ鯖かくれんぼ',
  confidence:'explicit-event',
  event_date:'2026-10-23',
  start_at:'2026-10-23T10:00:00+00:00',
  end_at:'2026-10-23T12:00:00+00:00',
  review_status:'candidate',
  live_scope:true,
  payload:{
   event_id:'holoserver-hide-and-seek:fixture',
   event_key:'holoserver-hide-and-seek',
   label:'#ホロ鯖かくれんぼ',
   confidence:'explicit-event',
   event_date:'2026-10-23',
   event_start_at:'2026-10-23T10:00:00+00:00',
   event_end_at:'2026-10-23T12:00:00+00:00',
   participant_count:2,
   pov_count:2,
   detection_version:'collab-event-v2',
   streams:[
    {video_id:'hide1111111',channel_id:'UC_A',title:'A'},
    {video_id:'hide2222222',channel_id:'UC_B',title:'B'}
   ]
  }
 }];
 const source={
  store_schema:'collab-event-store-v2',
  detection_version:'collab-event-v2',
  materialization_run_id:1,
  materialized_at:'2026-10-23T10:05:00+00:00',
  range_start:'2026-10-22T16:00:00+00:00',
  range_end:'2026-10-30T16:00:00+00:00'
 };
 const basis={
  projection_key:'live',
  range_start:source.range_start,
  range_end:source.range_end,
  detection_version:source.detection_version,
  events
 };
 return {
  schema_version:'public-collab-projection-v1',
  projection_key:'live',
  source_revision:'sha256:'+await digest(canonical(basis)),
  generated_at:'2026-10-23T10:05:00+00:00',
  source_event_count:1,
  effective_event_count:1,
  source,
  events
 };
}
function fakeDb(expectedRevision,expectedLive=1,{alreadyCurrent=false}={}){
 const batched=[];
 let applied=alreadyCurrent;
 return {
  batched,
  prepare(sql){
   const statement={
    sql,
    bind(...args){
     return {
      async first(){
       if(sql.includes('public_collab_projection_meta'))
        return applied
          ? {source_revision:expectedRevision,effective_event_count:1}
          : null;
       throw Error('unexpected bound first');
      }
     };
    },
    async first(){
     if(sql.includes('COUNT(*) AS n FROM public_collab_events'))
      return {n:expectedLive};
     throw Error('unexpected first');
    }
   };
   return statement;
  },
  async batch(statements){
   batched.push(...statements);
   applied=true;
   return statements.map(()=>({success:true,meta:{changes:1}}));
  }
 };
}
async function signedRequest(doc,{timestamp=String(NOW),secret=SECRET}={}){
 const raw=JSON.stringify(doc);
 const mac=await collabSignature(secret,timestamp,raw);
 return new Request('https://api.example/internal/collab/live',{
  method:'POST',
  headers:{
   'content-type':'application/json',
   'x-collab-timestamp':timestamp,
   'x-collab-signature':mac
  },
  body:raw
 });
}

test('complete live projection applies one bounded D1 batch and verifies readback',async()=>{
 const doc=await artifact();
 const DB=fakeDb(doc.source_revision);
 const receipt=await applyLiveProjection(DB,doc);
 assert.equal(receipt.status,'verified');
 assert.equal(receipt.effective_event_count,1);
 assert.equal(receipt.live_event_count,1);
 assert.equal(DB.batched.length,3); // clear + one event + meta
 assert.match(DB.batched[0].sql,/SET live_scope=0/);
 assert.match(DB.batched[1].sql,/holoserver-hide-and-seek/);
 assert.match(DB.batched[2].sql,/public_collab_projection_meta/);
});

test('unchanged source revision performs no D1 write batch',async()=>{
 const doc=await artifact();
 const DB=fakeDb(doc.source_revision,1,{alreadyCurrent:true});
 const receipt=await applyLiveProjection(DB,doc);
 assert.equal(receipt.status,'unchanged');
 assert.equal(receipt.d1_batch_statements,0);
 assert.equal(DB.batched.length,0);
});

test('private endpoint requires explicit enablement and a valid signature',async()=>{
 const doc=await artifact();
 const disabled=await handleCollabPrivatePost(
  await signedRequest(doc),
  {DB:fakeDb(doc.source_revision),COLLAB_PUBLISH_HMAC_SECRET:SECRET},
  {now:NOW}
 );
 assert.equal(disabled.status,503);

 const bad=await signedRequest(doc,{secret:'x'.repeat(32)});
 const denied=await handleCollabPrivatePost(
  bad,
  {DB:fakeDb(doc.source_revision),COLLAB_PUBLISH_ENABLED:'true',COLLAB_PUBLISH_HMAC_SECRET:SECRET},
  {now:NOW}
 );
 assert.equal(denied.status,401);
});

test('private endpoint accepts exact signed canonical v2 live projection',async()=>{
 const doc=await artifact();
 const DB=fakeDb(doc.source_revision);
 const response=await handleCollabPrivatePost(
  await signedRequest(doc),
  {DB,COLLAB_PUBLISH_ENABLED:'true',COLLAB_PUBLISH_HMAC_SECRET:SECRET},
  {now:NOW}
 );
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.status,'verified');
 assert.equal(body.source_revision,doc.source_revision);
});

test('projection tamper fails closed before D1 batch',async()=>{
 const doc=await artifact();
 doc.events[0].label='tampered';
 const DB=fakeDb(doc.source_revision);
 const response=await handleCollabPrivatePost(
  await signedRequest(doc),
  {DB,COLLAB_PUBLISH_ENABLED:'true',COLLAB_PUBLISH_HMAC_SECRET:SECRET},
  {now:NOW}
 );
 assert.equal(response.status,409);
 assert.equal(DB.batched.length,0);
});

test('mount preserves every unrelated existing API route',async()=>{
 const base={fetch:async()=>new Response('base',{status:218})};
 const mounted=mountCanonicalCollabPublisherOnCombinedApi(base);
 const response=await mounted.fetch(
  new Request('https://api.example/health'),
  {},
  {}
 );
 assert.equal(response.status,218);
 assert.equal(await response.text(),'base');
});
