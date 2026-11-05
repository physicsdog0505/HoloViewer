import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshKnownTodayLifecycle,mountTodayCadence,shouldRunLifecycleRefresh} from './worker_host/today/cadence-refresh.mjs';

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
      assert.match(url,/youtubeapis\.com\/youtube\/v3\/videos/);
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
