import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {persistEvent,getPendingEvents,markEventProcessed,markEventFailed} from './websub-store.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk',H='a'.repeat(64);
const db=new DatabaseSync(':memory:');db.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
function adapter(){return {prepare(q){return {bind(...args){return {run:async()=>db.prepare(q).run(...args),all:async()=>({results:db.prepare(q).all(...args)})}}}}};}
test('WebSub durable queue is idempotent, bounded, ACK-eligible and processable',async()=>{
 const d=adapter(),event={raw_sha256:H,channel_id:C,video_id:V,roster_version:'owner-v1'};
 await persistEvent(d,event);await persistEvent(d,event);
 assert.equal(db.prepare('SELECT COUNT(*) n FROM public_today_websub_events').get().n,1);
 assert.equal((await getPendingEvents(d)).length,1);
 await markEventProcessed(d,H);
 assert.equal((await getPendingEvents(d)).length,0);
});
test('failed event gets finite retry ceiling and no silent disappearance',async()=>{
 const d=adapter(),event={raw_sha256:'b'.repeat(64),channel_id:C,video_id:V,roster_version:'owner-v1'};
 await persistEvent(d,event);
 for(let i=0;i<5;i++)await markEventFailed(d,event.raw_sha256,'provider unavailable');
 assert.equal(db.prepare('SELECT status FROM public_today_websub_events WHERE event_hash=?').get(event.raw_sha256).status,'failed');
 assert.equal((await getPendingEvents(d)).length,0);
 await assert.rejects(()=>getPendingEvents(d,{limit:51}),/unbounded/);
});
