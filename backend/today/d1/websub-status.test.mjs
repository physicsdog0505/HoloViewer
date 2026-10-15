import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {persistEvent,getPendingEvents} from './websub-store.mjs';
import {refreshPendingVideos} from './websub-status.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk',roster={version:'approved-v1',channels:[{id:C,group:'hololive'}]};
function fixture(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
 sqlite.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
 return {prepare(q){return {bind(...args){return {first:async()=>sqlite.prepare(q).get(...args)??null,all:async()=>({results:sqlite.prepare(q).all(...args)}),run:async()=>sqlite.prepare(q).run(...args)}}}},async batch(statements){sqlite.exec('BEGIN');try{for(const s of statements)await s.run();sqlite.exec('COMMIT')}catch(e){sqlite.exec('ROLLBACK');throw e}},sqlite};
}
test('durable event -> one videos.list -> canonical evidence -> processed',async()=>{
 const db=fixture();await persistEvent(db,{raw_sha256:'a'.repeat(64),channel_id:C,video_id:V,roster_version:roster.version});
 const first=await refreshPendingVideos({db,roster,now:new Date('2026-10-16T00:20:00Z'),fetchVideos:async ids=>{
  assert.deepEqual(ids,[V]);
  return [{id:V,snippet:{channelId:C,title:'重大告知',channelTitle:'Test',liveBroadcastContent:'upcoming'},liveStreamingDetails:{scheduledStartTime:'2026-10-16T12:00:00Z'}}];
 }});
 assert.equal(first.updated,1);assert.equal(first.quota_units,1);
 assert.equal(db.sqlite.prepare('SELECT title FROM public_today_canonical').get().title,'重大告知');
 assert.equal((await getPendingEvents(db)).length,0);
});
test('wrong channel cannot become canonical or ACK',async()=>{
 const db=fixture();await persistEvent(db,{raw_sha256:'b'.repeat(64),channel_id:C,video_id:V,roster_version:roster.version});
 const result=await refreshPendingVideos({db,roster,fetchVideos:async()=>[{id:V,snippet:{channelId:'UC'+'B'.repeat(22),title:'Wrong',liveBroadcastContent:'live'}}]});
 assert.equal(result.failed,1);
 assert.equal(db.sqlite.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,0);
 assert.equal((await getPendingEvents(db)).length,1);
});
