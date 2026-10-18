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
