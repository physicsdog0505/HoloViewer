import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {handleVideoMetadataRead} from './worker_host/today/video-metadata-read.mjs';
import {handleVideoMetadataRecovery} from './worker_host/today/video-metadata-recovery.mjs';
import {signature} from './worker_host/today/today-private-post.mjs';

const MANAGED='UC'+'A'.repeat(22);
const EXTERNAL='UC'+'Z'.repeat(22);
const VID='abcdefghijk';
const SECRET='s'.repeat(32);

function getReq(id=VID){return new Request('https://api.example/v1/videos/'+id+'/metadata');}
function youtubeItem({channelId=MANAGED,actualStart='2026-10-18T15:00:06Z',actualEnd='2026-10-18T16:04:31Z',scheduled='2026-10-18T15:00:00Z',live='none',livestream=true}={}){
 return {
  id:VID,
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

test('public cache miss is fail-closed and never invokes provider or writes',async()=>{
 const db=sqliteD1();
 const before=db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_cache').get().n;
 const res=await handleVideoMetadataRead(getReq(),{DB:db,YOUTUBE_API_KEY:'key'});
 const body=await res.json();
 assert.equal(res.status,404);assert.equal(body.error,'metadata_not_cached');assert.equal(body.lifecycle_state,'unknown');
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_video_metadata_cache').get().n,before);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,0);
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
