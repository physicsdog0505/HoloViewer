import test from 'node:test';
import assert from 'node:assert/strict';
import {composeFullPttOnExistingApi} from './full_ptt_api_composition.mjs';
test('composed host keeps legacy routes, PTT read dispatch and private write deny',async()=>{
 const factory=({pttHandler})=>({async fetch(request,env){
  const pathname=new URL(request.url).pathname;
  if(pathname==='/v1/ptt/today')return pttHandler(request,env);
  return new Response('existing legacy response',{status:200});
 }});
 const host=composeFullPttOnExistingApi(factory,{verifyAuthority:async()=>false});
 const legacy=await host.fetch(new Request('https://api.example/v1/history'),{});
 assert.equal(legacy.status,200);
 assert.equal(await legacy.text(),'existing legacy response');
 const read=await host.fetch(new Request('https://api.example/v1/ptt/today?day=2026-10-15'),{});
 assert.equal(read.status,503);
 const write=await host.fetch(new Request('https://api.example/private/ptt/publish',{method:'POST',body:'{}'}),{});
 assert.equal(write.status,503);
});
