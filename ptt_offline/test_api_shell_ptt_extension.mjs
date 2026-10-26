import test from 'node:test';
import assert from 'node:assert/strict';
import {createPttMountedApiRouter,REVIEWED_API_SHELL_BASE} from './api_shell_ptt_extension.mjs';

function exactSeamFixture({pttHandler, legacyHistory, legacyVideo}={}) {
  return {async fetch(request,env){
    const url=new URL(request.url);
    const origin=request.headers.get('origin');
    if(origin && origin!==env.ALLOWED_ORIGIN)return new Response('blocked',{status:403});
    if(request.method==='OPTIONS')return new Response(null,{status:204});
    if(request.method!=='GET')return new Response('method',{status:405});
    if(url.pathname==='/health')return new Response(null,{status:env.DB?200:503});
    if(!env.DB)return new Response('missing DB',{status:503});
    if(url.pathname==='/v1/catalog/today')return new Response('canonical #47 Today');
    if(['/v1/ptt/today','/v1/ptt/history'].includes(url.pathname))
      return pttHandler(request,env);
    if(url.pathname==='/v1/history')return legacyHistory?.(request,env);
    return new Response('not_found',{status:404});
  }};
}
const env={DB:{prepare(sql){
  if(/insert|update|delete|drop|create/i.test(sql))throw new Error('unexpected D1 write');
  return {bind(){return {all:async()=>({results:[]})}}};
}},ALLOWED_ORIGIN:'https://viewer.example'};
const get=(path,opts={})=>new Request('https://api.example'+path,opts);

test('exact reviewed base HEAD is declared and handler-only extension is injected',()=>{
 assert.equal(REVIEWED_API_SHELL_BASE,'149a80361654b06377dbae580e1d8da2e5010cf0');
 assert.throws(()=>createPttMountedApiRouter(null),TypeError);
 assert.throws(()=>createPttMountedApiRouter(exactSeamFixture,{pttHandler(){}}),TypeError);
});

test('PTT Today/History both mount; history after stays on GET read contract',async()=>{
 const router=createPttMountedApiRouter(exactSeamFixture);
 for(const path of ['/v1/ptt/today?day=2026-10-15',
                    '/v1/ptt/history?day=2026-10-15&after=anchor']){
   const response=await router.fetch(get(path),env);
   assert.equal(response.status,503); // no verified threads: fail closed
 }
});

test('Today/health/legacy/method/origin gates remain with #47 shell',async()=>{
 const router=createPttMountedApiRouter(exactSeamFixture,{
   legacyHistory:()=>new Response('legacy History')
 });
 assert.equal(await (await router.fetch(get('/v1/catalog/today'),env)).text(),
              'canonical #47 Today');
 assert.equal((await router.fetch(get('/health'),env)).status,200);
 assert.equal(await (await router.fetch(get('/v1/history'),env)).text(),
              'legacy History');
 assert.equal((await router.fetch(get('/v1/ptt/today',{method:'POST'}),env)).status,405);
 assert.equal((await router.fetch(get('/v1/ptt/today',{
   method:'OPTIONS',headers:{origin:'https://viewer.example'}}),env)).status,204);
 assert.equal((await router.fetch(get('/v1/ptt/today',{
   headers:{origin:'https://not-allowed.example'}}),env)).status,403);
 assert.equal((await router.fetch(get('/v1/ptt/today'),{...env,DB:null})).status,503);
});
