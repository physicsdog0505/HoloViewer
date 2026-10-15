import test from 'node:test';import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {claimEvent,finishClaim,failClaim,nextReconcileWindow,commitReconcileWindow,saveChannelProfiles} from './websub-hardening.mjs';
import {planLeaseRecovery} from './websub-lease-recovery.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk',hash='a'.repeat(64),t1='1'.repeat(64),t2='2'.repeat(64);
const raw=new DatabaseSync(':memory:');
raw.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
raw.exec(readFileSync(new URL('./websub-hardening.PROPOSED.sql',import.meta.url),'utf8'));
const db={prepare(s){return {first:async()=>raw.prepare(s).get()??null,bind(...args){return {run:async()=>raw.prepare(s).run(...args),first:async()=>raw.prepare(s).get(...args)??null}}}}};
test('CAS claim excludes second worker, expired claim fences old ACK',async()=>{
 raw.prepare("INSERT INTO public_today_websub_events(event_hash,channel_id,video_id,roster_version,received_at,status) VALUES(?,?,?,?,?,'pending')").run(hash,C,V,'v1','2026-10-16T00:00:00Z');
 const now=new Date('2026-10-16T01:00:00Z');
 assert.equal(await claimEvent(db,hash,t1,{now,leaseSeconds:30}),true);
 assert.equal(await claimEvent(db,hash,t2,{now}),false);
 assert.equal(await claimEvent(db,hash,t2,{now:new Date('2026-10-16T01:00:31Z')}),true);
 await assert.rejects(()=>finishClaim(db,hash,t1,{now:new Date('2026-10-16T01:00:32Z')}),/claim lost/);
 await finishClaim(db,hash,t2,{now:new Date('2026-10-16T01:00:32Z')});
 assert.equal(raw.prepare('SELECT status FROM public_today_websub_events').get().status,'processed');
});
test('durable roster cursor rotates and resumes without always restarting at channel zero',async()=>{
 const roster={version:'v85',channels:[{id:C},{id:'UC'+'B'.repeat(22)},{id:'UC'+'C'.repeat(22)}]};
 const a=await nextReconcileWindow(db,roster,{limit:2});assert.deepEqual(a.selected.map(x=>x.id),[C,'UC'+'B'.repeat(22)]);
 await commitReconcileWindow(db,a);
 const b=await nextReconcileWindow(db,roster,{limit:2});
 assert.deepEqual(b.selected.map(x=>x.id),['UC'+'C'.repeat(22),C]);
});
test('verified channels.list profile persists title/avatar for approved channel only',async()=>{
 await saveChannelProfiles(db,{version:'v85',channels:[{id:C}]},[{id:C,snippet:{title:'Birthday Channel',thumbnails:{default:{url:'https://yt3.ggpht.com/abc'}}}}]);
 assert.equal(raw.prepare('SELECT channel_title FROM public_today_channel_profiles').get().channel_title,'Birthday Channel');
 await assert.rejects(()=>saveChannelProfiles(db,{version:'v85',channels:[{id:C}]},[{id:'UC'+'B'.repeat(22),snippet:{title:'wrong'}}]),/unapproved/);
});
test('pending timeout/rejection requires manual review, never blind retry',()=>{
 const r=planLeaseRecovery({version:'v1',channels:[{id:C}]},[{channel_id:C,roster_version:'v1',state:'pending',requested_at:'2026-10-15T00:00:00Z'}],{now:new Date('2026-10-16T00:00:00Z')});
 assert.equal(r.review[0].reason,'uncertain_pending_request');assert.equal(r.due.length,0);
});
