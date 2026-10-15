import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAuthorizedPttBatch} from './d1_owner_writer.mjs';
const row={push_id:'ptt:v1:'+'a'.repeat(64),aid:'A1',day:'2026-10-15',
  source_line:1,kind:'推',author:'a',content:'genuine-source-required',
  occurred_at:'2026-10-15T10:00:00Z',floor:null,
  source_url:'https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html',
  source_record_key:'A1:1'};
const batch={rows:[row],day:row.day,batch_id:'ptt48:fixture',digest:'sha-test',
  request_cap:1,retry_cap:0};
function mock() {
  const calls=[];
  const DB={prepare(sql){return {bind(...args){return {
    async first(){calls.push(['read',sql,args]);return null},
    sql,args};}}},async batch(stmts){calls.push(['batch',stmts.length]);
    return stmts.map(()=>({meta:{changes:1}}));}};
  return {DB,calls};
}
test('reject missing positive event authority before any D1 mutation',async()=>{
  const {DB,calls}=mock();
  await assert.rejects(applyAuthorizedPttBatch({DB,batch,verifyAuthority:async()=>false}),
    /unverified source event timestamp/);
  assert.equal(calls.length,0);
});
test('one atomic transactional D1 batch after authority and provenance checks',async()=>{
  const {DB,calls}=mock();
  const ack=await applyAuthorizedPttBatch({DB,batch,verifyAuthority:async()=>true});
  assert.equal(ack.logical_rows_acked,1);
  assert.equal(ack.d1_query_count,4);
  assert.deepEqual(calls.map(x=>x[0]),['read','batch']);
  assert.equal(calls[1][1],3);
});
test('refuse spoofed source identity',async()=>{
  const {DB,calls}=mock();
  await assert.rejects(applyAuthorizedPttBatch({DB,batch:{...batch,rows:[{...row,source_url:'https://evil.example/x'}]},verifyAuthority:async()=>true}),/invalid canonical row/);
  assert.equal(calls.length,0);
});
test('conflicting replay refuses mutation',async()=>{
  const {DB,calls}=mock();
  const conflict={...DB,prepare(sql){const prepared=DB.prepare(sql);
    return {bind(...args){const bound=prepared.bind(...args);return {...bound,first:async()=>{
      calls.push(['read',sql,args]);return {push_id:'ptt:v1:'+'b'.repeat(64)};}}}}}};
  await assert.rejects(applyAuthorizedPttBatch({DB:conflict,batch,verifyAuthority:async()=>true}),/evidence conflict/);
  assert.equal(calls.some(c=>c[0]==='batch'),false);
});

test('reject cross-Taipei-day timestamp before D1 access',async()=>{
  const {DB,calls}=mock();
  const wrong={...row,occurred_at:'2026-10-14T10:00:00Z'};
  await assert.rejects(applyAuthorizedPttBatch({
    DB,batch:{...batch,rows:[wrong]},verifyAuthority:async()=>true
  }),/invalid canonical row/);
  assert.equal(calls.length,0);
});
