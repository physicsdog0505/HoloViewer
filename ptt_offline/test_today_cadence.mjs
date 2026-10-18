import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshKnownTodayLifecycle,mountTodayCadence,shouldRunLifecycleRefresh,PROVIDER_MISS_RETIRE_THRESHOLD} from './worker_host/today/cadence-refresh.mjs';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

function fakeDb(rows){
  return {
    writes:[],
    prepare(sql){
      const self=this;
      return {
        bind(...args){
          return {
            all:async()=>({results:rows}),
            first:async()=>null,
            run:async()=>{self.writes.push({sql,args});return {success:true}}
          };
        },
        all:async()=>({results:rows}),
        first:async()=>null
      };
    },
    async batch(statements){ this.writes.push(...statements); return statements.map(()=>({success:true})); }
  };
}

test('cadence is disabled without explicit backend flag',async()=>{
  const out=await refreshKnownTodayLifecycle({}, {fetchImpl:async()=>{throw Error('network')}} );
  assert.equal(out.status,'disabled');
  assert.equal(out.requests,0);
});

test('known lifecycle refresh uses one bounded videos.list request',async()=>{
  const row={
    video_id:'abcdefghijk',
    publisher_channel_id:'UC'+'A'.repeat(22),
    roster_version:'v85',
    channel_group:'hololive',
    title:'Old title',
    channel_name:'Channel',
    lifecycle_observed_at:'2026-10-15T20:00:00Z'
  };
  const db=fakeDb([row]);
  let calls=0;
  const out=await refreshKnownTodayLifecycle(
    {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:db},
    {now:new Date('2026-10-15T21:50:00Z'),fetchImpl:async url=>{
      calls++;
      assert.match(url,/googleapis\.com\/youtube\/v3\/videos/);
      assert.match(url,/id=abcdefghijk/);
      return new Response(JSON.stringify({items:[{
        id:'abcdefghijk',
        snippet:{channelId:row.publisher_channel_id,title:'Fresh',channelTitle:'Channel',liveBroadcastContent:'live'},
        liveStreamingDetails:{actualStartTime:'2026-10-15T21:45:00Z'}
      }]}),{status:200,headers:{'content-type':'application/json'}});
    }}
  );
  assert.equal(calls,1);
  assert.equal(out.requests,1);
  assert.equal(out.updated,1);
});

test('combined cadence wrapper preserves fetch contract',async()=>{
  const base={async fetch(){return new Response('same',{status:207})}};
  const worker=mountTodayCadence(base,{fetchImpl:async()=>{throw Error('network')}});
  const r=await worker.fetch(new Request('https://api.example/v1/catalog/today'),{});
  assert.equal(r.status,207);
  assert.equal(await r.text(),'same');
});


test('lifecycle refresh cadence is every five minutes while discovery cron remains independent',()=>{
  assert.equal(shouldRunLifecycleRefresh(new Date('2026-10-16T06:40:00Z')),true);
  assert.equal(shouldRunLifecycleRefresh(new Date('2026-10-16T06:41:00Z')),false);
  assert.equal(shouldRunLifecycleRefresh(new Date('2026-10-16T06:44:59Z')),false);
  assert.equal(shouldRunLifecycleRefresh(new Date('2026-10-16T06:45:00Z')),true);
});


test('cadence includes recent ended rows needing authoritative re-verification for 7-day history',async()=>{
  const row={
    video_id:'recentend01',
    publisher_channel_id:'UC'+'A'.repeat(22),
    roster_version:'v85',
    channel_group:'hololive',
    title:'Ended',
    channel_name:'Channel',
    lifecycle_observed_at:'2026-10-17T10:00:00Z',
    scheduled_start:'2026-10-17T08:00:00Z',
    actual_start:'2026-10-17T08:01:00Z',
    actual_end:'2026-10-17T09:00:00Z',
    source_label:'YouTube'
  };
  let selectSql='',selectArgs=[];
  const db={
    writes:[],
    prepare(sql){
      if(sql.includes('FROM public_today_canonical')&&sql.includes('ORDER BY lifecycle_observed_at')){
        selectSql=sql;
        return {bind(...args){selectArgs=args;return {all:async()=>({results:[row]})}}};
      }
      return {
        bind(...args){return {
          first:async()=>null,
          all:async()=>({results:[]}),
          run:async()=>({success:true,args})
        }},
        first:async()=>null
      };
    },
    async batch(statements){this.writes.push(...statements);return statements.map(()=>({success:true}))}
  };
  const out=await refreshKnownTodayLifecycle(
    {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:db},
    {now:new Date('2026-10-18T05:00:00Z'),fetchImpl:async()=>new Response(JSON.stringify({items:[{
      id:'recentend01',
      snippet:{channelId:row.publisher_channel_id,title:'Ended',channelTitle:'Channel',liveBroadcastContent:'none'},
      liveStreamingDetails:{
        scheduledStartTime:'2026-10-17T08:00:00Z',
        actualStartTime:'2026-10-17T08:01:00Z',
        actualEndTime:'2026-10-17T09:00:00Z'
      }
    }]}),{status:200,headers:{'content-type':'application/json'}})}
  );
  assert.match(selectSql,/lifecycle_state='ended'/);
  assert.match(selectSql,/actual_end>=\?/);
  assert.equal(selectArgs[1],'YouTube liveStreamingDetails');
  assert.equal(out.updated,1);
});


function retirementDb(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0003_provider_missing_retirement.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
 sqlite.exec('CREATE TABLE public_catalog(video_id TEXT,channel_id TEXT,avatar_url TEXT,actual_start TEXT,scheduled_start TEXT)');
 sqlite.exec(`CREATE TABLE public_history(
   video_id TEXT PRIMARY KEY NOT NULL,taipei_day TEXT NOT NULL,title TEXT NOT NULL,
   channel_id TEXT NOT NULL,channel_name TEXT NOT NULL DEFAULT '',avatar_url TEXT NOT NULL DEFAULT '',
   scheduled_start TEXT,actual_start TEXT,actual_end TEXT NOT NULL,source_revision TEXT NOT NULL,published_at TEXT NOT NULL
 )`);
 function statement(sql,params=[]){return {
  bind(...values){return statement(sql,values)},
  async first(){return sqlite.prepare(sql).get(...params)??null},
  async all(){return {results:sqlite.prepare(sql).all(...params)}},
  async run(){return sqlite.prepare(sql).run(...params)}
 }}
 return {
  raw:sqlite,prepare(sql){return statement(sql)},
  async batch(statements){sqlite.exec('BEGIN IMMEDIATE');try{const out=[];for(const s of statements)out.push(await s.run());sqlite.exec('COMMIT');return out;}catch(e){sqlite.exec('ROLLBACK');throw e;}},
  close(){sqlite.close()}
 };
}
function seedLive(db,id='ghostlive01'){
 const cid='UC'+'G'.repeat(22);
 db.raw.prepare(`INSERT INTO public_today_canonical
  (video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,
   lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
   id,cid,'v85','hololive','Ghost','Channel','live',
   '2026-10-18T03:35:19Z','2026-10-18T03:35:19Z',
   '2026-10-18T03:00:00Z','2026-10-18T03:01:00Z',null,'YouTube','legacy'
  );
 return cid;
}
const emptyVideos=async()=>new Response(JSON.stringify({items:[]}),{status:200,headers:{'content-type':'application/json'}});

test('one transient videos.list omission retains live row and never fabricates actual_end',async()=>{
 const d=retirementDb();seedLive(d);
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d},
  {now:new Date('2026-10-18T08:30:00Z'),fetchImpl:emptyVideos}
 );
 assert.equal(out.missing,1);
 assert.equal(out.retired_missing,0);
 const row=d.raw.prepare('SELECT lifecycle_state,actual_end,lifecycle_observed_at FROM public_today_canonical WHERE video_id=?').get('ghostlive01');
 assert.equal(row.lifecycle_state,'live');
 assert.equal(row.actual_end,null);
 assert.equal(row.lifecycle_observed_at,'2026-10-18T03:35:19Z');
 assert.equal(d.raw.prepare('SELECT miss_count FROM public_today_provider_misses WHERE video_id=?').get('ghostlive01').miss_count,1);
 d.close();
});

test('repeated videos.list omissions retire canonical live only after conservative threshold',async()=>{
 const d=retirementDb();seedLive(d);
 const env={TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d};
 for(let i=1;i<PROVIDER_MISS_RETIRE_THRESHOLD;i++){
  const out=await refreshKnownTodayLifecycle(env,{now:new Date(Date.parse('2026-10-18T08:30:00Z')+i*300000),fetchImpl:emptyVideos});
  assert.equal(out.retired_missing,0);
  assert.ok(d.raw.prepare('SELECT video_id FROM public_today_canonical WHERE video_id=?').get('ghostlive01'));
 }
 const out=await refreshKnownTodayLifecycle(env,{now:new Date('2026-10-18T08:45:00Z'),fetchImpl:emptyVideos});
 assert.equal(out.retired_missing,1);
 assert.equal(d.raw.prepare('SELECT video_id FROM public_today_canonical WHERE video_id=?').get('ghostlive01'),undefined);
 assert.equal(d.raw.prepare('SELECT * FROM public_today_provider_misses WHERE video_id=?').get('ghostlive01'),undefined);
 d.close();
});

test('successful provider response before threshold resets miss state and restores trusted provenance',async()=>{
 const d=retirementDb();const cid=seedLive(d);
 const env={TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d};
 await refreshKnownTodayLifecycle(env,{now:new Date('2026-10-18T08:30:00Z'),fetchImpl:emptyVideos});
 assert.equal(d.raw.prepare('SELECT miss_count FROM public_today_provider_misses WHERE video_id=?').get('ghostlive01').miss_count,1);
 const success=async()=>new Response(JSON.stringify({items:[{
  id:'ghostlive01',
  snippet:{channelId:cid,title:'Restored',channelTitle:'Channel',liveBroadcastContent:'live'},
  liveStreamingDetails:{scheduledStartTime:'2026-10-18T03:00:00Z',actualStartTime:'2026-10-18T03:01:00Z'}
 }]}),{status:200,headers:{'content-type':'application/json'}});
 const out=await refreshKnownTodayLifecycle(env,{now:new Date('2026-10-18T08:35:00Z'),fetchImpl:success});
 assert.equal(out.updated,1);
 assert.equal(d.raw.prepare('SELECT * FROM public_today_provider_misses WHERE video_id=?').get('ghostlive01'),undefined);
 const row=d.raw.prepare('SELECT lifecycle_state,source_label,actual_end,lifecycle_observed_at FROM public_today_canonical WHERE video_id=?').get('ghostlive01');
 assert.equal(row.lifecycle_state,'live');
 assert.equal(row.source_label,'YouTube liveStreamingDetails');
 assert.equal(row.actual_end,null);
 assert.equal(row.lifecycle_observed_at,'2026-10-18T08:35:00Z');
 d.close();
});


test('legacy ended omitted repeatedly by provider remains ended and is never retired',async()=>{
 const d=retirementDb();
 const cid='UC'+'E'.repeat(22);
 d.raw.prepare(`INSERT INTO public_today_canonical
  (video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,
   lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
   'endedmiss01',cid,'v85','hololive','Ended','Channel','ended',
   '2026-10-17T09:30:00Z','2026-10-17T09:30:00Z',
   '2026-10-17T08:00:00Z','2026-10-17T08:01:00Z','2026-10-17T09:00:00Z','YouTube','legacy'
  );
 const env={TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d};
 for(let i=0;i<PROVIDER_MISS_RETIRE_THRESHOLD+1;i++){
  const out=await refreshKnownTodayLifecycle(env,{
   now:new Date(Date.parse('2026-10-18T08:30:00Z')+i*300000),
   fetchImpl:emptyVideos
  });
  assert.equal(out.retired_missing,0);
  const row=d.raw.prepare('SELECT lifecycle_state,actual_end,lifecycle_observed_at FROM public_today_canonical WHERE video_id=?').get('endedmiss01');
  assert.ok(row);
  assert.equal(row.lifecycle_state,'ended');
  assert.equal(row.actual_end,'2026-10-17T09:00:00Z');
  assert.equal(row.lifecycle_observed_at,'2026-10-17T09:30:00Z');
  assert.equal(d.raw.prepare('SELECT * FROM public_today_provider_misses WHERE video_id=?').get('endedmiss01'),undefined);
 }
 d.close();
});
