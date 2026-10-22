import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {recordSubscriptionRequest,confirmSubscriptionChallenge,readSubscriptionLeases} from './websub-leases.mjs';
const C='UC'+'A'.repeat(22),V='v85';
function db(){
 const raw=new DatabaseSync(':memory:');raw.exec(readFileSync(new URL('./websub-leases.PROPOSED.sql',import.meta.url),'utf8'));
 return {raw,prepare(sql){return {bind(...args){return {run:async()=>raw.prepare(sql).run(...args),first:async()=>raw.prepare(sql).get(...args)??null}},all:async()=>({results:raw.prepare(sql).all()})}}};
}
test('only pending matching roster/version can activate lease; expiry is durable',async()=>{
 const d=db(),now=new Date('2026-10-16T01:00:00Z');
 await assert.rejects(()=>confirmSubscriptionChallenge(d,{channelId:C,rosterVersion:V,mode:'subscribe',leaseSeconds:432000,now}),/no matching/);
 await recordSubscriptionRequest(d,{channelId:C,rosterVersion:V,now});
 await assert.rejects(()=>confirmSubscriptionChallenge(d,{channelId:C,rosterVersion:'old',mode:'subscribe',leaseSeconds:432000,now}),/no matching/);
 const result=await confirmSubscriptionChallenge(d,{channelId:C,rosterVersion:V,mode:'subscribe',leaseSeconds:432000,now});
 assert.equal(result.state,'active');assert.equal(result.expires_at,'2026-10-21T01:00:00Z');
 assert.equal((await readSubscriptionLeases(d))[0].state,'active');
 await assert.rejects(()=>confirmSubscriptionChallenge(d,{channelId:C,rosterVersion:V,mode:'subscribe',leaseSeconds:432000,now}),/no matching/);
});
test('stale pending challenge is rejected and cannot silently extend lease',async()=>{
 const d=db();
 await recordSubscriptionRequest(d,{channelId:C,rosterVersion:V,now:new Date('2026-10-15T00:00:00Z')});
 await assert.rejects(()=>confirmSubscriptionChallenge(d,{channelId:C,rosterVersion:V,mode:'subscribe',leaseSeconds:4000,now:new Date('2026-10-16T12:00:00Z')}),/no matching/);
 assert.equal((await readSubscriptionLeases(d))[0].state,'pending');
});
