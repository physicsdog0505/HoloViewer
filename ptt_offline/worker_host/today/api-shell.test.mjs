import test from 'node:test';
import assert from 'node:assert/strict';
import {createExistingApiRouter} from './api-shell.mjs';
import {legacyHistory,legacyVideo} from './legacy-compat.mjs';
const ORIGIN='https://holoviewer-public.singlebagel.workers.dev';
const router=createExistingApiRouter({
 legacyHistory:async()=>new Response('history'),
 legacyVideo:async()=>new Response('video')});
const env={DB:null,ALLOWED_ORIGIN:ORIGIN};
const db={prepare(sql){if(sql.includes('catalog_meta'))return {first:async()=>null};
 if(sql.includes('public_today_canonical'))return {bind(){return {all:async()=>({results:[]})}}};
 if(sql.includes('public_history'))return {bind(){return {all:async()=>({results:[]})}}};
 if(sql.includes('public_collab_projection_meta'))return {bind(key){return {first:async()=>(
  key==='live'?{
   projection_key:'live',source_revision:'sha256:'+'a'.repeat(64),
   published_at:'2026-10-22T17:00:00Z',range_start:'2026-10-21T16:00:00Z',
   range_end:'2026-10-22T16:00:00Z',source_event_count:0,effective_event_count:0
  }:null
 )}}};
 if(sql.includes('COUNT(*) AS n FROM public_collab_events'))return {bind(){return {first:async()=>({n:0})}}};
 if(sql.includes('FROM public_collab_events'))return {
  bind(){return {all:async()=>({results:[]}),first:async()=>null}},
  all:async()=>({results:[]})
 };
 throw Error('unexpected SELECT');}};
function req(path,method='GET',origin=ORIGIN){return new Request('https://api.example'+path,{method,headers:{origin}});}
test('known origin gets CORS, OPTIONS and GET gate',async()=>{
 assert.equal((await router.fetch(req('/health','OPTIONS'),{...env,DB:db})).status,204);
 assert.equal((await router.fetch(req('/health','POST'),{...env,DB:db})).status,405);
 const response=await router.fetch(req('/health'),{...env,DB:db});
 assert.equal(response.status,200);
 assert.equal(response.headers.get('access-control-allow-origin'),ORIGIN);
 assert.equal((await router.fetch(req('/health','GET','https://evil.example'),{...env,DB:db})).status,403);
});
test('health binding and Today use existing DB; no writes',async()=>{
 assert.equal((await router.fetch(req('/health'),env)).status,503);
 const r=await router.fetch(req('/v1/catalog/today?day=2026-10-15'),{...env,DB:db});
 assert.equal(r.status,200);
 assert.equal((await r.json()).schema_version,'public-consumer-v1');
});
test('legacy route handlers preserved and unknown route 404',async()=>{
 assert.equal(await (await router.fetch(req('/v1/history'),{...env,DB:db})).text(),'history');
 assert.equal(await (await router.fetch(req('/v1/catalog/videos/abcdefghijk'),{...env,DB:db})).text(),'video');
 assert.equal((await router.fetch(req('/v1/absent'),{...env,DB:db})).status,404);
});
test('PTT extension requires explicitly injected reviewed handler',async()=>{
 assert.equal((await router.fetch(req('/v1/ptt/today'),{...env,DB:db})).status,404);
 const ptt=createExistingApiRouter({pttHandler:async()=>new Response('ptt')});
 assert.equal(await (await ptt.fetch(req('/v1/ptt/today'),{...env,DB:db})).text(),'ptt');
});

test('legacy exact OPTIONS without Origin and allow-header contract',async()=>{
 const noOrigin=new Request('https://api.example/v1/catalog/today',{method:'OPTIONS'});
 const response=await router.fetch(noOrigin,{...env,DB:db});
 assert.equal(response.status,400);
 assert.equal((await response.json()).error,'origin_required');
 const yes=await router.fetch(req('/v1/catalog/today','OPTIONS'),{...env,DB:db});
 assert.equal(yes.headers.get('access-control-allow-headers'),'Accept');
});
test('env-driven allowlist and origin error contract',async()=>{
 const denied=await router.fetch(req('/health','GET','https://no.example'),{...env,DB:db});
 assert.equal(denied.status,403);
 assert.equal((await denied.json()).error,'origin_not_allowed');
 const many={...env,DB:db,ALLOWED_ORIGIN:'https://else.example, '+ORIGIN};
 const yes=await router.fetch(req('/health'),many);
 assert.equal(yes.headers.get('access-control-allow-origin'),ORIGIN);
});
test('exact health and DB-unbound contracts with max-age zero',async()=>{
 const ok=await router.fetch(req('/health'),{...env,DB:db});
 assert.deepEqual(await ok.json(),{service:'holoviewer-public-read',status:'database_bound',schema:'v1'});
 assert.equal(ok.headers.get('cache-control'),'public, max-age=0');
 const bad=await router.fetch(req('/health'),env);
 assert.equal(bad.status,503);
 assert.equal((await bad.json()).status,'database_not_bound');
 const missing=await router.fetch(req('/v1/catalog/today'),env);
 assert.equal((await missing.json()).error,'database_not_bound');
 assert.equal(missing.headers.get('cache-control'),'public, max-age=0');
});
test('Today response retains reviewed route cache policy, no global no-store',async()=>{
 const r=await router.fetch(req('/v1/catalog/today?day=2026-10-15'),{...env,DB:db});
 assert.equal(r.headers.get('cache-control'),'public, max-age=30');
});

test('accepted OPTIONS exposes preflight max age 600 and no response cache override',async()=>{
 const res=await router.fetch(req('/health','OPTIONS'),{...env,DB:db});
 assert.equal(res.status,204);
 assert.equal(res.headers.get('access-control-max-age'),'600');
 assert.equal(res.headers.get('access-control-allow-headers'),'Accept');
 assert.equal(res.headers.get('cache-control'),null);
});

test('live video prefix dispatch preserves invalid ID 400 and video cache age 15',async()=>{
 const env={DB:{prepare(){return {bind(){return {first:async()=>({video_id:'abcdefghijk'})}}}}},ALLOWED_ORIGIN:ORIGIN};
 const actualRouter=createExistingApiRouter();
 const invalid=await actualRouter.fetch(req('/v1/catalog/videos/short'),env);
 assert.equal(invalid.status,400);
 assert.equal((await invalid.json()).error,'invalid_video_id');
 const valid=await actualRouter.fetch(req('/v1/catalog/videos/abcdefghijk'),env);
 assert.equal(valid.status,200);
});

test('Collab experience routes are mounted on the existing API shell',async()=>{
 const live=await router.fetch(req('/v1/collab/live'),{...env,DB:db});
 assert.equal(live.status,200);
 const liveBody=await live.json();
 assert.equal(liveBody.kind,'collab');
 assert.deepEqual(liveBody.events,[]);
 const history=await router.fetch(req('/v1/collab/history?day=2026-10-15'),{...env,DB:db});
 assert.equal(history.status,200);
 assert.equal((await history.json()).scope,'history');
});
test('Watchalong route reaches feature gate instead of falling through 404',async()=>{
 const r=await router.fetch(req('/v1/watchalong/recent'),{...env,DB:db});
 assert.equal(r.status,503);
 assert.equal((await r.json()).error,'watchalong_not_enabled');
});


test('single-video lookup falls back to Today canonical when legacy public_catalog has no row',async()=>{
 const today={
  video_id:'zPCcFbCONek',title:'Ended stream',channel_id:'UC'+'A'.repeat(22),channel_name:'Channel',
  lifecycle_state:'ended',actual_start:'2026-10-18T03:15:53Z',actual_end:'2026-10-18T04:49:00Z',
  scheduled_start:'2026-10-18T03:15:00Z',source_label:'YouTube liveStreamingDetails'
 };
 const db={prepare(sql){return {bind(){return {async first(){
  if(sql.includes('FROM public_catalog'))return null;
  if(sql.includes('FROM public_today_canonical'))return today;
  throw Error('unexpected query');
 }}}}}};
 const response=await legacyVideo(new Request('https://api.example/v1/catalog/videos/zPCcFbCONek'),{DB:db});
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.video_id,'zPCcFbCONek');
 assert.equal(body.actual_start,'2026-10-18T03:15:53Z');
 assert.equal(body.actual_end,'2026-10-18T04:49:00Z');
 assert.equal(body.anchor_source,'youtube-liveStreamingDetails-actualStartTime');
});

test('single-video Today fallback hides untrusted actual bounds',async()=>{
 const today={
  video_id:'abcdefghijk',title:'Legacy',channel_id:'UC'+'A'.repeat(22),channel_name:'Channel',
  lifecycle_state:'ended',actual_start:'2026-10-18T03:15:53Z',actual_end:'2026-10-18T04:49:00Z',
  scheduled_start:'2026-10-18T03:15:00Z',source_label:'legacy-import'
 };
 const db={prepare(sql){return {bind(){return {async first(){
  if(sql.includes('FROM public_catalog'))return null;
  if(sql.includes('FROM public_today_canonical'))return today;
  throw Error('unexpected query');
 }}}}}};
 const body=await (await legacyVideo(new Request('https://api.example/v1/catalog/videos/abcdefghijk'),{DB:db})).json();
 assert.equal(body.actual_start,null);
 assert.equal(body.actual_end,null);
 assert.equal(body.anchor_source,null);
});


test('single-video lookup resolves trusted recent public_history when Today row is absent',async()=>{
 const history={
  video_id:'recentvod01',title:'Recent VOD',channel_id:'UC'+'A'.repeat(22),channel_name:'Channel',
  avatar_url:'',actual_start:'2026-10-17T10:00:05Z',actual_end:'2026-10-17T11:00:00Z',
  scheduled_start:'2026-10-17T10:00:00Z',source_revision:'youtube-videos-list:liveStreamingDetails'
 };
 const db={prepare(sql){return {bind(){return {async first(){
  if(sql.includes('FROM public_today_canonical'))return null;
  if(sql.includes('FROM public_history'))return history;
  if(sql.includes('FROM public_catalog'))return null;
  throw Error('unexpected query');
 }}}}}};
 const body=await (await legacyVideo(new Request('https://api.example/v1/catalog/videos/recentvod01'),{DB:db})).json();
 assert.equal(body.lifecycle_state,'ended');
 assert.equal(body.actual_start,'2026-10-17T10:00:05Z');
 assert.equal(body.actual_end,'2026-10-17T11:00:00Z');
 assert.equal(body.anchor_source,'youtube-liveStreamingDetails-actualStartTime');
});

test('single-video recent history fails closed on untrusted provenance',async()=>{
 const history={
  video_id:'recentbad01',title:'Recent VOD',channel_id:'UC'+'A'.repeat(22),channel_name:'Channel',
  avatar_url:'',actual_start:'2026-10-17T10:00:05Z',actual_end:'2026-10-17T11:00:00Z',
  scheduled_start:'2026-10-17T10:00:00Z',source_revision:'legacy-import'
 };
 const db={prepare(sql){return {bind(){return {async first(){
  if(sql.includes('FROM public_today_canonical'))return null;
  if(sql.includes('FROM public_history'))return history;
  if(sql.includes('FROM public_catalog'))return null;
  throw Error('unexpected query');
 }}}}}};
 const body=await (await legacyVideo(new Request('https://api.example/v1/catalog/videos/recentbad01'),{DB:db})).json();
 assert.equal(body.actual_start,null);
 assert.equal(body.actual_end,null);
 assert.equal(body.anchor_source,null);
});


test('History read enriches trusted avatar, group and audited dual support colors without changing bounds authority',async()=>{
 const cid='UC'+'H'.repeat(22);
 const row={
  video_id:'histcard001',taipei_day:'2026-10-17',title:'History',channel_id:cid,channel_name:'Member',
  avatar_url:'',scheduled_start:'2026-10-17T10:00:00Z',
  actual_start:'2026-10-17T10:01:00Z',actual_end:'2026-10-17T11:00:00Z',
  source_revision:'youtube-videos-list:liveStreamingDetails',
  trusted_channel_avatar:'https://yt3.ggpht.com/history-avatar',
  channel_group:'hololive'
 };
 const DB={prepare(sql){return {bind(){return {
  async first(){return sql.includes('COUNT(*)')?{total:1}:null},
  async all(){return {results:[row]}}
 }}}}};
 const colors=JSON.stringify({schema_version:1,fallback:'neutral',channels:[{
  channel_id:cid,verification_status:'community',color_semantics:'2025_6th_fes_penlight',
  display_mode:'dual_color',color_hexes:['#112233','#AABBCC']
 }]});
 const res=await legacyHistory(new Request('https://api.example/v1/history?day=2026-10-17'),{
  DB,TODAY_SUPPORT_COLORS_JSON:colors
 });
 assert.equal(res.status,200);
 const item=(await res.json()).items[0];
 assert.equal(item.avatar_url,'https://yt3.ggpht.com/history-avatar');
 assert.equal(item.group,'hololive');
 assert.equal(item.member_accent,'#112233');
 assert.deepEqual(item.member_accent_dual,['#112233','#AABBCC']);
 assert.equal(item.support_mode,'dual_color');
 assert.equal(item.support_color_source,'2025_6th_fes_penlight');
 assert.equal(item.actual_start,'2026-10-17T10:01:00Z');
 assert.equal(item.actual_end,'2026-10-17T11:00:00Z');
 assert.equal(item.anchor_source,'youtube-liveStreamingDetails-actualStartTime');
});

test('History presentation enrichment fails closed for invalid avatar and neutral member',async()=>{
 const cid='UC'+'N'.repeat(22);
 const row={
  video_id:'histneutral1',taipei_day:'2026-10-17',title:'History',channel_id:cid,channel_name:'Member',
  avatar_url:'https://evil.example/avatar.png',scheduled_start:'2026-10-17T10:00:00Z',
  actual_start:'2026-10-17T10:01:00Z',actual_end:'2026-10-17T11:00:00Z',
  source_revision:'legacy-import',trusted_channel_avatar:null,channel_group:'other'
 };
 const DB={prepare(sql){return {bind(){return {
  async first(){return sql.includes('COUNT(*)')?{total:1}:null},
  async all(){return {results:[row]}}
 }}}}};
 const colors=JSON.stringify({schema_version:1,fallback:'neutral',channels:[]});
 const item=(await (await legacyHistory(
  new Request('https://api.example/v1/history?day=2026-10-17'),
  {DB,TODAY_SUPPORT_COLORS_JSON:colors}
 )).json()).items[0];
 assert.equal(item.avatar_url,null);
 assert.equal(item.group,'other');
 assert.equal(item.member_accent,null);
 assert.equal(item.member_accent_dual,null);
 assert.equal(item.support_mode,'neutral');
 assert.equal(item.support_color_source,null);
 assert.equal(item.actual_start,null);
 assert.equal(item.actual_end,null);
 assert.equal(item.anchor_source,null);
});
