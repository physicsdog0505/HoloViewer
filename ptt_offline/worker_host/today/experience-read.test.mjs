import test from 'node:test';
import assert from 'node:assert/strict';
import {detectCollabCandidates} from './experience-read.mjs';

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
