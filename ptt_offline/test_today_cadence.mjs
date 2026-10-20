import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshKnownTodayLifecycle,mountTodayCadence,shouldRunLifecycleRefresh,PROVIDER_MISS_RETIRE_THRESHOLD,LIFECYCLE_CANDIDATE_SQL} from './worker_host/today/cadence-refresh.mjs';
import {readFileSync} from 'node:fs';
import {readToday} from './worker_host/today/store.mjs';
import {DatabaseSync} from 'node:sqlite';

function fakeDb(rows){
  return {
    writes:[],
    prepare(sql){
      const self=this;
      const selected=/FROM\s+public_today_canonical/i.test(sql)?rows:[];
      return {
        bind(...args){
          return {
            all:async()=>({results:selected}),
            first:async()=>null,
            run:async()=>{self.writes.push({sql,args});return {success:true}}
          };
        },
        all:async()=>({results:selected}),
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


function instrumentDb(base){
 let readQueries=0,providerMissDeletes=0,heartbeatUpdates=0,batches=0;
 return {
  raw:base.raw,
  prepare(sql){
   if(/^\s*(?:SELECT|WITH)\b/i.test(sql))readQueries++;
   if(/^\s*DELETE\s+FROM\s+public_today_provider_misses\b/i.test(sql))providerMissDeletes++;
   if(/^\s*UPDATE\s+public_today_canonical\b/i.test(sql)&&/checked_at=\?/i.test(sql))heartbeatUpdates++;
   return base.prepare(sql);
  },
  async batch(statements){batches++;return base.batch(statements)},
  close(){base.close()},
  metrics:()=>({readQueries,providerMissDeletes,heartbeatUpdates,batches})
 };
}
function seedSteadyLive(db,count=50){
 const cid='UC'+'S'.repeat(22);
 for(let i=0;i<count;i++){
  const id='v'+String(i).padStart(10,'0');
  db.raw.prepare(`INSERT INTO public_today_canonical
   (video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,
    lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum)
   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
    id,cid,'v85','hololive','Title '+i,'Channel','live',
    '2026-10-18T08:00:00Z','2026-10-18T08:00:00Z',
    '2026-10-18T07:00:00Z','2026-10-18T07:01:00Z',null,
    'YouTube liveStreamingDetails','steady'
   );
 }
 return cid;
}
function steadyProvider(cid,count=50,{changedIndex=-1,endedIndex=-1}={}){
 const items=[];
 for(let i=0;i<count;i++){
  const id='v'+String(i).padStart(10,'0');
  const ended=i===endedIndex;
  items.push({
   id,
   snippet:{
    channelId:cid,
    title:i===changedIndex?'Changed title':'Title '+i,
    channelTitle:'Channel',
    liveBroadcastContent:ended?'none':'live'
   },
   liveStreamingDetails:{
    scheduledStartTime:'2026-10-18T07:00:00Z',
    actualStartTime:'2026-10-18T07:01:00Z',
    ...(ended?{actualEndTime:'2026-10-18T08:59:00Z'}:{})
   }
  });
 }
 return async()=>new Response(JSON.stringify({items}),{status:200,headers:{'content-type':'application/json'}});
}

test('cadence selector keeps legacy eligibility/order and uses proposed access-path indexes',async()=>{
 const db=retirementDb();
 const cid='UC'+'Q'.repeat(22);
 const insert=db.raw.prepare(`INSERT INTO public_today_canonical
  (video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,
   lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum)
  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)`);
 for(let i=0;i<80;i++){
  const id='a'+String(i).padStart(10,'0');
  const checked=new Date(Date.parse('2026-10-18T08:00:00Z')+i*60000).toISOString().replace(/\.000Z$/,'Z');
  insert.run(id,cid,'v85','hololive','A'+i,'Channel','upcoming',
   '2026-10-18T08:00:00Z',checked,'2026-10-18T10:00:00Z',null,null,'YouTube liveStreamingDetails','a');
 }
 for(let i=0;i<80;i++){
  const id='e'+String(i).padStart(10,'0');
  const checked=new Date(Date.parse('2026-10-18T08:00:30Z')+i*60000).toISOString().replace(/\.000Z$/,'Z');
  insert.run(id,cid,'v85','hololive','E'+i,'Channel','ended',
   '2026-10-18T08:00:00Z',checked,'2026-10-17T07:00:00Z','2026-10-17T07:01:00Z','2026-10-17T08:00:00Z','YouTube','e');
 }
 for(let i=0;i<120;i++){
  const id='z'+String(i).padStart(10,'0');
  const checked=new Date(Date.parse('2026-10-10T00:00:00Z')+i*60000).toISOString().replace(/\.000Z$/,'Z');
  insert.run(id,cid,'v85','hololive','Z'+i,'Channel','ended',
   '2026-10-10T00:00:00Z',checked,'2026-10-10T01:00:00Z','2026-10-10T01:01:00Z','2026-10-10T02:00:00Z','YouTube liveStreamingDetails','z');
 }
 const cutoff='2026-10-11T16:00:00Z';
 const legacy=db.raw.prepare(`SELECT video_id FROM public_today_canonical
  WHERE lifecycle_state!='ended'
     OR (lifecycle_state='ended' AND actual_end>=?
         AND (source_label!=? OR actual_start IS NULL OR actual_end IS NULL))
  ORDER BY checked_at ASC,video_id ASC LIMIT 50`)
  .all(cutoff,'YouTube liveStreamingDetails').map(r=>r.video_id);
 let requested=[];
 const fetchImpl=async url=>{
  requested=new URL(url).searchParams.get('id').split(',');
  return new Response(JSON.stringify({items:[]}),{status:200,headers:{'content-type':'application/json'}});
 };
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:db},
  {now:new Date('2026-10-18T09:00:00Z'),fetchImpl}
 );
 assert.equal(out.selected,50);
 assert.deepEqual(requested,legacy);
 const plan=db.raw.prepare('EXPLAIN QUERY PLAN '+LIFECYCLE_CANDIDATE_SQL)
  .all(50,cutoff,'YouTube liveStreamingDetails',50,50)
  .map(r=>String(r.detail));
 assert.ok(plan.some(x=>x.includes('public_today_canonical_cadence_active')));
 assert.ok(plan.some(x=>x.includes('public_today_canonical_cadence_ended_reverify')));
 assert.ok(plan.some(x=>x.includes('public_today_websub_processed_video')));
 db.close();
});

test('steady-state 50-video cadence uses two bounded D1 reads and no evidence churn',async()=>{
 const raw=retirementDb();const cid=seedSteadyLive(raw,50);const d=instrumentDb(raw);
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d},
  {now:new Date('2026-10-18T09:00:00Z'),fetchImpl:steadyProvider(cid,50)}
 );
 assert.equal(out.selected,50);
 assert.equal(out.updated,0);
 assert.equal(out.unchanged,50);
 assert.equal(out.read_queries,2);
 assert.equal(d.metrics().readQueries,2);
 assert.equal(d.metrics().providerMissDeletes,0);
 assert.equal(d.metrics().heartbeatUpdates,1);
 assert.equal(raw.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,0);
 const row=raw.raw.prepare('SELECT lifecycle_observed_at,checked_at FROM public_today_canonical WHERE video_id=?').get('v0000000000');
 assert.equal(row.lifecycle_observed_at,'2026-10-18T08:00:00Z');
 assert.equal(row.checked_at,'2026-10-18T09:00:00Z');
 assert.equal(raw.raw.prepare('SELECT source_checksum FROM public_today_canonical WHERE video_id=?').get('v0000000000').source_checksum,'steady');
 raw.close();
});


test('unchanged 50-video heartbeat rotates fairly without changing evidence provenance',async()=>{
 const raw=retirementDb();const cid=seedSteadyLive(raw,50);const d=instrumentDb(raw);
 const env={TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d};
 const first=await refreshKnownTodayLifecycle(env,{
  now:new Date('2026-10-18T09:00:00Z'),fetchImpl:steadyProvider(cid,50),limit:25
 });
 assert.equal(first.selected,25);
 assert.equal(first.updated,0);
 assert.equal(d.metrics().readQueries,2);
 const afterFirst=raw.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical WHERE checked_at='2026-10-18T09:00:00Z'").get().n;
 assert.equal(afterFirst,25);
 const second=await refreshKnownTodayLifecycle(env,{
  now:new Date('2026-10-18T09:05:00Z'),fetchImpl:steadyProvider(cid,50),limit:25
 });
 assert.equal(second.selected,25);
 assert.equal(second.updated,0);
 assert.equal(d.metrics().readQueries,4);
 const checked=raw.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical WHERE checked_at='2026-10-18T09:05:00Z'").get().n;
 assert.equal(checked,25);
 assert.equal(raw.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical WHERE checked_at='2026-10-18T09:00:00Z'").get().n,25);
 assert.equal(raw.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical WHERE checked_at='2026-10-18T08:00:00Z'").get().n,0);
 const untouched=raw.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical WHERE lifecycle_observed_at!='2026-10-18T08:00:00Z' OR source_checksum!='steady'").get().n;
 assert.equal(untouched,0);
 assert.equal(raw.raw.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n,0);
 raw.close();
});


test('consumer live freshness follows checked_at, not evidence observation time',async()=>{
 const db=retirementDb();const cid=seedSteadyLive(db,1);
 db.raw.prepare(`INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group)
  VALUES(?,?,?,?)`).run(cid,'v85','2026-10-18T07:00:00Z','hololive');
 db.raw.prepare(`INSERT INTO public_today_catalog_meta
  (singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap,checkpoint)
  VALUES(1,?,?,?,?,?,?)`).run('v85','2026-10-18T09:00:00Z',1,1,0,'test');
 db.raw.prepare('UPDATE public_today_canonical SET checked_at=? WHERE video_id=?')
  .run('2026-10-18T09:00:00Z','v0000000000');
 const out=await readToday(db,{day:'2026-10-18',now:new Date('2026-10-18T09:10:00Z')});
 assert.equal(out.streams.length,1);
 assert.equal(out.streams[0].stale,false);
 assert.equal(out.streams[0].observed_at,'2026-10-18T08:00:00Z');
 db.raw.prepare('UPDATE public_today_canonical SET checked_at=? WHERE video_id=?')
  .run('2026-10-18T08:00:00Z','v0000000000');
 const expired=await readToday(db,{day:'2026-10-18',now:new Date('2026-10-18T09:10:00Z')});
 assert.equal(expired.streams[0].stale,true);
 db.close();
});

test('provider miss cleanup is one bounded delete only when preloaded miss rows exist',async()=>{
 const raw=retirementDb();const cid=seedSteadyLive(raw,10);
 for(let i=0;i<5;i++){
  raw.raw.prepare('INSERT INTO public_today_provider_misses(video_id,first_missing_at,last_missing_at,miss_count) VALUES(?,?,?,?)')
   .run('v'+String(i).padStart(10,'0'),'2026-10-18T08:00:00Z','2026-10-18T08:00:00Z',1);
 }
 const d=instrumentDb(raw);
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d},
  {now:new Date('2026-10-18T09:00:00Z'),fetchImpl:steadyProvider(cid,10),limit:10}
 );
 assert.equal(out.read_queries,2);
 assert.equal(d.metrics().providerMissDeletes,1);
 assert.equal(raw.raw.prepare('SELECT COUNT(*) n FROM public_today_provider_misses').get().n,0);
 raw.close();
});

test('one changed lifecycle fact adds one bounded evidence preload, not per-video reads',async()=>{
 const raw=retirementDb();const cid=seedSteadyLive(raw,50);const d=instrumentDb(raw);
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d},
  {now:new Date('2026-10-18T09:00:00Z'),fetchImpl:steadyProvider(cid,50,{changedIndex:17})}
 );
 assert.equal(out.updated,1);
 assert.equal(out.unchanged,49);
 assert.equal(out.read_queries,3);
 assert.equal(d.metrics().readQueries,3);
 assert.equal(raw.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,1);
 assert.equal(raw.raw.prepare('SELECT title FROM public_today_canonical WHERE video_id=?').get('v0000000017').title,'Changed title');
 raw.close();
});

test('ended transition adds one bounded catalog-avatar preload only once',async()=>{
 const raw=retirementDb();const cid=seedSteadyLive(raw,50);
 raw.raw.prepare('INSERT INTO public_catalog(video_id,channel_id,avatar_url,actual_start,scheduled_start) VALUES(?,?,?,?,?)')
  .run('catalog0001',cid,'https://yt3.ggpht.com/avatar','2026-10-18T06:00:00Z','2026-10-18T06:00:00Z');
 const d=instrumentDb(raw);
 const out=await refreshKnownTodayLifecycle(
  {TODAY_CADENCE_ENABLED:'true',YOUTUBE_API_KEY:'secret',DB:d},
  {now:new Date('2026-10-18T09:00:00Z'),fetchImpl:steadyProvider(cid,50,{endedIndex:3})}
 );
 assert.equal(out.updated,1);
 assert.equal(out.read_queries,4);
 assert.equal(d.metrics().readQueries,4);
 const ended=raw.raw.prepare('SELECT lifecycle_state,actual_end FROM public_today_canonical WHERE video_id=?').get('v0000000003');
 assert.equal(ended.lifecycle_state,'ended');
 assert.equal(ended.actual_end,'2026-10-18T08:59:00Z');
 raw.close();
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
      if(sql.includes('FROM public_today_canonical')&&sql.includes('ORDER BY checked_at')){
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
  assert.equal(selectArgs[2],'YouTube liveStreamingDetails');
  assert.equal(out.updated,1);
});


function retirementDb(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0003_provider_missing_retirement.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./worker_host/today/0005_today_cadence_access_path.PROPOSED.sql',import.meta.url),'utf8'));
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
