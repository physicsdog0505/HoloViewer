import test from 'node:test';
import assert from 'node:assert/strict';
import {createExistingApiRouter} from './api-shell.mjs';
const ORIGIN='https://holoviewer-public.singlebagel.workers.dev';
const router=createExistingApiRouter({allowedOrigins:[ORIGIN],
 legacyHistory:async()=>new Response('history'),
 legacyVideo:async()=>new Response('video')});
const db={prepare(sql){if(sql.includes('catalog_meta'))return {first:async()=>null};
 if(sql.includes('public_today_canonical'))return {bind(){return {all:async()=>({results:[]})}}};
 throw Error('unexpected SELECT');}};
function req(path,method='GET',origin=ORIGIN){return new Request('https://api.example'+path,{method,headers:{origin}});}
test('known origin gets CORS, OPTIONS and GET gate',async()=>{
 assert.equal((await router.fetch(req('/health','OPTIONS'),{DB:db})).status,204);
 assert.equal((await router.fetch(req('/health','POST'),{DB:db})).status,405);
 const response=await router.fetch(req('/health'),{DB:db});
 assert.equal(response.status,200);
 assert.equal(response.headers.get('access-control-allow-origin'),ORIGIN);
 assert.equal((await router.fetch(req('/health','GET','https://evil.example'),{DB:db})).status,403);
});
test('health binding and Today use existing DB; no writes',async()=>{
 assert.equal((await router.fetch(req('/health'),{})).status,503);
 const r=await router.fetch(req('/v1/catalog/today?day=2026-10-15'),{DB:db});
 assert.equal(r.status,200);
 assert.equal((await r.json()).schema_version,'public-consumer-v1');
});
test('legacy route handlers preserved and unknown route 404',async()=>{
 assert.equal(await (await router.fetch(req('/v1/history'),{DB:db})).text(),'history');
 assert.equal(await (await router.fetch(req('/v1/catalog/videos/abcdefghijk'),{DB:db})).text(),'video');
 assert.equal((await router.fetch(req('/v1/absent'),{DB:db})).status,404);
});
test('PTT extension requires explicitly injected reviewed handler',async()=>{
 assert.equal((await router.fetch(req('/v1/ptt/today'),{DB:db})).status,404);
 const ptt=createExistingApiRouter({allowedOrigins:[ORIGIN],pttHandler:async()=>new Response('ptt')});
 assert.equal(await (await ptt.fetch(req('/v1/ptt/today'),{DB:db})).text(),'ptt');
});
