import test from 'node:test';
import assert from 'node:assert/strict';
// #45 integration gate: run Today membership + route-mount regressions in the existing PTT workflow.
import './store.test.mjs';
import './api-shell.test.mjs';
import {detectCollabCandidates,handleExperienceRead} from './experience-read.mjs';

const C1='UC'+'A'.repeat(22);
const C2='UC'+'B'.repeat(22);
const C3='UC'+'C'.repeat(22);

test('explicit HoloARK candidates preserve accepted 06:00 Taipei event-day grouping',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'【ホロARK】day',lifecycle_state:'live',actual_start:'2026-10-15T16:30:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,channel_name:'B',title:'【ホロARK】day',lifecycle_state:'live',actual_start:'2026-10-15T17:10:00Z'},
  ]);
  assert.equal(events.length,1);
  assert.equal(events[0].candidate,true);
  assert.equal(events[0].event_id,'ark:2026-10-15');
  assert.deepEqual(events[0].streams.map(x=>x.video_id),['aaaaaaaaaaa','bbbbbbbbbbb']);
  assert.equal(events[0].sync.available,false);
});

test('generic shared-topic requires distinct channels and starts within 20 minutes',()=>{
  const rows=[
    {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'Misty Mountain Gaming Collab Cooking',lifecycle_state:'upcoming',scheduled_start:'2026-10-16T10:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,channel_name:'B',title:'Misty Mountain Gaming Collab Dinner',lifecycle_state:'upcoming',scheduled_start:'2026-10-16T10:15:00Z'},
    {video_id:'ccccccccccc',channel_id:C3,channel_name:'C',title:'Misty Mountain Gaming Collab Later',lifecycle_state:'upcoming',scheduled_start:'2026-10-16T11:00:00Z'},
  ];
  const events=detectCollabCandidates(rows);
  assert.equal(events.length,1);
  assert.equal(events[0].event_key,'shared-topic');
  assert.deepEqual(events[0].streams.map(x=>x.video_id),['aaaaaaaaaaa','bbbbbbbbbbb']);
});

test('verified ended POVs expose relative sync offsets only with actual bounds',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'【ホロARK】day',lifecycle_state:'ended',actual_start:'2026-10-15T15:00:00Z',actual_end:'2026-10-15T17:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,channel_name:'B',title:'【ホロARK】day',lifecycle_state:'ended',actual_start:'2026-10-15T15:05:00Z',actual_end:'2026-10-15T17:05:00Z'},
  ]);
  assert.equal(events.length,1);
  assert.equal(events[0].sync.available,true);
  assert.equal(events[0].sync.basis,'youtube_actual_start');
  assert.equal(events[0].streams[0].sync_offset_ms,0);
  assert.equal(events[0].streams[1].sync_offset_ms,300000);
});

test('single stream or same-channel rows never become a collab event',()=>{
  assert.deepEqual(detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'Misty Mountain Gaming Collab',lifecycle_state:'live',actual_start:'2026-10-16T10:00:00Z'}
  ]),[]);
  assert.deepEqual(detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,channel_name:'A',title:'Misty Mountain Gaming Collab',lifecycle_state:'live',actual_start:'2026-10-16T10:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C1,channel_name:'A',title:'Misty Mountain Gaming Collab',lifecycle_state:'live',actual_start:'2026-10-16T10:05:00Z'}
  ]),[]);
});


test('ingestion provenance never creates a shared-topic candidate',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,title:'Japanese Ramen Simulator',
      source_label:'YouTube videos.list verified bootstrap',lifecycle_state:'live',
      actual_start:'2026-10-16T10:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,title:'APEX battle royale',
      source_label:'YouTube videos.list verified bootstrap',lifecycle_state:'live',
      actual_start:'2026-10-16T10:05:00Z'},
  ]);
  assert.deepEqual(events,[]);
});

test('real title overlap still yields candidate even with provenance present',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,title:'【#インボキア】こわこわなボドゲ',
      source_label:'YouTube videos.list verified bootstrap',lifecycle_state:'live',
      actual_start:'2026-10-16T10:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,title:'【#インボキア】呪いのダイスゲーム',
      source_label:'YouTube videos.list verified bootstrap',lifecycle_state:'live',
      actual_start:'2026-10-16T10:05:00Z'},
  ]);
  assert.equal(events.length,1);
  assert.equal(events[0].confidence,'shared-topic');
  assert.deepEqual(events[0].streams.map(s=>s.video_id),['aaaaaaaaaaa','bbbbbbbbbbb']);
  assert.equal(events[0].candidate,true);
  assert.equal(events[0].sync.available,false);
});


test('explicit HoloARK start_label fallback attaches to the unique accepted event day',()=>{
  const events=detectCollabCandidates([
    {video_id:'ddddddddddd',channel_id:C1,channel_name:'A',title:'【ホロARK】day',lifecycle_state:'live',
      actual_start:'2026-10-15T16:30:00Z',start_label:'10/16 00:30'},
    {video_id:'eeeeeeeeeee',channel_id:C2,channel_name:'B',title:'【ホロARK】day',lifecycle_state:'upcoming',
      start_label:'10/16 01:10'},
  ]);
  assert.equal(events.length,1);
  assert.equal(events[0].event_id,'ark:2026-10-15');
  assert.deepEqual(events[0].streams.map(x=>x.video_id),['ddddddddddd','eeeeeeeeeee']);
});

test('shared-topic event id matches accepted 4174 min-video-id contract',()=>{
  const events=detectCollabCandidates([
    {video_id:'zzzzzzzzzzz',channel_id:C1,title:'Misty Mountain Gaming',lifecycle_state:'live',actual_start:'2026-10-16T10:00:00Z'},
    {video_id:'aaaaaaaaaaa',channel_id:C2,title:'Misty Mountain Dinner',lifecycle_state:'live',actual_start:'2026-10-16T10:05:00Z'},
  ]);
  assert.equal(events.length,1);
  assert.equal(events[0].event_id,'shared-topic:aaaaaaaaaaa');
});

test('known production provenance false positives remain rejected on matched-time inputs',()=>{
  const provenance='YouTube videos.list verified bootstrap';
  const cases=[
    ['ACE COMBAT 7 SKIES UNKNOWN','無職転生 Watchalong'],
    ['Poly Bridge 3','ホロドリ fishing challenge'],
    ['Poly Bridge 3','Gundam Watchalong'],
    ['Holodori fishing challenge','Gundam Watchalong'],
  ];
  for(const [leftTitle,rightTitle] of cases){
    const events=detectCollabCandidates([
      {video_id:'aaaaaaaaaaa',channel_id:C1,title:leftTitle,source_label:provenance,lifecycle_state:'live',actual_start:'2026-10-16T10:00:00Z'},
      {video_id:'bbbbbbbbbbb',channel_id:C2,title:rightTitle,source_label:provenance,lifecycle_state:'live',actual_start:'2026-10-16T10:05:00Z'},
    ]);
    assert.deepEqual(events,[],leftTitle+' vs '+rightTitle);
  }
});

test('shared-topic boundary is inclusive at 20 minutes and rejects beyond it',()=>{
  const base={channel_name:'A',title:'Misty Mountain Gaming',lifecycle_state:'upcoming'};
  const at20=detectCollabCandidates([
    {...base,video_id:'aaaaaaaaaaa',channel_id:C1,scheduled_start:'2026-10-16T10:00:00Z'},
    {...base,video_id:'bbbbbbbbbbb',channel_id:C2,scheduled_start:'2026-10-16T10:20:00Z'},
  ]);
  assert.equal(at20.length,1);
  const beyond=detectCollabCandidates([
    {...base,video_id:'aaaaaaaaaaa',channel_id:C1,scheduled_start:'2026-10-16T10:00:00Z'},
    {...base,video_id:'bbbbbbbbbbb',channel_id:C2,scheduled_start:'2026-10-16T10:20:01Z'},
  ]);
  assert.deepEqual(beyond,[]);
});

test('shared-topic pairs merge transitively without requiring every pair to overlap',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,title:'AlphaQuest SharedOne',lifecycle_state:'live',actual_start:'2026-10-16T10:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,title:'AlphaQuest BetaQuest',lifecycle_state:'live',actual_start:'2026-10-16T10:05:00Z'},
    {video_id:'ccccccccccc',channel_id:C3,title:'BetaQuest FinalStage',lifecycle_state:'live',actual_start:'2026-10-16T10:10:00Z'},
  ]);
  assert.equal(events.length,1);
  assert.deepEqual(events[0].streams.map(x=>x.video_id),['aaaaaaaaaaa','bbbbbbbbbbb','ccccccccccc']);
  assert.equal(events[0].candidate,true);
  assert.equal(events[0].sync.available,false);
});

test('provenance-only overlap stays rejected even when all streams are ended and sync-capable',()=>{
  const events=detectCollabCandidates([
    {video_id:'aaaaaaaaaaa',channel_id:C1,title:'ACE COMBAT 7',source_label:'YouTube videos.list verified bootstrap',
      lifecycle_state:'ended',actual_start:'2026-10-16T10:00:00Z',actual_end:'2026-10-16T11:00:00Z'},
    {video_id:'bbbbbbbbbbb',channel_id:C2,title:'Mushoku Tensei Watchalong',source_label:'YouTube videos.list verified bootstrap',
      lifecycle_state:'ended',actual_start:'2026-10-16T10:05:00Z',actual_end:'2026-10-16T11:05:00Z'},
  ]);
  assert.deepEqual(events,[]);
});


function historyVideoDb(rows){
  const byId=new Map(rows.map(row=>[row.video_id,row]));
  return {
    prepare(sql){
      assert.match(sql,/FROM public_history WHERE video_id=\?/);
      return {
        bind(videoId){
          return {async first(){return byId.get(videoId)??null;}};
        }
      };
    }
  };
}

test('history video metadata lookup returns exact verified YouTube actual window for known regressions',async()=>{
  const source_revision='stream-catalog-v1:youtube-liveStreamingDetails';
  const rows=[
    {video_id:'62AgiXDP3tU',actual_start:'2026-10-05T12:01:05Z',actual_end:'2026-10-05T12:54:31Z',source_revision},
    {video_id:'FVpLKAiHYFA',actual_start:'2026-10-09T10:00:05Z',actual_end:'2026-10-09T11:29:38Z',source_revision},
    {video_id:'pwJeqkeHtPM',actual_start:'2026-10-04T15:29:35Z',actual_end:'2026-10-05T00:35:17Z',source_revision},
  ];
  const env={DB:historyVideoDb(rows)};
  for(const expected of rows){
    const response=await handleExperienceRead(
      new Request('https://example.test/v1/history/videos/'+expected.video_id),env
    );
    assert.equal(response.status,200);
    const body=await response.json();
    assert.deepEqual(body,{
      schema_version:'public-history-video-v1',
      video_id:expected.video_id,
      actual_start:expected.actual_start,
      actual_end:expected.actual_end,
      anchor_source:'youtube-liveStreamingDetails-actualStartTime'
    });
  }
});

test('history video metadata lookup fails closed on missing provenance or actual bounds',async()=>{
  const cases=[
    {video_id:'aaaaaaaaaaa',actual_start:'2026-10-05T12:01:05Z',actual_end:'2026-10-05T12:54:31Z',source_revision:'legacy-import'},
    {video_id:'bbbbbbbbbbb',actual_start:null,actual_end:'2026-10-05T12:54:31Z',source_revision:'stream-catalog-v1:youtube-liveStreamingDetails',scheduled_start:'2026-10-05T12:00:00Z'},
    {video_id:'ccccccccccc',actual_start:'2026-10-05T12:54:31Z',actual_end:'2026-10-05T12:01:05Z',source_revision:'stream-catalog-v1:youtube-liveStreamingDetails'},
  ];
  const env={DB:historyVideoDb(cases)};
  for(const row of cases){
    const response=await handleExperienceRead(new Request('https://example.test/v1/history/videos/'+row.video_id),env);
    assert.equal(response.status,404);
    assert.deepEqual(await response.json(),{error:'not_found',verified:false});
  }
});

test('history video metadata lookup is exact video id only and does not guess',async()=>{
  const env={DB:historyVideoDb([])};
  const missing=await handleExperienceRead(new Request('https://example.test/v1/history/videos/8pF4qHcshDc'),env);
  assert.equal(missing.status,404);
  assert.deepEqual(await missing.json(),{error:'not_found',verified:false});
  const invalid=await handleExperienceRead(new Request('https://example.test/v1/history/videos/not-a-video-id'),env);
  assert.equal(invalid.status,400);
  assert.deepEqual(await invalid.json(),{error:'invalid_video_id'});
});


function canonicalProjectionDb(){
 const payload={
  event_id:'holoserver-hide-and-seek:5680e7ec7c29074a',
  event_key:'holoserver-hide-and-seek',
  label:'#ホロ鯖かくれんぼ',
  confidence:'explicit-event',
  event_date:'2026-10-22',
  event_start_at:'2026-10-22T10:00:00+00:00',
  event_end_at:'2026-10-22T11:15:00+00:00',
  participant_count:5,
  pov_count:5,
  streams:[
   {video_id:'89kUA14-sCc',channel_id:C1,channel_title:'水宮枢',lifecycle_state:'ended',actual_start:'2026-10-22T10:15:00+00:00',actual_end:'2026-10-22T11:15:00+00:00'},
   {video_id:'Uy-KPheZe7U',channel_id:C2,channel_title:'宙科そぴあ',lifecycle_state:'ended',actual_start:'2026-10-22T10:15:00+00:00',actual_end:'2026-10-22T11:05:00+00:00'},
   {video_id:'bB5HkHSQWkI',channel_id:C3,channel_title:'熱千めら',lifecycle_state:'ended',actual_start:'2026-10-22T10:00:00+00:00',actual_end:'2026-10-22T11:00:00+00:00'},
   {video_id:'ihKbojqvGAk',channel_id:'UC'+'D'.repeat(22),channel_title:'百灯キョーコ',lifecycle_state:'ended',actual_start:'2026-10-22T10:05:00+00:00',actual_end:'2026-10-22T11:00:00+00:00'},
   {video_id:'mOeNtn8bn3A',channel_id:'UC'+'E'.repeat(22),channel_title:'鈴鳴つづり',lifecycle_state:'ended',actual_start:'2026-10-22T10:10:00+00:00',actual_end:'2026-10-22T11:00:00+00:00'}
  ]
 };
 const row={
  event_id:payload.event_id,event_key:payload.event_key,label:payload.label,
  confidence:payload.confidence,review_status:'approved',
  payload_json:JSON.stringify(payload),source_revision:'collab-event-v1:owner-effective:test',
  published_at:'2026-10-22T17:00:00Z'
 };
 return {
  prepare(sql){
   if(sql.includes('FROM public_collab_projection_meta')){
    return {async first(){return {source_revision:row.source_revision,published_at:row.published_at,source_event_count:1,effective_event_count:1};}};
   }
   if(sql.includes('FROM public_collab_events')&&sql.includes('live_scope=1')){
    return {async all(){return {results:[row]};}};
   }
   if(sql.includes('FROM public_collab_events')&&sql.includes('event_date=?')){
    return {bind(day){
      return {
       async all(){assert.equal(day,'2026-10-22');return {results:[row]};},
       async first(){assert.equal(day,row.event_id);return null;}
      };
    }};
   }
   if(sql.includes('FROM public_collab_events')&&sql.includes('event_id=?')){
    return {bind(eventId,day){
      return {async first(){
       if(eventId!==row.event_id)return null;
       if(day!=null&&day!=='2026-10-22')return null;
       return row;
      }};
    }};
   }
   throw Error('unexpected SQL: '+sql);
  }
 };
}

test('Public collab live reads canonical projection and preserves canonical event id',async()=>{
 const response=await handleExperienceRead(
  new Request('https://example.test/v1/collab/live'),
  {DB:canonicalProjectionDb()},
  new Date('2026-10-23T00:30:00+08:00')
 );
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.completeness.projection,'canonical');
 assert.equal(body.events.length,1);
 assert.equal(body.events[0].event_id,'holoserver-hide-and-seek:5680e7ec7c29074a');
 assert.equal(body.events[0].event_key,'holoserver-hide-and-seek');
 assert.equal(body.events[0].review_status,'approved');
 assert.equal(body.events[0].streams.length,5);
 assert.equal(body.events[0].streams.some(x=>x.video_id==='89kUA14-sCc'),true);
});

test('Public collab history reads canonical projection instead of recomputing shared-topic',async()=>{
 const response=await handleExperienceRead(
  new Request('https://example.test/v1/collab/history?day=2026-10-22&limit=50&offset=0'),
  {DB:canonicalProjectionDb()}
 );
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.events[0].event_id,'holoserver-hide-and-seek:5680e7ec7c29074a');
 assert.notEqual(body.events[0].event_key,'shared-topic');
});

test('Public collab detail resolves the exact canonical event id',async()=>{
 const id='holoserver-hide-and-seek:5680e7ec7c29074a';
 const response=await handleExperienceRead(
  new Request('https://example.test/v1/collab/events/'+id),
  {DB:canonicalProjectionDb()}
 );
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.event.event_id,id);
 assert.equal(body.event.source_revision,'collab-event-v1:owner-effective:test');
});

test('Public collab routes fail closed when canonical projection is unavailable',async()=>{
 const db={prepare(){return {async first(){return null;}};}};
 const response=await handleExperienceRead(new Request('https://example.test/v1/collab/live'),{DB:db});
 assert.equal(response.status,503);
 assert.deepEqual(await response.json(),{error:'experience_projection_unavailable'});
});
