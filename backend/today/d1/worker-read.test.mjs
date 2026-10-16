import test from 'node:test';
import assert from 'node:assert/strict';
import {handleTodayRead} from './worker-read.mjs';
function mockDb() {
  return {prepare(sql){
    if (sql.includes('catalog_meta')) return {first:async()=>null};
    if (sql.includes('public_today_canonical')) return {bind(...params){
      assert.equal(params.at(-2),201); // LIMIT+1 probe
      assert.equal(params.at(-1),0); // OFFSET
      return {all:async()=>({results:[]})};
    }};
    throw Error('unexpected D1 SQL');
  }};
}
test('existing Worker GET route returns compatible bounded Today envelope',async()=>{
  const response=await handleTodayRead(new Request('https://api.example/v1/catalog/today?day=2026-10-15'),{DB:mockDb()},new Date('2026-10-15T12:00:00Z'));
  assert.equal(response.status,200);
  const data=await response.json();
  assert.equal(data.schema_version,'public-consumer-v1');
  assert.deepEqual(data.streams,[]);
  assert.equal(data.completeness.gap,true);
});
test('route stays GET-only and rejects invalid limit',async()=>{
  const env={DB:mockDb()};
  assert.equal((await handleTodayRead(new Request('https://api.example/v1/catalog/today',{method:'POST'}),env)).status,405);
  assert.equal((await handleTodayRead(new Request('https://api.example/v1/catalog/today?limit=999'),env)).status,400);
});
test('no DB binding fails closed without leaking internals',async()=>{
  const r=await handleTodayRead(new Request('https://api.example/v1/catalog/today'),{});
  assert.equal(r.status,503);
  assert.equal((await r.json()).error,'service_unavailable');
});
