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
