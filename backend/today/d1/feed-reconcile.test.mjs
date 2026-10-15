import test from 'node:test';import assert from 'node:assert/strict';import {DatabaseSync} from 'node:sqlite';import {readFileSync} from 'node:fs';import {reconcileAtomFeeds} from './feed-reconcile.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk';
function db(){const sqlite=new DatabaseSync(':memory:');sqlite.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));return {sqlite,prepare(sql){return {bind(...params){return {run:async()=>sqlite.prepare(sql).run(...params)}}}}}}
test('bounded Atom reconciliation enqueues idempotent real-shape video discovery',async()=>{
 const d=db(),roster={version:'v72',channels:[{id:C}]};
 const feed='<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:channelId>'+C+'</yt:channelId><yt:videoId>'+V+'</yt:videoId></entry></feed>';
 const args={db:d,roster,fetchFeed:async()=>feed,now:new Date('2026-10-16T00:00:00Z')};
 assert.equal((await reconcileAtomFeeds(args)).discovered,1);
 await reconcileAtomFeeds(args);
 assert.equal(d.sqlite.prepare('SELECT COUNT(*) n FROM public_today_websub_events').get().n,1);
});
test('mismatched channel feed does not enqueue cross-channel videos',async()=>{
 const d=db();
 const out=await reconcileAtomFeeds({db:d,roster:{version:'v72',channels:[{id:C}]},fetchFeed:async()=>'<feed><entry><yt:channelId>'+'UC'+'B'.repeat(22)+'</yt:channelId><yt:videoId>'+V+'</yt:videoId></entry></feed>'});
 assert.equal(out.failed,1);assert.equal(d.sqlite.prepare('SELECT COUNT(*) n FROM public_today_websub_events').get().n,0);
});
