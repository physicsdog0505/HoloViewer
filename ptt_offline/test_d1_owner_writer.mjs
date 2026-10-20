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
function makeRows(count,template=row) {
  return Array.from({length:count},(_,i)=>({...template,
    push_id:'ptt:v1:'+String(i+1).padStart(64,'0'),
    source_line:i+1,source_record_key:template.aid+':'+(i+1)}));
}
function mock(rows=[row],options={}) {
  const calls=[];
  const byPush=new Map(rows.map(value=>[value.push_id,value]));
  const bySource=new Map(rows.map(value=>[value.day+':'+value.aid+':'+value.source_record_key,value]));
  const DB={prepare(sql){return {bind(...args){return {
    async first(){throw new Error('unexpected point read')},
    async all(){calls.push(['read',sql,args]);
      if(sql.includes('FROM ptt_pushes WHERE push_id IN')) {
        const results=args.map(pushId=>byPush.get(pushId)).filter(Boolean).map(value=>({
          push_id:value.push_id,aid:value.aid,day:value.day,source_line:value.source_line,
          author:value.author,content:options.tamperPush?'tampered':value.content,
          occurred_at:value.occurred_at,source_url:value.source_url
        }));
        return {results};
      }
      if(sql.includes('SELECT day,aid,source_record_key,push_id,source_line FROM ptt_source_evidence')) {
        const results=[];
        for(let i=0;i<args.length;i+=3){
          const value=bySource.get(args[i]+':'+args[i+1]+':'+args[i+2]);
          if(value)results.push({day:value.day,aid:value.aid,source_record_key:value.source_record_key,
            push_id:value.push_id,source_line:value.source_line});
        }
        return {results};
      }
      if(sql.includes('SELECT day,aid,source_record_key,push_id FROM ptt_source_evidence')) {
        const results=[];
        for(let i=0;i<args.length;i+=3){
          const value=bySource.get(args[i]+':'+args[i+1]+':'+args[i+2]);
          if(value && options.existingMatching)results.push({day:value.day,aid:value.aid,
            source_record_key:value.source_record_key,push_id:value.push_id});
          if(value && options.conflictKey===value.source_record_key)results.push({day:value.day,aid:value.aid,
            source_record_key:value.source_record_key,push_id:'ptt:v1:'+'b'.repeat(64)});
        }
        return {results};
      }
      return {results:[]};
    },
    sql,args};}}},async batch(stmts){calls.push(['batch',stmts.length,stmts]);
    const changes=options.changes??1;
    return stmts.map(()=>({meta:{changes}}));}};
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
  const mutationSql=calls[1][2].map(x=>x.sql);
  assert.ok(mutationSql.find(x=>x.includes('INSERT INTO ptt_threads')).includes('WHERE ptt_threads.source_url IS NULL'));
  assert.ok(mutationSql.find(x=>x.includes('INSERT INTO ptt_pushes')).includes('WHERE (ptt_pushes.floor IS NULL'));
  assert.ok(mutationSql.find(x=>x.includes('INSERT INTO ptt_source_evidence')).includes('WHERE ptt_source_evidence.push_id<>excluded.push_id'));
  assert.equal(ack.d1_rows_written,4);
});
test('refuse spoofed source identity',async()=>{
  const {DB,calls}=mock();
  await assert.rejects(applyAuthorizedPttBatch({DB,batch:await signed({...batch,rows:[{...row,source_url:'https://evil.example/x'}]}),verifyAuthority:async()=>true}),/invalid canonical row/);
  assert.equal(calls.length,0);
});
test('conflicting replay refuses mutation',async()=>{
  const {DB,calls}=mock([row],{conflictKey:row.source_record_key});
  await assert.rejects(applyAuthorizedPttBatch({DB,batch,verifyAuthority:async()=>true}),/evidence conflict/);
  assert.equal(calls.filter(c=>c[0]==='read').length,1);
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
 const {DB,calls}=mock([row],{tamperPush:true});
 await assert.rejects(applyAuthorizedPttBatch({DB,batch,verifyAuthority:async()=>true}),
   /remote state uncertain, do not retry/);
 assert.equal(calls.some(c=>c[0]==='batch'),true);
 assert.equal(calls.filter(c=>c[0]==='read').length,3);
});

test('reviewed steady-state batch of 12 pushes is accepted with bounded accounting',async()=>{
 const rows=makeRows(12);
 const expanded=await signed({...batch,rows,write_cap:12});
 const {DB,calls}=mock(rows);
 const ack=await applyAuthorizedPttBatch({DB,batch:expanded,
  verifyAuthority:async()=>true,limits:{rows:12,writes:30,queries:70}});
 assert.equal(ack.logical_rows_acked,12);
 assert.equal(ack.d1_rows_written,26);
 assert.equal(ack.d1_query_count,29);
 assert.equal(calls.filter(c=>c[0]==='read').length,3);
});

test('1 vs 10 vs 25 pushes keep verification reads constant at three',async()=>{
 for(const count of [1,10,25]){
  const rows=makeRows(count);
  const candidate=await signed({...batch,rows,write_cap:count});
  const {DB,calls}=mock(rows);
  const ack=await applyAuthorizedPttBatch({DB,batch:candidate,verifyAuthority:async()=>true,
    limits:{rows:25,writes:80,queries:150}});
  assert.equal(calls.filter(c=>c[0]==='read').length,3);
  assert.equal(ack.d1_query_count,2*count+2+3);
 }
});

test('multi-AID batch preserves exact bounded accounting and readback',async()=>{
 const second={...row,push_id:'ptt:v1:'+'c'.repeat(64),aid:'1gq0n6WU',source_line:325,
   source_record_key:'1gq0n6WU:325',occurred_at:'2026-10-15T09:35:00Z',
   source_url:'https://www.ptt.cc/bbs/C_Chat/M.1792019526.A.81E.html'};
 const rows=[row,second];
 const candidate=await signed({...batch,rows,write_cap:2});
 const {DB,calls}=mock(rows);
 const ack=await applyAuthorizedPttBatch({DB,batch:candidate,verifyAuthority:async()=>true,
   limits:{rows:25,writes:80,queries:150}});
 assert.equal(ack.logical_rows_acked,2);
 assert.equal(ack.d1_rows_written,8);
 assert.equal(ack.d1_query_count,11);
 assert.equal(calls.filter(c=>c[0]==='read').length,3);
 assert.equal(calls.find(c=>c[0]==='batch')[1],8);
});

test('matching replay remains idempotent while preserving three verification reads',async()=>{
 const rows=makeRows(10);
 const candidate=await signed({...batch,rows,write_cap:10});
 const {DB,calls}=mock(rows,{existingMatching:true,changes:0});
 const ack=await applyAuthorizedPttBatch({DB,batch:candidate,verifyAuthority:async()=>true,
   limits:{rows:25,writes:80,queries:150}});
 assert.equal(ack.status,'ACK');
 assert.equal(ack.d1_rows_written,0);
 assert.equal(calls.filter(c=>c[0]==='read').length,3);
});
