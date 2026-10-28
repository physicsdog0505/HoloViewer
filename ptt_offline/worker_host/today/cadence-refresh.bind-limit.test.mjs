import test from 'node:test';
import assert from 'node:assert/strict';

import {
  UNCHANGED_VIEWER_UPDATE_CHUNK,
  chunkValues
} from './cadence-refresh.mjs';

test('concurrent viewer unchanged-row updates stay below D1 SQLite variable limit',()=>{
  const ids=Array.from({length:50},(_,i)=>`video${String(i).padStart(6,'0')}`);
  const chunks=chunkValues(ids);

  assert.equal(UNCHANGED_VIEWER_UPDATE_CHUNK,30);
  assert.deepEqual(chunks.map(chunk=>chunk.length),[30,20]);

  for(const chunk of chunks){
    // checked_at (1) + CASE(video_id,value) (2 per row) + WHERE IN (1 per row)
    const bindCount=1+(2*chunk.length)+chunk.length;
    assert.ok(bindCount<=91,`bind count ${bindCount} exceeds expected safe bound`);
  }
});

test('chunkValues preserves order and covers each candidate exactly once',()=>{
  const ids=Array.from({length:50},(_,i)=>String(i));
  const chunks=chunkValues(ids);
  assert.deepEqual(chunks.flat(),ids);
});
