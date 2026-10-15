import test from 'node:test';
import assert from 'node:assert/strict';
import {createExistingApiRouter} from './api-shell.mjs';
const ORIGIN='https://holoviewer-public.singlebagel.workers.dev';
const router=createExistingApiRouter({
 legacyHistory:async()=>new Response('history'),
 legacyVideo:async()=>new Response('video')});
const env={DB:null,ALLOWED_ORIGIN:ORIGIN};
const db={prepare(sql){if(sql.includes('catalog_meta'))return {first:async()=>null};
 if(sql.includes('public_today_canonical'))return {bind(){return {all:async()=>({results:[]})}}};
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
