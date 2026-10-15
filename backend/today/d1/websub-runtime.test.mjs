import test from 'node:test';
import assert from 'node:assert/strict';
import {mountTodayWebSubOnWorker} from './websub-runtime.mjs';

test('non-WebSub routes delegate to existing worker unchanged',async()=>{
 let seen=0;
 const base={async fetch(){seen++;return new Response('base',{status:201})}};
 const worker=mountTodayWebSubOnWorker(base,{fetchImpl:async()=>{throw Error('network')}}); 
 const r=await worker.fetch(new Request('https://api.example/health'),{});
 assert.equal(r.status,201);assert.equal(await r.text(),'base');assert.equal(seen,1);
});

test('WebSub ingress is fail-closed when DB/secret are not configured',async()=>{
 const base={async fetch(){throw Error('must not delegate')}};
 const worker=mountTodayWebSubOnWorker(base);
 const r=await worker.fetch(new Request('https://api.example/internal/today/websub?hub.mode=subscribe'));
 assert.equal(r.status,503);
 assert.deepEqual(await r.json(),{error:'receiver_disabled'});
});

test('scheduled preserves existing worker handler then runs Today scheduler without network when disabled',async()=>{
 const order=[];
 const base={async fetch(){return new Response('ok')},async scheduled(){order.push('base')}};
 const worker=mountTodayWebSubOnWorker(base,{fetchImpl:async()=>{throw Error('network')}});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-16T00:00:00Z')},{},{});
 order.push(out.status);
 assert.deepEqual(order,['base','disabled']);
 assert.equal(out.requests,0);
});
