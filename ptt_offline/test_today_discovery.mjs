import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshTodayDiscovery} from './worker_host/today/discovery-refresh.mjs';
import {refreshPendingVideos} from './worker_host/today/websub-status.mjs';
import {mountTodayCadence} from './worker_host/today/cadence-refresh.mjs';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';

test('Today discovery is explicitly disabled by default and performs no network',async()=>{
  let calls=0;
  const out=await refreshTodayDiscovery({},{
    fetchImpl:async()=>{calls++;throw Error('must not call network')}
  });
  assert.deepEqual(out,{
    status:'disabled',feed_requests:0,channels:0,discovered:0,updated:0
  });
  assert.equal(calls,0);
});

test('combined cadence preserves existing fetch contract with discovery disabled',async()=>{
  const base={async fetch(){return new Response('same',{status:206})}};
  const worker=mountTodayCadence(base,{fetchImpl:async()=>{throw Error('network')}});
  const response=await worker.fetch(new Request('https://api.example/v1/catalog/today'),{});
  assert.equal(response.status,206);
  assert.equal(await response.text(),'same');
});

test('discovery source stays bounded and uses no search.list',async()=>{
  const source=await import('node:fs/promises').then(fs=>
    fs.readFile(new URL('./worker_host/today/discovery-refresh.mjs',import.meta.url),'utf8'));
  assert.match(source,/CHANNELS_PER_WAVE=10/);
  assert.match(source,/WAVES_PER_RUN=3/);
  assert.match(source,/One cursor write per minute at most/);
  assert.match(source,/youtube\/v3\/videos/);
  assert.doesNotMatch(source,/search\.list/);
  assert.doesNotMatch(source,/youtube\/v3\/search/);
});


const CHANNELS=Array.from({length:66},(_,i)=>({
  id:'UC'+i.toString(36).toUpperCase().padStart(22,'0'),group:'hololive'
}));
const fixedNow=new Date('2026-10-17T00:05:00Z');
const stamp=x=>x.toISOString().replace(/\\.\\d{3}Z$/,'Z');
const videoId=i=>'v'+String(i).padStart(10,'0');
const entryHash=(channel,video,version='fixture-v1')=>createHash('sha256')
  .update('feed-reconcile-v2:'+channel+':'+video+':'+version).digest('hex');

function discoveryDb({seedAll=true,omitVideoIndex=null}={}){
  const sqlite=new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
  sqlite.exec(readFileSync(new URL('./worker_host/today/discovery-only.sql',import.meta.url),'utf8'));
  sqlite.exec(readFileSync(new URL('./worker_host/today/websub-leases-only.PROPOSED.sql',import.meta.url),'utf8'));
  sqlite.prepare('INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap) VALUES(1,?,NULL,66,0,1)').run('fixture-v1');
  for(const c of CHANNELS)sqlite.prepare('INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES(?,?,?,?)')
    .run(c.id,'fixture-v1','2026-10-17T00:00:00Z',c.group);
  // The three waves selected on the first run are channel ordinals 0..29.
  for(let c=0;c<30;c++){
    const channel=CHANNELS[c];
    for(let n=0;n<2;n++){
      const index=c*2+n;
      if(omitVideoIndex===index)continue;
      if(seedAll)sqlite.prepare(`INSERT INTO public_today_websub_events
        (event_hash,channel_id,video_id,roster_version,received_at,status,attempts)
        VALUES(?,?,?,?,?,'processed',0)`).run(entryHash(channel.id,videoId(index)),channel.id,videoId(index),'fixture-v1',stamp(fixedNow));
    }
  }
  let rowWrites=0,writeStatements=0,queries=0,readQueries=0,writeQueries=0,returnedRows=0,returnedReadRows=0;
  function isRead(sql){return /^\s*(SELECT|PRAGMA|EXPLAIN)\b/i.test(sql);}
  function statement(sql,params=[]){
    return {
      bind(...args){return statement(sql,args)},
      async first(){
        queries++;if(isRead(sql))readQueries++;else writeQueries++;
        const value=sqlite.prepare(sql).get(...params)??null;
        if(value){returnedRows++;if(isRead(sql))returnedReadRows++;}
        return value;
      },
      async all(){
        queries++;if(isRead(sql))readQueries++;else writeQueries++;
        const results=sqlite.prepare(sql).all(...params);
        returnedRows+=results.length;if(isRead(sql))returnedReadRows+=results.length;
        return {results};
      },
      async run(){
        queries++;if(isRead(sql))readQueries++;else writeQueries++;
        const result=sqlite.prepare(sql).run(...params);
        const changed=Number(result.changes??0);
        if(changed>0){rowWrites+=changed;writeStatements++;}
        return {success:true,changes:changed,meta:{changes:changed}};
      }
    };
  }
  const DB={
    prepare(sql){return statement(sql)},
    async batch(statements){
      sqlite.exec('BEGIN IMMEDIATE');
      try{
        const out=[];
        for(const item of statements)out.push(await item.run());
        sqlite.exec('COMMIT');return out;
      }catch(error){sqlite.exec('ROLLBACK');throw error;}
    },
    get rowWrites(){return rowWrites},
    get writeStatements(){return writeStatements},
    get queries(){return queries},
    get readQueries(){return readQueries},
    get writeQueries(){return writeQueries},
    get returnedRows(){return returnedRows},
    get returnedReadRows(){return returnedReadRows},
    raw:sqlite
  };
  return DB;
}
function feedResponse(channelIndex){
 const items=[0,1].map(n=>({
  video:videoId(channelIndex*2+n),channel:CHANNELS[channelIndex].id
 }));
 return new Response('<feed>'+items.map(x=>`<entry><yt:videoId>${x.video}</yt:videoId><yt:channelId>${x.channel}</yt:channelId></entry>`).join('')+'</feed>',{
  status:200,headers:{'content-type':'application/atom+xml'}
 });
}
function discoveryFetch(){
 let feedCalls=0,videoCalls=0;
 const fetchImpl=async input=>{
  const url=String(input);
  if(url.includes('youtube.com/feeds/videos.xml')){
    const id=new URL(url).searchParams.get('channel_id');
    const ordinal=CHANNELS.findIndex(c=>c.id===id);
    feedCalls++;
    return feedResponse(ordinal);
  }
  if(url.includes('googleapis.com/youtube/v3/videos')){
    videoCalls++;
    const ids=new URL(url).searchParams.get('id').split(',');
    const items=ids.map(id=>{
      const index=Number(id.slice(1));
      const channelIndex=Math.floor(index/2);
      return {id,snippet:{channelId:CHANNELS[channelIndex].id,title:'Live '+id,
        channelTitle:'Channel '+channelIndex,liveBroadcastContent:'live'},
        liveStreamingDetails:{actualStartTime:'2026-10-17T00:00:00Z'}};
    });
    return new Response(JSON.stringify({items}),{status:200,headers:{'content-type':'application/json'}});
  }
  throw Error('unexpected request '+url);
 };
 return {fetchImpl,get feedCalls(){return feedCalls},get videoCalls(){return videoCalls}};
}

test('30-channel steady state: duplicate feed items create exactly one cursor row write',async()=>{
 const db=discoveryDb({seedAll:true});
 const net=discoveryFetch();
 const before=db.rowWrites;
 const out=await refreshTodayDiscovery({TODAY_DISCOVERY_ENABLED:'true',DB:db,YOUTUBE_API_KEY:'fixture-key'},
   {now:fixedNow,fetchImpl:net.fetchImpl});
 assert.equal(net.feedCalls,30);
 assert.equal(net.videoCalls,0);
 assert.equal(out.channels,30);
 assert.equal(out.feed_entries,60);
 assert.equal(out.discovered,0);
 assert.equal(db.rowWrites-before,1,'only the batched reconcile cursor advances');
 assert.equal(db.queries,65);
 assert.equal(db.readQueries,4);
 assert.equal(db.writeQueries,61);
 assert.equal(db.returnedReadRows,67,'result rows in the test double, not Cloudflare billed Rows Read');
 db.raw.close();
});

test('one new livestream candidate: bounded end-to-end budget is six changed rows',async()=>{
 const db=discoveryDb({seedAll:true,omitVideoIndex:0});
 const net=discoveryFetch();
 const before=db.rowWrites;
 const out=await refreshTodayDiscovery({TODAY_DISCOVERY_ENABLED:'true',DB:db,YOUTUBE_API_KEY:'fixture-key'},
   {now:fixedNow,fetchImpl:net.fetchImpl});
 assert.equal(net.feedCalls,30);
 assert.equal(net.videoCalls,1);
 assert.equal(out.discovered,1);
 assert.equal(out.updated,1);
 assert.equal(db.rowWrites-before,6,'queue insert + cursor + claim + evidence + canonical + finish claim');
 assert.equal(db.queries,72);
 assert.equal(db.readQueries,7);
 assert.equal(db.writeQueries,65);
 assert.equal(db.returnedReadRows,68,'result rows in the test double, not Cloudflare billed Rows Read');
 assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM public_today_canonical").get().n,1);
 db.raw.close();
});

test('full 30-channel / 60-entry minute remains bounded while discovery stays minute-level',async()=>{
 const db=discoveryDb({seedAll:false});
 const net=discoveryFetch();
 const before=db.rowWrites;
 const out=await refreshTodayDiscovery({TODAY_DISCOVERY_ENABLED:'true',DB:db,YOUTUBE_API_KEY:'fixture-key'},
   {now:fixedNow,fetchImpl:net.fetchImpl});
 assert.equal(net.feedCalls,30);
 assert.equal(out.channels,30);
 assert.equal(out.feed_entries,60);
 assert.equal(out.discovered,60);
 assert.equal(net.videoCalls,1,'pending IDs are batched into one videos.list request of at most 50');
 assert.equal(out.updated,50);
 assert.equal(db.rowWrites-before,261,'60 queue inserts + 1 cursor + 50 claims + 100 evidence/canonical + 50 finishes');
 assert.equal(db.queries,366);
 assert.equal(db.readQueries,105);
 assert.equal(db.writeQueries,261);
 assert.equal(db.returnedReadRows,117,'result rows in the test double, not Cloudflare billed Rows Read');
 assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM public_today_websub_events WHERE status='pending'").get().n,10);
 db.raw.close();
});


test('ordinary uploads and Shorts without livestream evidence never enter canonical/evidence',async()=>{
 const db=discoveryDb({seedAll:false});
 const targets=[
  {index:0,title:'ordinary recent upload'},
  {index:2,title:'vertical Shorts video'}
 ];
 for(const target of targets){
  const channel=CHANNELS[Math.floor(target.index/2)];
  const id=videoId(target.index);
  db.raw.prepare(`INSERT INTO public_today_websub_events
   (event_hash,channel_id,video_id,roster_version,received_at,status,attempts)
   VALUES(?,?,?,?,?,'pending',0)`)
   .run(entryHash(channel.id,id),channel.id,id,'fixture-v1',stamp(fixedNow));
 }
 let apiCalls=0;
 const result=await refreshPendingVideos({
  db,
  roster:{version:'fixture-v1',channels:CHANNELS.slice(0,2)},
  now:fixedNow,
  limit:2,
  fetchVideos:async ids=>{
   apiCalls++;
   return ids.map(id=>{
    const target=targets.find(t=>videoId(t.index)===id);
    const channel=CHANNELS[Math.floor(target.index/2)];
    return {id,snippet:{channelId:channel.id,title:target.title,channelTitle:'Test',liveBroadcastContent:'none'}};
   });
  }
 });
 assert.equal(apiCalls,1);
 assert.equal(result.updated,0);
 assert.equal(result.failed,0);
 assert.equal(result.ignored_non_live,2);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_canonical').get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n,0);
 assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM public_today_websub_events WHERE status='processed'").get().n,2);
 assert.equal(db.rowWrites,4,'two queue claims and two final acknowledgements only');
 db.raw.close();
});


test('WebSub primary mode only suppresses Atom after complete active lease coverage',async()=>{
 let calls=0;
 const db=discoveryDb({seedAll:true});
 const baseEnv={
  TODAY_DISCOVERY_ENABLED:'true',TODAY_WEBSUB_PRIMARY_ENABLED:'true',TODAY_WEBSUB_RECEIVER_ENABLED:'true',
  TODAY_WEBSUB_PROCESS_ENABLED:'true',TODAY_WEBSUB_RENEW_ENABLED:'true',
  TODAY_WEBSUB_CALLBACK_URL:'https://api.example/internal/today/websub',
  TODAY_WEBSUB_SECRET:'fixture-secret-012345678901234567890123',
  DB:db,YOUTUBE_API_KEY:'fixture'
 };
 const incomplete=await refreshTodayDiscovery(baseEnv,{now:fixedNow,fetchImpl:async()=>{calls++;throw Error('no polling')}});
 assert.equal(incomplete.status,'blocked_websub_primary_incomplete_coverage');
 assert.equal(incomplete.coverage.expected_channels,66);
 assert.equal(incomplete.coverage.active_leases,0);
 for(const channel of CHANNELS){
  db.raw.prepare(`INSERT INTO public_today_websub_leases
   (channel_id,roster_version,topic,requested_mode,state,requested_at,verified_at,expires_at,lease_seconds,last_error)
   VALUES(?,?,?,'subscribe','active',?,?,?,?,NULL)`)
   .run(channel.id,'fixture-v1','https://www.youtube.com/xml/feeds/videos.xml?channel_id='+channel.id,
     '2026-10-16T23:00:00Z','2026-10-16T23:01:00Z','2026-10-22T23:01:00Z',432000);
 }
 const ready=await refreshTodayDiscovery(baseEnv,{now:fixedNow,fetchImpl:async()=>{calls++;throw Error('no polling')}});
 assert.equal(ready.status,'disabled_websub_primary');
 assert.equal(ready.coverage.status,'PASS');
 assert.equal(ready.coverage.active_leases,66);
 db.raw.prepare('UPDATE public_today_websub_leases SET expires_at=? WHERE channel_id=?')
  .run('2026-10-16T23:00:00Z',CHANNELS[0].id);
 const expired=await refreshTodayDiscovery(baseEnv,{now:fixedNow,fetchImpl:async()=>{calls++;throw Error('no polling')}});
 assert.equal(expired.status,'blocked_websub_primary_incomplete_coverage');
 assert.equal(expired.coverage.active_leases,65);
 assert.equal(calls,0);
 db.raw.close();
});
