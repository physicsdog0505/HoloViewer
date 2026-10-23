import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectAuthorizedPttBatch,handleOwnerPttReconcile} from './d1_owner_reconcile.mjs';
import {batchDigest} from './d1_owner_writer.mjs';

async function fixtureBatch(){
 const row={push_id:'ptt:v1:'+'a'.repeat(64),aid:'1abc',day:'2026-10-23',source_line:10,
  kind:'推',author:'u',content:'x',occurred_at:'2026-10-23T12:00:00Z',floor:null,
  source_url:'https://www.ptt.cc/bbs/C_Chat/M.1792753209.A.FD7.html',
  source_priority:10,source_record_key:'1abc:10',time_proof:'proof'};
 const batch={source_identity:'s'.repeat(64),day:'2026-10-23',rows:[row],
  request_cap:1,write_cap:1,retry_cap:0};
 batch.digest=await batchDigest(batch);batch.batch_id='ptt48:'+batch.digest.slice(0,24);return batch;
}
function db({pushes=[],evidence=[]}={}){
 let writes=0;
 return {get writes(){return writes;},prepare(sql){
  if(/\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP)\b/i.test(sql)){writes++;throw Error('write');}
  return {bind(){return {all:async()=>({results:sql.includes('ptt_source_evidence')?evidence:pushes})}}};
 }};
}
test('all present returns exact committed result with zero writes',async()=>{
 const batch=await fixtureBatch(),row=batch.rows[0];
 const DB=db({pushes:[row],evidence:[{day:row.day,aid:row.aid,source_record_key:row.source_record_key,push_id:row.push_id,source_line:row.source_line}]});
 const r=await inspectAuthorizedPttBatch({DB,batch});
 assert.equal(r.outcome,'ALL_PRESENT');assert.equal(r.present,1);assert.equal(DB.writes,0);
});
test('none present is distinguishable from partial',async()=>{
 const batch=await fixtureBatch();
 const none=await inspectAuthorizedPttBatch({DB:db(),batch});
 assert.equal(none.outcome,'NONE_PRESENT');
 const row=batch.rows[0];
 const partial=await inspectAuthorizedPttBatch({DB:db({pushes:[row]}),batch});
 assert.equal(partial.outcome,'PARTIAL_OR_MISMATCH');
});
test('private reconcile requires HMAC authorization and never requires publish-enabled',async()=>{
 const batch=await fixtureBatch();
 const request=new Request('https://api.example/private/ptt/reconcile',{method:'POST',body:JSON.stringify(batch)});
 const denied=await handleOwnerPttReconcile(request.clone(),{DB:db()},{authorize:()=>false});
 assert.equal(denied.status,401);
 const allowed=await handleOwnerPttReconcile(request,{DB:db()},{authorize:()=>true});
 assert.equal(allowed.status,200);
 assert.equal((await allowed.json()).outcome,'NONE_PRESENT');
});
