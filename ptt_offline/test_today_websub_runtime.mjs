import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {mountTodayWebSubOnWorker,loadApprovedTodayRoster,shouldRunRenewal} from './worker_host/today/websub-runtime.mjs';
import {recordSubscriptionRequest,confirmSubscriptionChallenge,readSubscriptionLeases} from './worker_host/today/websub-leases.mjs';
import {topicForChannel} from './worker_host/today/websub-receiver.mjs';
import {renewSubscriptions} from './worker_host/today/websub-renewal-send.mjs';
import {planSubscriptions} from './worker_host/today/websub-renewal.mjs';
import {writeEvidence} from './worker_host/today/store.mjs';
import {auditWebSubSchema} from './worker_host/today/websub-schema-preflight.mjs';
import {mountTodayCadence} from './worker_host/today/cadence-refresh.mjs';

const secret='local-fixture-secret-0123456789abcdef';
const version='today-roster-v85';
const channels=Array.from({length:85},(_,i)=>({id:'UC'+String(i).padStart(22,'0'),group:'hololive'}));
const video='abcdefghijk';
const at=new Date('2026-10-17T00:00:00Z');
const stamp=d=>d.toISOString().replace(/\.\d{3}Z$/,'Z');
function makeDb(){
 const raw=new DatabaseSync(':memory:');
 raw.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 raw.exec(readFileSync(new URL('./worker_host/today/discovery-only.sql',import.meta.url),'utf8'));
 raw.exec(readFileSync(new URL('./worker_host/today/websub-leases-only.PROPOSED.sql',import.meta.url),'utf8'));
 raw.prepare('INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap) VALUES(1,?, ?,85,85,0)').run(version,stamp(at));
 for(const c of channels)raw.prepare('INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)').run(c.id,version,stamp(at),c.group);
 function prepared(sql,args=[]){
  return {
   bind(...next){return prepared(sql,next)},
   async first(){return raw.prepare(sql).get(...args)??null},
   async all(){return {results:raw.prepare(sql).all(...args)}},
   async run(){const result=raw.prepare(sql).run(...args);const changes=Number(result.changes??0);return {success:true,changes,meta:{changes}}}
  };
 }
 const db={
  prepare(sql){return prepared(sql)},
  async batch(statements){raw.exec('BEGIN IMMEDIATE');try{const out=[];for(const st of statements)out.push(await st.run());raw.exec('COMMIT');return out}catch(e){raw.exec('ROLLBACK');throw e}},
  raw
 };
 return db;
}
function env(db,overrides={}){
 return {DB:db,TODAY_WEBSUB_RECEIVER_ENABLED:'true',
  TODAY_WEBSUB_CALLBACK_URL:'https://api.example/internal/today/websub',
  TODAY_WEBSUB_SECRET:secret,YOUTUBE_API_KEY:'test-only-key',...overrides};
}
const baseWorker=()=>({async fetch(){return new Response('base',{status:207})},async scheduled(){return {status:'base-scheduled'}}});
function atom(channel=channels[0].id){
 return '<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>'+video+'</yt:videoId><yt:channelId>'+channel+'</yt:channelId></entry></feed>';
}
async function hmac(body,key=secret,algorithm='SHA-256'){
 const k=await crypto.subtle.importKey('raw',new TextEncoder().encode(key),{name:'HMAC',hash:algorithm},false,['sign']);
 return Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',k,new TextEncoder().encode(body))),b=>b.toString(16).padStart(2,'0')).join('');
}
async function challenge(worker,e,channel=channels[0].id,mode='subscribe'){
 const query=new URLSearchParams({'hub.mode':mode,'hub.topic':topicForChannel(channel),'hub.challenge':'challenge-token','hub.lease_seconds':'432000'});
 return worker.fetch(new Request('https://api.example/internal/today/websub?'+query),e,{});
}
async function delivery(worker,e,body=atom(),signature=null){
 const sig=signature??'sha256='+await hmac(body);
 return worker.fetch(new Request('https://api.example/internal/today/websub',{method:'POST',headers:{'x-hub-signature-256':sig,'content-type':'application/atom+xml'},body}),e,{});
}
async function activeLease(db,channel=channels[0].id,rosterVersion=version,mode='subscribe'){
 await recordSubscriptionRequest(db,{channelId:channel,rosterVersion,mode,now:at});
 return confirmSubscriptionChallenge(db,{channelId:channel,rosterVersion,mode,leaseSeconds:432000,now:at});
}

test('runtime roster comes from exact D1-approved roster and validates all 85 rows',async()=>{
 const db=makeDb();
 const roster=await loadApprovedTodayRoster(db);
 assert.equal(roster.version,version);
 assert.equal(roster.expected_channels,85);
 assert.equal(roster.channels.length,85);
 db.raw.prepare('DELETE FROM public_today_approved_channels WHERE channel_id=?').run(channels[0].id);
 await assert.rejects(()=>loadApprovedTodayRoster(db),/row count mismatch/);
 db.raw.close();
});

test('non-WebSub paths delegate; WebSub receiver defaults fail-closed',async()=>{
 const db=makeDb();
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async()=>{throw Error('network forbidden in this test')}});
 const regular=await worker.fetch(new Request('https://api.example/health'),{DB:db},{});
 assert.equal(regular.status,207);
 const off=await worker.fetch(new Request('https://api.example/internal/today/websub'),{DB:db},{});
 assert.equal(off.status,503);
 assert.deepEqual(await off.json(),{error:'receiver_disabled'});
 db.raw.close();
});

test('Hub challenge only activates a matching pending request for current approved roster',async()=>{
 const db=makeDb(),e=env(db),worker=mountTodayWebSubOnWorker(baseWorker());
 const missing=await challenge(worker,e);
 assert.equal(missing.status,403);
 await recordSubscriptionRequest(db,{channelId:channels[0].id,rosterVersion:version,now:new Date()});
 const accepted=await challenge(worker,e);
 assert.equal(accepted.status,200);
 assert.equal(await accepted.text(),'challenge-token');
 const leases=await readSubscriptionLeases(db);
 assert.equal(leases.length,1);
 assert.equal(leases[0].state,'active');
 assert.ok(Date.parse(leases[0].expires_at)>Date.now()+431000000);
 db.raw.close();
});

test('challenge rejects stale roster, wrong mode and unapproved channels',async()=>{
 const db=makeDb(),e=env(db),worker=mountTodayWebSubOnWorker(baseWorker());
 const requestedAt=new Date();
 await recordSubscriptionRequest(db,{channelId:channels[0].id,rosterVersion:'old-roster',now:requestedAt});
 assert.equal((await challenge(worker,e)).status,403);
 await recordSubscriptionRequest(db,{channelId:channels[1].id,rosterVersion:version,mode:'unsubscribe',now:requestedAt});
 assert.equal((await challenge(worker,e,channels[1].id,'subscribe')).status,403);
 assert.equal((await challenge(worker,e,channels[1].id,'unsubscribe')).status,200);
 const outsider='UC'+'Z'.repeat(22);
 const query=new URLSearchParams({'hub.mode':'subscribe','hub.topic':topicForChannel(outsider),'hub.challenge':'no','hub.lease_seconds':'432000'});
 assert.equal((await worker.fetch(new Request('https://api.example/internal/today/websub?'+query),e,{})).status,403);
 db.raw.close();
});

test('HMAC callback requires active lease and durable idempotent queue insert before 204',async()=>{
 const db=makeDb(),e=env(db),worker=mountTodayWebSubOnWorker(baseWorker());
 const raw=atom();
 const bad=await delivery(worker,e,raw,'sha256='+'0'.repeat(64));
 assert.equal(bad.status,401);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_websub_events').get().n,0);
 const noLease=await delivery(worker,e,raw);
 assert.equal(noLease.status,403);
 await activeLease(db);
 const ok=await delivery(worker,e,raw);
 assert.equal(ok.status,204);
 const dupe=await delivery(worker,e,raw);
 assert.equal(dupe.status,204);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_websub_events').get().n,1);
 const row=db.raw.prepare('SELECT channel_id,video_id,roster_version,status FROM public_today_websub_events').get();
 assert.deepEqual({...row},{channel_id:channels[0].id,video_id:video,roster_version:version,status:'pending'});
 db.raw.close();
});

test('explicit lease renewal is bounded and never sends by default',async()=>{
 const db=makeDb(),roster=await loadApprovedTodayRoster(db);
 let calls=0;
 const off=await renewSubscriptions({roster,leases:[],db,callback:'https://api.example/internal/today/websub',secret,
  post:async()=>{calls++;throw Error('must not send')},now:at,limit:10});
 assert.equal(off.status,'DISABLED');
 assert.equal(off.sent,0);
 assert.equal(calls,0);
 const on=await renewSubscriptions({roster,leases:[],db,callback:'https://api.example/internal/today/websub',secret,enabled:true,
  post:async(url,body)=>{calls++;assert.equal(url,'https://pubsubhubbub.appspot.com/subscribe');
   assert.equal(body.get('hub.topic').startsWith('https://www.youtube.com/xml/feeds/videos.xml?channel_id='),true);
   return {status:202}},now:at,limit:10});
 assert.equal(on.sent,10);
 assert.equal(on.planned,10);
 assert.equal(on.has_more,true);
 assert.equal(calls,10);
 assert.equal((await readSubscriptionLeases(db)).filter(x=>x.state==='pending').length,10);
 db.raw.close();
});

test('hourly renewal cadence is explicit and has no network side effect by itself',()=>{
 assert.equal(shouldRunRenewal(new Date('2026-10-17T01:00:00Z')),true);
 assert.equal(shouldRunRenewal(new Date('2026-10-17T01:01:00Z')),false);
});

test('composed scheduled entry preserves cadence and runs WebSub processing plus bounded renewal',async()=>{
 const db=makeDb();
 let hubPosts=0;
 const fetchImpl=async url=>{
  assert.equal(String(url),'https://pubsubhubbub.appspot.com/subscribe');
  hubPosts++;
  return new Response(null,{status:202});
 };
 const worker=mountTodayWebSubOnWorker(mountTodayCadence(baseWorker(),{fetchImpl}),{fetchImpl});
 const out=await worker.scheduled(
  {scheduledTime:Date.parse('2026-10-17T01:00:00Z')},
  env(db,{
   TODAY_CADENCE_ENABLED:'false',TODAY_DISCOVERY_ENABLED:'false',
   TODAY_WEBSUB_PROCESS_ENABLED:'true',TODAY_WEBSUB_RENEW_ENABLED:'true'
  }),{}
 );
 assert.equal(out.lifecycle.status,'disabled');
 assert.equal(out.discovery.status,'disabled');
 assert.equal(out.websub.processing.updated,0);
 assert.equal(out.websub.renewal.status,'SUBMITTED_PENDING_CHALLENGE');
 assert.equal(out.websub.renewal.sent,10);
 assert.equal(hubPosts,10);
 db.raw.close();
});

test('scheduled processor acknowledges non-live uploads without creating Today rows',async()=>{
 const db=makeDb();
 await activeLease(db);
 const body=atom();
 const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
 const eventHash=Array.from(new Uint8Array(sha),b=>b.toString(16).padStart(2,'0')).join('');
 db.raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status,attempts) VALUES(?,?,?,?,?,'pending',0)")
  .run(eventHash,channels[0].id,video,version,stamp(at));
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async url=>{
  assert.ok(String(url).includes('googleapis.com/youtube/v3/videos'));
  return new Response(JSON.stringify({items:[{id:video,snippet:{channelId:channels[0].id,title:'ordinary upload',channelTitle:'Test',liveBroadcastContent:'none'}}]}),{status:200});
 }});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-17T00:05:00Z')},env(db,{TODAY_WEBSUB_PROCESS_ENABLED:'true'}),{});
 assert.equal(out.status,'base-scheduled');
 assert.equal(out.websub.processing.ignored_non_live,1);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_canonical').get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n,0);
 assert.equal(db.raw.prepare('SELECT status FROM public_today_websub_events WHERE event_hash=?').get(eventHash).status,'processed');
 db.raw.close();
});

test('deleted-entry notices are acked safely and signal bounded reconciliation',async()=>{
 const db=makeDb();
 await activeLease(db);
 const body='<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"><deleted-entry xmlns="http://purl.org/atompub/tombstones/1.0" ref="https://www.youtube.com/watch?v='+video+'"><yt:channelId>'+channels[0].id+'</yt:channelId></deleted-entry></feed>';
 const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
 const eventHash=Array.from(new Uint8Array(sha),b=>b.toString(16).padStart(2,'0')).join('');
 db.raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status,attempts) VALUES(?,?,NULL,?,? ,'pending',0)")
  .run(eventHash,channels[0].id,version,stamp(at));
 let atomCalls=0,videoCalls=0;
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async url=>{
  const u=String(url);
  if(u.includes('youtube.com/feeds/videos.xml')){
   atomCalls++;
   return new Response(atom(channels[0].id),{status:200,headers:{'content-type':'application/atom+xml'}});
  }
  if(u.includes('googleapis.com/youtube/v3/videos')){videoCalls++;throw Error('videos.list not expected in deleted-notice recovery cycle');}
  throw Error('unexpected recovery request '+u);
 }});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-17T00:05:00Z')},env(db,{TODAY_WEBSUB_PROCESS_ENABLED:'true'}),{});
 assert.equal(out.websub.processing.deleted_notices,1);
 assert.equal(out.websub.processing.reconcile_required,true);
 assert.deepEqual(out.websub.processing.reconcile_channels,[channels[0].id]);
 assert.equal(out.websub.recovery.status,'bounded_atom_reconcile');
 assert.equal(out.websub.recovery.channels,1);
 assert.equal(atomCalls,1);
 assert.equal(videoCalls,0);
 assert.equal(db.raw.prepare('SELECT status FROM public_today_websub_events WHERE event_hash=?').get(eventHash).status,'processed');
 assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM public_today_websub_events WHERE status='pending'").get().n,1);
 db.raw.close();
});

test('transient videos.list failure retries under a token-fenced bounded lease',async()=>{
 const db=makeDb();
 await activeLease(db);
 const body=atom();
 const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
 const eventHash=Array.from(new Uint8Array(sha),b=>b.toString(16).padStart(2,'0')).join('');
 db.raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status,attempts) VALUES(?,?,?,?,?,'pending',0)")
  .run(eventHash,channels[0].id,video,version,stamp(at));
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async()=>new Response('upstream error',{status:503})});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-17T00:05:00Z')},env(db,{TODAY_WEBSUB_PROCESS_ENABLED:'true'}),{});
 assert.equal(out.websub.processing.failed,1);
 const row=db.raw.prepare('SELECT status,attempts,claim_token,claim_until FROM public_today_websub_events WHERE event_hash=?').get(eventHash);
 assert.equal(row.status,'pending');
 assert.equal(row.attempts,1);
 assert.equal(row.claim_token,null);
 assert.equal(row.claim_until,null);
 db.raw.close();
});


test('unchanged pushed livestream snapshot acknowledges without another evidence/canonical write',async()=>{
 const db=makeDb(),channel=channels[0].id;
 const current={video_id:video,channel_id:channel,roster_version:version,group:'hololive',
  title:'Same live stream',channel_name:'Test Channel',lifecycle_state:'live',
  observed_at:'2026-10-17T00:00:00Z',scheduled_start:null,
  actual_start:'2026-10-16T23:55:00Z',actual_end:null,source_label:'YouTube'};
 await writeEvidence(db,current);
 const beforeEvidence=db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n;
 const body=atom(channel);
 const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
 const eventHash=Array.from(new Uint8Array(sha),b=>b.toString(16).padStart(2,'0')).join('');
 db.raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status,attempts) VALUES(?,?,?,?,?,'pending',0)")
  .run(eventHash,channel,video,version,stamp(at));
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async url=>{
  assert.ok(String(url).includes('googleapis.com/youtube/v3/videos'));
  return new Response(JSON.stringify({items:[{id:video,
   snippet:{channelId:channel,title:current.title,channelTitle:current.channel_name,liveBroadcastContent:'live'},
   liveStreamingDetails:{actualStartTime:current.actual_start}}]}),{status:200});
 }});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-17T00:05:00Z')},
  env(db,{TODAY_WEBSUB_PROCESS_ENABLED:'true'}),{});
 assert.equal(out.websub.processing.unchanged,1);
 assert.equal(out.websub.processing.updated,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n,beforeEvidence);
 assert.equal(db.raw.prepare('SELECT lifecycle_observed_at FROM public_today_canonical WHERE video_id=?').get(video).lifecycle_observed_at,current.observed_at);
 assert.equal(db.raw.prepare('SELECT status FROM public_today_websub_events WHERE event_hash=?').get(eventHash).status,'processed');
 db.raw.close();
});


test('expired active lease cannot continue accepting Hub callback',async()=>{
 const db=makeDb(),worker=mountTodayWebSubOnWorker(baseWorker());
 await activeLease(db);
 db.raw.prepare("UPDATE public_today_websub_leases SET expires_at=? WHERE channel_id=?")
  .run('2026-10-16T00:00:00Z',channels[0].id);
 const result=await delivery(worker,env(db),atom());
 assert.equal(result.status,403);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_websub_events').get().n,0);
 db.raw.close();
});

test('expired processing claim is recovered and completed without duplicate event insert',async()=>{
 const db=makeDb(),channel=channels[0].id,body=atom(channel);
 const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body));
 const eventHash=Array.from(new Uint8Array(sha),b=>b.toString(16).padStart(2,'0')).join('');
 db.raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status,attempts,claim_token,claim_until) VALUES(?,?,?,?,?,'processing',0,?,?)")
  .run(eventHash,channel,video,version,stamp(at),'a'.repeat(64),'2026-10-17T00:04:00Z');
 const worker=mountTodayWebSubOnWorker(baseWorker(),{fetchImpl:async url=>{
  assert.ok(String(url).includes('googleapis.com/youtube/v3/videos'));
  return new Response(JSON.stringify({items:[{id:video,
   snippet:{channelId:channel,title:'Recovered live',channelTitle:'Test',liveBroadcastContent:'live'},
   liveStreamingDetails:{actualStartTime:'2026-10-17T00:00:00Z'}}]}),{status:200});
 }});
 const out=await worker.scheduled({scheduledTime:Date.parse('2026-10-17T00:05:30Z')},
  env(db,{TODAY_WEBSUB_PROCESS_ENABLED:'true'}),{});
 assert.equal(out.websub.processing.updated,1);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_websub_events').get().n,1);
 assert.equal(db.raw.prepare('SELECT status FROM public_today_websub_events WHERE event_hash=?').get(eventHash).status,'processed');
 db.raw.close();
});


test('read-only schema preflight passes proposed fixture and fails closed when lease schema is missing',async()=>{
 const db=makeDb();
 const before=db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_approved_channels').get().n;
 const good=await auditWebSubSchema(db);
 assert.equal(good.status,'PASS');
 assert.equal(good.mode,'READ_ONLY');
 assert.equal(good.approved_channels,85);
 assert.equal(good.expected_channels,85);
 assert.ok(Object.values(good.tables).every(x=>x.status==='PASS'));
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_approved_channels').get().n,before);
 db.raw.exec('DROP TABLE public_today_websub_leases');
 const missing=await auditWebSubSchema(db);
 assert.equal(missing.status,'HOLD');
 assert.deepEqual(missing.tables.public_today_websub_leases.missing_columns,
  ['channel_id','roster_version','topic','requested_mode','state','requested_at','verified_at','expires_at','lease_seconds','last_error']);
 db.raw.close();
});


test('lease with old approved roster version is due even when its expiry is far away',()=>{
 const a=channels[0].id;
 const plan=planSubscriptions({version,channels:[{id:a}]},[
  {channel_id:a,roster_version:'old-version',state:'active',expires_at:'2026-10-25T00:00:00Z'}
 ],{now:at,limit:10});
 assert.deepEqual(plan.due.map(x=>x.channel_id),[a]);
 assert.equal(plan.due[0].roster_version,version);
});
