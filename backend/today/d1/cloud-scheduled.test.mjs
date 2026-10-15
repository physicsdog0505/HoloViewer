import test from 'node:test';import assert from 'node:assert/strict';import {runTodayScheduled} from './cloud-scheduled.mjs';
test('disabled collector makes no network calls',async()=>{
 const result=await runTodayScheduled({}, {fetchImpl:async()=>{throw Error('network was called')}});
 assert.deepEqual(result,{status:'disabled',requests:0});
});
test('enabled collector refuses missing credentials and invalid roster',async()=>{
 await assert.rejects(()=>runTodayScheduled({TODAY_COLLECTOR_ENABLED:'true'}),/configuration missing/);
 await assert.rejects(()=>runTodayScheduled({TODAY_COLLECTOR_ENABLED:'true',DB:{},YOUTUBE_API_KEY:'test',TODAY_APPROVED_ROSTER:'{"channels":[]}'}),/roster size/);
});

test('explicit reconciliation flag requires durable store; no provider calls on invalid queue',async()=>{
 const env={TODAY_COLLECTOR_ENABLED:'true',TODAY_RECONCILE_ENABLED:'true',
  DB:{prepare(){throw Error('queue schema unavailable')}},YOUTUBE_API_KEY:'test-key',
  TODAY_APPROVED_ROSTER:JSON.stringify({version:'v1',channels:[{id:'UC'+'A'.repeat(22),group:'hololive'}]})};
 await assert.rejects(()=>runTodayScheduled(env,{fetchImpl:async()=>({ok:true,
   headers:{get:()=>null},text:async()=>'<feed></feed>'})}),/queue schema unavailable/);
});
