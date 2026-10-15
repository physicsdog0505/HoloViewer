import test from 'node:test';
import assert from 'node:assert/strict';
import {legacyHistory,legacyVideo} from './legacy-compat.mjs';
const db={prepare(sql){return {bind(...args){return {
 first:async()=>sql.includes('COUNT')?{total:7}:sql.includes('public_catalog')?{video_id:args[0]}:null,
 all:async()=>({results:[{id:1}]})
}}}}};
test('history validates day bounds and returns legacy envelope',async()=>{
 const r=await legacyHistory(new Request('https://api.example/v1/history?day=2026-10-15&limit=5&offset=1'),{DB:db});
 assert.deepEqual(await r.json(),{day:'2026-10-15',total:7,limit:5,offset:1,items:[{id:1}]});
 assert.equal(r.headers.get('cache-control'),'public, max-age=30');
 for(const query of ['day=wrong','day=2026-10-15&limit=51','day=2026-10-15&offset=1000001']){
  const x=await legacyHistory(new Request('https://api.example/v1/history?'+query),{DB:db});
  assert.equal(x.status,400);
  assert.equal((await x.json()).error,'invalid_history_query');
 }
});
test('video lookup legacy status envelope and input guard',async()=>{
 assert.equal((await legacyVideo(new Request('https://api.example/v1/catalog/videos/short'),{DB:db})).status,400);
 const ok=await legacyVideo(new Request('https://api.example/v1/catalog/videos/abcdefghijk'),{DB:db});
 assert.equal(ok.status,200);assert.equal((await ok.json()).video_id,'abcdefghijk');
});

test('live SQL parity: Taipei day, explicit projection and stable sort',async()=>{
 const seen=[];
 const DB={prepare(sql){seen.push(sql);return {bind(...args){return {
 async first(){return sql.includes('COUNT(*)')?{total:1}:{video_id:args[0]}},
 async all(){return {results:[{video_id:'abcdefghijk'}]}}
 }}}}};
 const h=await legacyHistory(new Request('https://api.example/v1/history?day=2026-10-15&limit=1'),{DB});
 assert.equal(h.status,200);
 assert.match(seen[0],/WHERE taipei_day=\?/);
 assert.match(seen[1],/SELECT video_id,title,channel_id,channel_name,avatar_url,actual_start,actual_end,scheduled_start FROM public_history/);
 assert.match(seen[1],/COALESCE\(actual_start,scheduled_start\) DESC,video_id DESC/);
 assert.doesNotMatch(seen[1],/SELECT \*/);
 await legacyVideo(new Request('https://api.example/v1/catalog/videos/abcdefghijk'),{DB});
 assert.match(seen[2],/SELECT video_id,title,channel_id,channel_name,avatar_url,lifecycle_state,actual_start,actual_end,scheduled_start FROM public_catalog/);
});
test('impossible ISO days and oversized numeric values reject before database access',async()=>{
 const never={prepare(){throw Error('should not query')}};
 for(const q of ['day=2026-02-30','day=2026-13-01','day=2026-10-15&offset=999999999999999999999999','day=2026-10-15&limit=0']){
  const r=await legacyHistory(new Request('https://api.example/v1/history?'+q),{DB:never});
  assert.equal(r.status,400,q);
 }
});
