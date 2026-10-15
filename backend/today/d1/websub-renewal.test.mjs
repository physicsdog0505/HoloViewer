import test from 'node:test';import assert from 'node:assert/strict';import {planSubscriptions} from './websub-renewal.mjs';
const a='UC'+'A'.repeat(22),b='UC'+'B'.repeat(22);
test('bounded renewal only due approved channels; retired not auto-unsubscribed',()=>{
 const roster={version:'v72',channels:[{id:a},{id:b}]};
 const leases=[{channel_id:a,expires_at:'2026-10-20T00:00:00Z'},{channel_id:b,expires_at:'2026-10-16T12:00:00Z'},{channel_id:'UC'+'C'.repeat(22)}];
 const x=planSubscriptions(roster,leases,{now:new Date('2026-10-16T00:00:00Z')});
 assert.deepEqual(x.due.map(y=>y.channel_id),[b]);
 assert.equal(x.unapproved_existing.length,1);assert.equal(x.mode,'DRY_RUN_ONLY');
 assert.equal(planSubscriptions(roster,[],{limit:1}).has_more,true);
 assert.throws(()=>planSubscriptions({version:'x',channels:[{id:a},{id:a}]},[]),/duplicate/);
});
