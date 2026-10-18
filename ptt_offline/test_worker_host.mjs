import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import worker from './worker_host/index.mjs';
import {canonicalTimeMessage,verifyPublisherTimeProof} from './worker_host/time_authority.mjs';
const secret='time-proof-owner-key-at-least-32-bytes';
async function sign(row) {
 const key=await webcrypto.subtle.importKey('raw',new TextEncoder().encode(secret),
  {name:'HMAC',hash:'SHA-256'},false,['sign']);
 return Buffer.from(await webcrypto.subtle.sign('HMAC',key,
  new TextEncoder().encode(canonicalTimeMessage(row)))).toString('hex');
}
test('actual bundled existing-worker entry preserves health with binding',async()=>{
 const r=await worker.fetch(new Request('https://api.example/health'),{DB:{}});
 assert.equal(r.status,200);
 assert.equal((await r.json()).service,'holoviewer-public-read');
});
test('actual production entry mounts WebSub callback before the base 404 router',async()=>{
 const DB={prepare(){return {
  bind(){return this},
  first:async()=>({roster_version:'today-roster-v85',expected_channels:85})
 }}};
 const r=await worker.fetch(new Request('https://api.example/internal/today/websub'),{
  DB,
  TODAY_WEBSUB_RECEIVER_ENABLED:'true',
  TODAY_WEBSUB_CALLBACK_URL:'https://api.example/internal/today/websub',
  TODAY_WEBSUB_SECRET:'local-fixture-secret-0123456789abcdef'
 });
 assert.equal(r.status,403);
 assert.deepEqual(await r.json(),{error:'challenge_rejected'});
});
test('existing-worker entry blocks private POST until explicitly enabled',async()=>{
 const r=await worker.fetch(new Request('https://api.example/private/ptt/publish',
  {method:'POST',body:'{}'}),{DB:{}});
 assert.equal(r.status,503);
});
test('reviewed exact event time HMAC passes and tampering fails',async()=>{
 const row={aid:'1gepPtNy',source_line:1,source_record_key:'1gepPtNy:1',
  push_id:'ptt:v1:'+'a'.repeat(64),occurred_at:'2026-10-15T10:00:00Z',
  source_url:'https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html'};
 const signed={...row,time_proof:await sign(row)};
 assert.equal(await verifyPublisherTimeProof(signed,{PTT_TIME_AUTHORITY_SECRET:secret}),true);
 assert.equal(await verifyPublisherTimeProof({...signed,occurred_at:'2026-10-15T11:00:00Z'},
  {PTT_TIME_AUTHORITY_SECRET:secret}),false);
 assert.equal(await verifyPublisherTimeProof(signed,{}),false);
});

test('combined host serves both independent owner POST paths without enabling writes',async()=>{
 const today=await worker.fetch(new Request('https://api.example/internal/today/one-shot',
   {method:'POST',body:'{}'}),{DB:{}});
 assert.equal(today.status,503);
 assert.equal((await today.json()).error,'publisher_disabled');
 const ptt=await worker.fetch(new Request('https://api.example/private/ptt/publish',
   {method:'POST',body:'{}'}),{DB:{}});
 assert.equal(ptt.status,503);
 const legacy=await worker.fetch(new Request('https://api.example/health'),{DB:{}});
 assert.equal(legacy.status,200);
});

test('legacy CORS stays deny-by-default when ALLOWED_ORIGIN is absent',async()=>{
 const untagged=await worker.fetch(new Request('https://api.example/health',{headers:{origin:'https://untrusted.example'}}),{DB:{}});
 assert.equal(untagged.status,403);
 assert.equal(untagged.headers.get('access-control-allow-origin'),null);
 const noOrigin=await worker.fetch(new Request('https://api.example/health'),{DB:{}});
 assert.equal(noOrigin.status,200);
});
test('legacy CORS recognizes exact configured origin only',async()=>{
 const good=await worker.fetch(new Request('https://api.example/health',{headers:{origin:'https://viewer.example'}}),{DB:{},ALLOWED_ORIGIN:'https://viewer.example'});
 assert.equal(good.status,200);
 assert.equal(good.headers.get('access-control-allow-origin'),'https://viewer.example');
 const bad=await worker.fetch(new Request('https://api.example/health',{headers:{origin:'https://other.example'}}),{DB:{},ALLOWED_ORIGIN:'https://viewer.example'});
 assert.equal(bad.status,403);
 assert.equal(bad.headers.get('access-control-allow-origin'),null);
});

test('combined host serves #47 Today consumer envelope directly to 4174 preload',async()=>{
 const coverage={roster_version:'v85',last_success_at:'2026-10-15T20:20:00Z',expected_channels:85,scanned_channels:85,gap:0,checkpoint:'cp_fixture1234'};
 const row={video_id:'abcdefghijk',publisher_channel_id:'UC'+'A'.repeat(22),roster_version:'v85',
  channel_group:'hololive',title:'Fixture LIVE',channel_name:'Fixture Channel',lifecycle_state:'live',
  lifecycle_observed_at:'2026-10-15T20:20:00Z',checked_at:'2026-10-15T20:20:00Z',
  scheduled_start:'2026-10-15T20:00:00Z',actual_start:'2026-10-15T20:01:00Z',actual_end:null,
  source_label:'YouTube liveStreamingDetails',source_checksum:'deadbeef',trusted_channel_avatar:null};
 const DB={prepare(sql){return {bind(){return this},first:async()=>sql.includes('public_today_catalog_meta')?coverage:null,
   all:async()=>({results:sql.includes('FROM public_today_canonical')?[row]:[]})}}};
 const r=await worker.fetch(new Request('https://api.example/v1/catalog/today?day=2026-10-16'),{DB});
 assert.equal(r.status,200);
 const body=await r.json();
 assert.equal(body.schema_version,'public-consumer-v1');
 assert.equal(body.streams.length,1);
 assert.deepEqual(Object.keys(body.streams[0]).sort(),[
  'actual_end','actual_start','anchor_source','avatar_url','channel_id','channel_name','group','lifecycle_state','member_accent','member_accent_dual',
  'observed_at','source_label','stale','start_at','support_color_source','support_mode','title','video_id'
 ].sort());
 assert.equal(body.streams[0].video_id,'abcdefghijk');
 assert.equal(body.streams[0].lifecycle_state,'live'); // lifecycle identity is preserved even when freshness is stale
 assert.equal(body.streams[0].stale,true);
 assert.equal(body.streams[0].group,'hololive');
 assert.equal(body.streams[0].source_label,'YouTube liveStreamingDetails');
});

test('combined host accepts chunked support-color payload without changing Today contract',async()=>{
 const coverage={roster_version:'v85',last_success_at:'2026-10-16T04:45:00Z',expected_channels:85,scanned_channels:85,gap:0,checkpoint:'cp_fixture1234'};
 const cid='UC'+'A'.repeat(22);
 const row={video_id:'abcdefghijk',publisher_channel_id:cid,roster_version:'v85',
  channel_group:'hololive',title:'Fixture',channel_name:'Fixture',lifecycle_state:'live',
  lifecycle_observed_at:'2026-10-16T04:45:00Z',checked_at:'2026-10-16T04:45:00Z',
  scheduled_start:'2026-10-16T04:30:00Z',actual_start:'2026-10-16T04:31:00Z',actual_end:null,
  source_label:'YouTube liveStreamingDetails',source_checksum:'deadbeef',trusted_channel_avatar:null};
 const DB={prepare(sql){return {bind(){return this},first:async()=>sql.includes('public_today_catalog_meta')?coverage:null,
   all:async()=>({results:sql.includes('FROM public_today_canonical')?[row]:[]})}}};
 const payload=JSON.stringify({schema_version:1,fallback:'neutral',channels:[{
  channel_id:cid,verification_status:'verified',display_mode:'solid',color_hex:'#123456'
 }]});
 const cut=Math.floor(payload.length/2);
 const env={DB,TODAY_SUPPORT_COLORS_JSON_0:payload.slice(0,cut),TODAY_SUPPORT_COLORS_JSON_1:payload.slice(cut)};
 const r=await worker.fetch(new Request('https://api.example/v1/catalog/today?day=2026-10-16'),env);
 assert.equal(r.status,200);
 const body=await r.json();
 assert.equal(body.streams[0].member_accent,'#123456');
 assert.equal(body.streams[0].support_mode,'solid');
});
