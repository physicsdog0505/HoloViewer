import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAuthorizedPttBatch,batchDigest} from './d1_owner_writer.mjs';
const row={push_id:'ptt:v1:'+'a'.repeat(64),aid:'1gepPtNy',day:'2026-10-15',
  source_line:1,kind:'推',author:'a',content:'genuine-source-required',
  occurred_at:'2026-10-15T10:00:00Z',floor:null,
  source_url:'https://www.ptt.cc/bbs/C_Chat/M.1789081207.A.5FC.html',
  source_record_key:'1gepPtNy:1'};
const draft={rows:[row],day:row.day,source_identity:'collector-proof',write_cap:1,request_cap:1,retry_cap:0};
const digest=await batchDigest(draft);
const batch={...draft,digest,batch_id:'ptt48:'+digest.slice(0,24)};
async function signed(value){const d=await batchDigest(value);return {...value,digest:d,batch_id:'ptt48:'+d.slice(0,24)};}
function mock() {
  const calls=[];
  const DB={prepare(sql){return {bind(...args){return {
    async first(){calls.push(['read',sql,args]);
      if(sql.includes('FROM ptt_pushes WHERE push_id='))return {
        aid:row.aid,day:row.day,source_line:row.source_line,
        author:row.author,content:row.content,occurred_at:row.occurred_at,source_url:row.source_url};
      if(sql.includes('SELECT push_id,source_line FROM ptt_source_evidence'))
        return {push_id:row.push_id,source_line:row.source_line};
      return null},
    sql,args};}}},async batch(stmts){calls.push(['batch',stmts.length,stmts]);
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
  assert.equal(ack.d1_query_count,7);
  assert.deepEqual(calls.map(x=>x[0]),['read','batch','read','read']);
  assert.equal(calls[1][1],4);
  assert.ok(calls[1][2].some(x=>x.sql.includes('ptt_provider_state') && x.sql.includes('has_gap=1')));
  assert.equal(ack.d1_rows_written,4);
});
test('refuse spoofed source identity',async()=>{
  const {DB,calls}=mock();
  await assert.rejects(applyAuthorizedPttBatch({DB,batch:await signed({...batch,rows:[{...row,source_url:'https://evil.example/x'}]}),verifyAuthority:async()=>true}),/invalid canonical row/);
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
    DB,batch:await signed({...batch,rows:[wrong]}),verifyAuthority:async()=>true
  }),/invalid canonical row/);
  assert.equal(calls.length,0);
});

test('reject mismatched AID and canonical PTT URL before D1 access',async()=>{
 const {DB,calls}=mock();
 await assert.rejects(applyAuthorizedPttBatch({
  DB,batch:await signed({...batch,rows:[{...row,aid:'WrongAid'}]}),
  verifyAuthority:async()=>true}),/invalid canonical row/);
 assert.equal(calls.length,0);
});

test('tampered batch digest fails before D1 access',async()=>{
 const {DB,calls}=mock();
 await assert.rejects(applyAuthorizedPttBatch({
  DB,batch:{...batch,digest:'f'.repeat(64)},verifyAuthority:async()=>true
 }),/batch checksum mismatch/);
 assert.equal(calls.length,0);
});

test('publisher terminal 2-of-5 rows preserves Python canonical digest',async()=>{
 const {DB,calls}=mock();
 const terminal=await signed({...batch,write_cap:5});
 const ack=await applyAuthorizedPttBatch({DB,batch:terminal,verifyAuthority:async()=>true});
 assert.equal(ack.logical_rows_acked,1);
 assert.equal(calls.some(c=>c[0]==='batch'),true);
});

test('D1 mutation with inconsistent canonical readback never emits ACK',async()=>{
 const {DB,calls}=mock();
 const faulty={...DB,prepare(sql){
   const original=DB.prepare(sql);
   if(!sql.includes('FROM ptt_pushes WHERE push_id='))return original;
   return {bind(...args){const bound=original.bind(...args);
     return {...bound,first:async()=>({...await bound.first(),content:'tampered'})};
   }};
 }};
 await assert.rejects(applyAuthorizedPttBatch({DB:faulty,batch,verifyAuthority:async()=>true}),
   /remote state uncertain, do not retry/);
 assert.equal(calls.some(c=>c[0]==='batch'),true);
});

test('reviewed steady-state batch of 12 pushes is accepted with bounded accounting',async()=>{
 const rows=Array.from({length:12},(_,i)=>({...row,
  push_id:'ptt:v1:'+String(i+1).padStart(64,'0'),
  source_line:i+1,source_record_key:'1gepPtNy:'+(i+1)}));
 const expanded=await signed({...batch,rows,write_cap:12});
 const calls=[];
 const DB={prepare(sql){return {bind(...args){return {sql,args,async first(){
  calls.push(sql);
  if(sql.includes('SELECT push_id,source_line FROM ptt_source_evidence'))
    return {push_id:rows.find(x=>x.source_record_key===args[2]).push_id,
      source_line:rows.find(x=>x.source_record_key===args[2]).source_line};
  if(sql.includes('FROM ptt_pushes WHERE push_id=')){
   const found=rows.find(x=>x.push_id===args[0]);
   return Object.fromEntries(['aid','day','source_line','author','content','occurred_at','source_url'].map(k=>[k,found[k]]));
  }
  return null;
 }}}}},async batch(stmts){return stmts.map(()=>({meta:{changes:1}}))}};
 const ack=await applyAuthorizedPttBatch({DB,batch:expanded,
  verifyAuthority:async()=>true,limits:{rows:12,writes:30,queries:70}});
 assert.equal(ack.logical_rows_acked,12);
 assert.equal(ack.d1_rows_written,26);
 assert.equal(ack.d1_query_count,63);
});
