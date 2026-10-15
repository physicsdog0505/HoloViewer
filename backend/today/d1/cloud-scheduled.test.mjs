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

test('enabled WebSub renewal uses existing lease ledger and Hub sender behind explicit flag',async()=>{
 const calls=[];
 const db={prepare(sql){
  return {bind(){return this},all:async()=>{
   if(sql.includes('FROM public_today_websub_leases'))return {results:[]};
   if(sql.includes('FROM public_today_websub_events'))return {results:[]};
   throw Error('unexpected all '+sql);
  },run:async()=>{
   if(sql.includes('INSERT INTO public_today_websub_leases'))return {success:true};
   throw Error('unexpected run '+sql);
  },first:async()=>null};
 }};
 const channel='UC'+'A'.repeat(22);
 const env={TODAY_COLLECTOR_ENABLED:'true',TODAY_WEBSUB_RENEW_ENABLED:'true',
  TODAY_WEBSUB_CALLBACK:'https://api.example/internal/today/websub',
  TODAY_WEBSUB_SECRET:'s'.repeat(32),TODAY_WEBSUB_RENEW_LIMIT:'25',
  DB:db,YOUTUBE_API_KEY:'test-key',
  TODAY_APPROVED_ROSTER:JSON.stringify({version:'v1',channels:[{id:channel,group:'hololive'}]})};
 const result=await runTodayScheduled(env,{now:new Date('2026-10-16T00:00:00Z'),fetchImpl:async(url,opts)=>{
  calls.push({url:String(url),method:opts?.method??'GET',body:String(opts?.body??'')});
  if(String(url).includes('pubsubhubbub.appspot.com'))return {status:202,ok:true};
  throw Error('unexpected network '+url);
 }});
 assert.equal(result.websub.sent,1);
 assert.equal(result.websub.status,'SUBMITTED_PENDING_CHALLENGE');
 assert.equal(result.updated,0);
 assert.equal(calls.length,1);
 assert.equal(calls[0].method,'POST');
 assert.match(calls[0].body,/hub\.mode=subscribe/);
});
test('WebSub renewal remains disabled unless explicit flag is true',async()=>{
 const db={prepare(){return {bind(){return this},all:async()=>({results:[]})}}};
 const env={TODAY_COLLECTOR_ENABLED:'true',DB:db,YOUTUBE_API_KEY:'test-key',
  TODAY_APPROVED_ROSTER:JSON.stringify({version:'v1',channels:[{id:'UC'+'A'.repeat(22),group:'hololive'}]})};
 const result=await runTodayScheduled(env,{fetchImpl:async()=>{throw Error('network should not be called')}});
 assert.equal(result.websub,null);
});
