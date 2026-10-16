import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshTodayDiscovery} from './worker_host/today/discovery-refresh.mjs';
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
  let rowWrites=0,writeStatements=0;
  function statement(sql,params=[]){
    return {
      bind(...args){return statement(sql,args)},
      async first(){return sqlite.prepare(sql).get(...params)??null},
      async all(){return {results:sqlite.prepare(sql).all(...params)}},
      async run(){
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
 assert.equal(db.raw.prepare("SELECT COUNT(*) AS n FROM public_today_websub_events WHERE status='pending'").get().n,10);
 db.raw.close();
});
