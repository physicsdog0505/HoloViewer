import test from 'node:test';
import assert from 'node:assert/strict';
import {mountOwnerPublisherOnExistingApiRouter} from './api_owner_shell_extension.mjs';
function accepted(){return {async fetch(){return new Response('accepted-read',{status:200})}}}
test('legacy GET and Today read remain delegated',async()=>{
 const r=mountOwnerPublisherOnExistingApiRouter(accepted());
 const response=await r.fetch(new Request('https://api.example/v1/catalog/today'),{});
 assert.equal(response.status,200);assert.equal(await response.text(),'accepted-read');
});
test('private owner endpoint blocked unless enabled and signed',async()=>{
 const r=mountOwnerPublisherOnExistingApiRouter(accepted(),{verifyAuthority:async()=>true});
 const request=new Request('https://api.example/private/ptt/publish',{method:'POST',body:'{}'});
 const reply=await r.fetch(request,{DB:{batch(){throw Error('unexpected')}}});
 assert.equal(reply.status,503);
});
test('browser origin cannot call owner endpoint',async()=>{
 const r=mountOwnerPublisherOnExistingApiRouter(accepted(),{verifyAuthority:async()=>true});
 const req=new Request('https://api.example/private/ptt/publish',{method:'POST',
 headers:{origin:'https://public.example'},body:'{}'});
 const reply=await r.fetch(req,{PTT_PUBLISH_ENABLED:'true',DB:{batch(){throw Error('unexpected')}}});
 assert.equal(reply.status,403);
});
