import test from 'node:test';import assert from 'node:assert/strict';import {runTodayScheduled} from './cloud-scheduled.mjs';
test('disabled collector makes no network calls',async()=>{
 const result=await runTodayScheduled({}, {fetchImpl:async()=>{throw Error('network was called')}});
 assert.deepEqual(result,{status:'disabled',requests:0});
});
test('enabled collector refuses missing credentials and invalid roster',async()=>{
 await assert.rejects(()=>runTodayScheduled({TODAY_COLLECTOR_ENABLED:'true'}),/configuration missing/);
 await assert.rejects(()=>runTodayScheduled({TODAY_COLLECTOR_ENABLED:'true',DB:{},YOUTUBE_API_KEY:'test',TODAY_APPROVED_ROSTER:'{"channels":[]}'}),/roster size/);
});
