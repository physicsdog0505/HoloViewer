import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {handleVideoMetadataRead} from './worker_host/today/video-metadata-read.mjs';
import {handleVideoMetadataRecovery,processVideoMetadataDemands} from './worker_host/today/video-metadata-recovery.mjs';
import {signature} from './worker_host/today/today-private-post.mjs';

const MANAGED='UC'+'A'.repeat(22);
const EXTERNAL='UC'+'Z'.repeat(22);
const VID='abcdefghijk';
const SECRET='s'.repeat(32);

function getReq(id=VID){return new Request('https://api.example/v1/videos/'+id+'/metadata');}
function youtubeItem({id=VID,channelId=MANAGED,actualStart='2026-10-18T15:00:06Z',actualEnd='2026-10-18T16:04:31Z',scheduled='2026-10-18T15:00:00Z',live='none',livestream=true}={}){
 return {
  id,
  snippet:{channelId,title:'Fallback video',channelTitle:'Channel',liveBroadcastContent:live},
  ...(livestream?{liveStreamingDetails:{
   ...(scheduled?{scheduledStartTime:scheduled}:{}),
   ...(actualStart?{actualStartTime:actualStart}:{}),
   ...(actualEnd?{actualEndTime:actualEnd}:{})
  }}:{})
 };
}
function fetchBody(items,status=200){
 return async()=>new Response(JSON.stringify({items}),{status,headers:{'content-type':'application/json'}});
}
function sqliteD1({managed=true}={}){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0004_video_metadata_cache.sql',import.meta.url),'utf8'));
 sqlite.exec("CREATE TABLE public_history(video_id TEXT PRIMARY KEY,taipei_day TEXT,title TEXT,channel_id TEXT,channel_name TEXT,avatar_url TEXT,scheduled_start TEXT,actual_start TEXT,actual_end TEXT,source_revision TEXT,published_at TEXT);");
 sqlite.exec("CREATE TABLE public_catalog(video_id TEXT PRIMARY KEY,title TEXT,channel_id TEXT,channel_name TEXT,lifecycle_state TEXT,scheduled_start TEXT,actual_start TEXT,avatar_url TEXT);");
 sqlite.exec("CREATE TABLE ptt_threads(day TEXT NOT NULL,aid TEXT NOT NULL,source_url TEXT,verified_at TEXT,PRIMARY KEY(day,aid));");
 sqlite.prepare("INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap,checkpoint) VALUES(1,?,?,?,?,?,NULL)")
  .run('fixture-v1','2026-10-19T00:00:00Z',managed?1:0,managed?1:0,0);
 if(managed)sqlite.prepare("INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)")
  .run(MANAGED,'fixture-v1','2026-10-19T00:00:00Z','hololive');
 function stmt(sql,params=[]){return {
  bind(...values){return stmt(sql,values)},
  async first(){return sqlite.prepare(sql).get(...params)??null},
  async all(){return {results:sqlite.prepare(sql).all(...params)}},
  async run(){return sqlite.prepare(sql).run(...params)}
 }}
 return {
  raw:sqlite,
  prepare(sql){return stmt(sql)},
  async batch(statements){
   sqlite.exec('BEGIN IMMEDIATE');
   try{const out=[];for(const s of statements)out.push(await s.run());sqlite.exec('COMMIT');return out;}
   catch(e){sqlite.exec('ROLLBACK');throw e;}
  },
  close(){sqlite.close()}
 };
}
async function signedRecovery(body,env,{now=new Date('2026-10-20T03:00:00Z'),fetchImpl}={}){
 const raw=JSON.stringify(body),ts=String(now.getTime()),mac=await signature(SECRET,ts,raw);
 const req=new Request('https://api.example/internal/videos/metadata/recover',{
  method:'POST',headers:{'content-type':'application/json','x-today-timestamp':ts,'x-today-signature':mac},body:raw
 });
 return handleVideoMetadataRecovery(req,env,{now,fetchImpl});
}

test('A catalog hit returns source=catalog without provider dependency',async()=>{
 const db=sqliteD1();
 db.raw.prepare("INSERT INTO public_today_canonical(video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
  .run(VID,MANAGED,'fixture-v1','hololive','Catalog','Managed','ended','2026-10-18T16:05:00Z','2026-10-18T16:05:00Z','2026-10-18T15:00:00Z','2026-10-18T15:00:06Z','2026-10-18T16:04:31Z','YouTube liveStreamingDetails','abc');
 const res=await handleVideoMetadataRead(getReq(),{DB:db});
 const body=await res.json();
 assert.equal(res.status,200);assert.equal(body.source,'catalog');assert.equal(body.managed_channel,true);
 assert.equal(body.actual_start,'2026-10-18T15:00:06Z');assert.equal(body.actual_end,'2026-10-18T16:04:31Z');
 db.close();
});

test('public cache miss registers one bounded demand and never calls provider in GET path',async()=>{
 const db=sqliteD1();let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key'};
 const res=await handleVideoMetadataRead(getReq(),env,{now:new Date('2026-10-20T03:00:00Z')});
 const body=await res.json();
 assert.equal(res.status,202);assert.equal(body.status,'metadata_pending');assert.equal(body.priority,2);
 assert.equal(fetches,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_recovery_demand').get().n,1);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_cache').get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,0);
 const drained=await processVideoMetadataDemands(env,{
  now:new Date('2026-10-20T03:00:30Z'),limit:1,
  fetchImpl:async()=>{fetches++;return fetchBody([youtubeItem({channelId:EXTERNAL})])()}
 });
 assert.equal(drained.resolved,1);assert.equal(fetches,1);
 const follow=await handleVideoMetadataRead(getReq(),env,{now:new Date('2026-10-20T03:00:31Z')});
 const followBody=await follow.json();
 assert.equal(follow.status,200);assert.equal(followBody.source,'youtube-fallback');
 db.close();
});

test('verified PTT day raises demand priority without bypassing provider budget',async()=>{
 const db=sqliteD1();
 db.raw.prepare("INSERT INTO ptt_threads(day,aid,verified_at) VALUES(?,?,?)").run('2026-10-18','#fixture','2026-10-20T00:00:00Z');
 const req=new Request('https://api.example/v1/videos/'+VID+'/metadata?ptt_day=2026-10-18');
 const res=await handleVideoMetadataRead(req,{DB:db,YOUTUBE_API_KEY:'key'},{now:new Date('2026-10-20T03:00:00Z')});
 const body=await res.json();
 assert.equal(res.status,202);assert.equal(body.priority,1);assert.equal(body.ptt_priority,true);
 const row=db.raw.prepare('SELECT priority,ptt_day FROM public_video_metadata_recovery_demand WHERE video_id=?').get(VID);
 assert.equal(row.priority,1);assert.equal(row.ptt_day,'2026-10-18');
 db.close();
});

test('twenty public misses for the same video dedupe to one provider lookup',async()=>{
 const db=sqliteD1({managed:false});let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key'};
 const fetchImpl=async()=>{fetches++;return fetchBody([youtubeItem({channelId:EXTERNAL})])()};
 for(let i=0;i<20;i++){
  const res=await handleVideoMetadataRead(getReq(),env,{now:new Date('2026-10-20T03:00:00Z')});
  assert.equal(res.status,202);
 }
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_recovery_demand').get().n,1);
 const drained=await processVideoMetadataDemands(env,{now:new Date('2026-10-20T03:00:30Z'),limit:4,fetchImpl});
 assert.equal(drained.resolved,1);
 assert.equal(fetches,1);
 assert.equal(db.raw.prepare('SELECT calls FROM public_video_metadata_recovery_budget').get().calls,1);
 db.close();
});

test('31 distinct public demands never exceed 30 provider calls and keep excess pending',async()=>{
 const db=sqliteD1({managed:false});let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key'};
 const now=new Date('2026-10-20T03:00:00Z');
 for(let i=0;i<31;i++){
  const id=('0000000000'+i.toString(36)).slice(-11);
  await handleVideoMetadataRead(getReq(id),env,{now});
 }
 const result=await processVideoMetadataDemands(env,{
  now,limit:31,fetchImpl:async()=>{fetches++;return fetchBody([])()}
 });
 assert.equal(fetches,30);assert.equal(result.budget_exhausted,true);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM public_video_metadata_recovery_demand WHERE status='pending'").get().n,1);
 assert.equal(db.raw.prepare('SELECT calls FROM public_video_metadata_recovery_budget').get().calls,30);
 db.close();
});

test('pending demand resumes automatically after budget window renewal',async()=>{
 const db=sqliteD1({managed:false});let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key'};
 const first=new Date('2026-10-20T03:00:00Z');
 db.raw.prepare("INSERT INTO public_video_metadata_recovery_budget(window_start,calls,updated_at) VALUES(?,?,?)")
  .run('2026-10-20T03:00:00Z',30,'2026-10-20T03:00:00Z');
 await handleVideoMetadataRead(getReq(),env,{now:first});
 const blocked=await processVideoMetadataDemands(env,{now:first,limit:1,fetchImpl:async()=>{fetches++;return fetchBody([youtubeItem({channelId:EXTERNAL})])()}});
 assert.equal(blocked.budget_exhausted,true);assert.equal(fetches,0);
 const later=new Date('2026-10-20T03:10:01Z');
 db.raw.prepare("UPDATE public_video_metadata_recovery_demand SET next_attempt_at=? WHERE video_id=?").run('2026-10-20T03:10:00Z',VID);
 const resumed=await processVideoMetadataDemands(env,{now:later,limit:1,fetchImpl:async()=>{fetches++;return fetchBody([youtubeItem({channelId:EXTERNAL})])()}});
 assert.equal(resumed.resolved,1);assert.equal(fetches,1);
 assert.equal(db.raw.prepare('SELECT status FROM public_video_metadata_recovery_demand WHERE video_id=?').get(VID).status,'resolved');
 db.close();
});


test('B owner recovery resolves managed livestream, fills cache, and ingests Today without History',async()=>{
 const db=sqliteD1();
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const res=await signedRecovery({video_id:VID},env,{fetchImpl:fetchBody([youtubeItem()])});
 const body=await res.json();
 assert.equal(res.status,200);assert.equal(body.managed_channel,true);assert.equal(body.is_livestream,true);
 assert.equal(body.history_candidate,true);
 const cache=db.raw.prepare('SELECT * FROM public_video_metadata_cache WHERE video_id=?').get(VID);
 assert.equal(cache.actual_start,'2026-10-18T15:00:06Z');assert.equal(cache.actual_end,'2026-10-18T16:04:31Z');
 const today=db.raw.prepare('SELECT lifecycle_state,actual_start,actual_end FROM public_today_canonical WHERE video_id=?').get(VID);
 assert.equal(today.lifecycle_state,'ended');assert.equal(today.actual_start,'2026-10-18T15:00:06Z');assert.equal(today.actual_end,'2026-10-18T16:04:31Z');
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_history').get().n,0);
 const read=await handleVideoMetadataRead(getReq(),{DB:db});
 assert.equal((await read.json()).source,'catalog');
 db.close();
});

test('C external owner recovery caches metadata but never ingests formal Today/History',async()=>{
 const db=sqliteD1();
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const res=await signedRecovery({video_id:VID},env,{fetchImpl:fetchBody([youtubeItem({channelId:EXTERNAL})])});
 const body=await res.json();
 assert.equal(body.managed_channel,false);assert.equal(body.ingestion.status,'not_managed_or_not_livestream');
 assert.equal(db.raw.prepare('SELECT managed_channel FROM public_video_metadata_cache WHERE video_id=?').get(VID).managed_channel,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_history').get().n,0);
 const publicRead=await handleVideoMetadataRead(getReq(),{DB:db});
 const publicBody=await publicRead.json();
 assert.equal(publicBody.source,'youtube-fallback');assert.equal(publicBody.managed_channel,false);
 db.close();
});

test('managed ordinary upload may cache metadata but never enters Today/History',async()=>{
 const db=sqliteD1();
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const item=youtubeItem({actualStart:null,actualEnd:null,scheduled:null,live:'none',livestream:false});
 const res=await signedRecovery({video_id:VID},env,{fetchImpl:fetchBody([item])});
 const body=await res.json();
 assert.equal(body.managed_channel,true);assert.equal(body.is_livestream,false);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_history').get().n,0);
 db.close();
});

test('D owner provider failure remains explicit and writes nothing',async()=>{
 const db=sqliteD1();
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const res=await signedRecovery({video_id:VID},env,{fetchImpl:async()=>{throw Error('network')}});
 assert.equal(res.status,503);assert.equal((await res.json()).error,'youtube_metadata_unavailable');
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_cache').get().n,0);
 db.close();
});

test('owner recovery requires valid HMAC before provider access',async()=>{
 const db=sqliteD1();let fetches=0;
 const req=new Request('https://api.example/internal/videos/metadata/recover',{
  method:'POST',headers:{'x-today-timestamp':String(Date.parse('2026-10-20T03:00:00Z')),'x-today-signature':'0'.repeat(64)},body:JSON.stringify({video_id:VID})
 });
 const res=await handleVideoMetadataRecovery(req,{DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET},{
  now:new Date('2026-10-20T03:00:00Z'),fetchImpl:async()=>{fetches++;return fetchBody([])()}
 });
 assert.equal(res.status,401);assert.equal(fetches,0);
 db.close();
});


test('signed replay is durable-suppressed before a second provider call',async()=>{
 const db=sqliteD1();let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const fetchImpl=async()=>{fetches++;return fetchBody([youtubeItem()])()};
 const now=new Date('2026-10-20T03:00:00Z');
 const first=await signedRecovery({video_id:VID},env,{now,fetchImpl});
 assert.equal(first.status,200);
 const second=await signedRecovery({video_id:VID},env,{now,fetchImpl});
 assert.equal(second.status,200);
 assert.equal((await second.json()).status,'replay_suppressed');
 assert.equal(fetches,1);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_recovery_replay').get().n,1);
 db.close();
});

test('same video within cooldown reuses cache even with a fresh valid signature',async()=>{
 const db=sqliteD1();let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const fetchImpl=async()=>{fetches++;return fetchBody([youtubeItem({channelId:EXTERNAL})])()};
 const first=await signedRecovery({video_id:VID},env,{now:new Date('2026-10-20T03:00:00Z'),fetchImpl});
 assert.equal(first.status,200);
 const second=await signedRecovery({video_id:VID},env,{now:new Date('2026-10-20T03:00:01Z'),fetchImpl});
 assert.equal(second.status,200);
 const body=await second.json();
 assert.equal(body.status,'cached');
 assert.equal(body.cooldown_seconds,60);
 assert.equal(fetches,1);
 db.close();
});

test('global durable budget caps provider calls at 30 per 10-minute window',async()=>{
 const db=sqliteD1({managed:false});let fetches=0;
 const env={DB:db,YOUTUBE_API_KEY:'key',TODAY_PUBLISH_ENABLED:'true',TODAY_PUBLISH_HMAC_SECRET:SECRET};
 const now=new Date('2026-10-20T03:00:00Z');
 for(let i=0;i<30;i++){
  const id=('0000000000'+i.toString(36)).slice(-11);
  const res=await signedRecovery({video_id:id},env,{now,fetchImpl:async()=>{fetches++;return fetchBody([])()}});
  assert.equal(res.status,404);
 }
 const id31='zzzzzzzzzzz';
 const blocked=await signedRecovery({video_id:id31},env,{now,fetchImpl:async()=>{fetches++;return fetchBody([])()}});
 assert.equal(blocked.status,429);
 const body=await blocked.json();
 assert.equal(body.error,'recovery_budget_exhausted');
 assert.equal(fetches,30);
 const ledger=db.raw.prepare('SELECT calls FROM public_video_metadata_recovery_budget').get();
 assert.equal(ledger.calls,30);
 db.close();
});
