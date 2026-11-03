import test from 'node:test';
import assert from 'node:assert/strict';
import {applyAuthorizedCanonicalRemap,canonicalRemapDigest,
  handleOwnerPttCanonicalRemap} from './d1_owner_canonical_remap.mjs';

const keys=['push_id','aid','day','source_line','kind','author','content','occurred_at',
  'floor','source_url','source_priority','source_record_key'];
const base={aid:'1gwHM4TF',day:'2026-11-03',source_line:383,kind:'推',author:'old-author',
  content:'provisional',occurred_at:'2026-11-03T10:00:00Z',floor:1,
  source_url:'https://www.ptt.cc/bbs/C_Chat/M.1793660292.A.74F.html',source_priority:10,
  source_record_key:'1gwHM4TF:383'};
const old={...base,push_id:'ptt:v1:'+'a'.repeat(64)};
const newer={...base,push_id:'ptt:v1:'+'b'.repeat(64),author:'canonical-author',
  content:'canonical',canonical_proof:'c'.repeat(64)};

async function signed(rows=[{old,new:newer}],overrides={}) {
  const batch={repair_type:'CANONICAL_SOURCE_LINE_REMAP_V1',source_identity:'d'.repeat(64),
    day:rows[0].new.day,aid:rows[0].new.aid,source_lines:rows.map(row=>row.new.source_line),
    rows,request_cap:1,write_cap:2*rows.length,retry_cap:0,...overrides};
  batch.digest=await canonicalRemapDigest(batch);
  batch.batch_id='ptt-remap-v1:'+batch.digest.slice(0,24);
  return batch;
}
function rowFor(line,index=0) {
  const suffix=(index+1).toString(16).padStart(64,'0');
  const next=(index+101).toString(16).padStart(64,'0');
  const common={...base,source_line:line,source_record_key:'1gwHM4TF:'+line};
  return {old:{...common,push_id:'ptt:v1:'+suffix},
    new:{...common,push_id:'ptt:v1:'+next,author:'new-'+line,content:'new-'+line,
      canonical_proof:'c'.repeat(64)}};
}
function mock(batch,{mismatchOld=false,tamperAfter=false,already=false,partialChanges=false}={}) {
  const calls=[];
  const pushes=new Map();
  const evidence=new Map();
  for(const pair of batch.rows) {
    const initial=already?pair.new:{...pair.old,content:mismatchOld?'wrong':pair.old.content};
    pushes.set(initial.push_id,{...initial});
    evidence.set(pair.old.day+':'+pair.old.aid+':'+pair.old.source_record_key,{
      day:pair.old.day,aid:pair.old.aid,source_record_key:pair.old.source_record_key,
      push_id:initial.push_id,source_line:initial.source_line});
  }
  const DB={prepare(sql){return {sql,bind(...args){return {sql,args,async all(){
    calls.push(['read',sql,args]);
    if(sql.includes('FROM ptt_pushes'))return {results:args.map(id=>pushes.get(id)).filter(Boolean)};
    if(sql.includes('FROM ptt_source_evidence')) {
      const results=[];
      for(let i=0;i<args.length;i+=3){const found=evidence.get(args[i]+':'+args[i+1]+':'+args[i+2]);if(found)results.push(found)}
      return {results};
    }
    return {results:[]};
  }}}}},async batch(statements){
    calls.push(['batch',statements]);
    for(const pair of batch.rows){
      pushes.delete(pair.old.push_id);pushes.set(pair.new.push_id,{...pair.new});
      const key=pair.old.day+':'+pair.old.aid+':'+pair.old.source_record_key;
      evidence.set(key,{day:pair.new.day,aid:pair.new.aid,source_record_key:pair.new.source_record_key,
        push_id:pair.new.push_id,source_line:pair.new.source_line});
    }
    if(tamperAfter)pushes.get(batch.rows[0].new.push_id).content='tampered';
    return statements.map((_,index)=>({meta:{changes:partialChanges&&index===0?0:1}}));
  }};
  return {DB,calls};
}
const verify=async()=>true;

test('exact old to new canonical remap passes in one bounded transaction',async()=>{
  const batch=await signed();const {DB,calls}=mock(batch);
  const receipt=await applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify});
  assert.equal(receipt.status,'ACK');assert.equal(receipt.logical_rows_repaired,1);
  assert.equal(receipt.live_checkpoint_mutations,0);
  assert.deepEqual(calls.map(call=>call[0]),['read','read','batch','read','read']);
});

test('old remote identity mismatch fails closed before mutation',async()=>{
  const batch=await signed();const {DB,calls}=mock(batch,{mismatchOld:true});
  await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}),/old remote identity mismatch/);
  assert.equal(calls.some(call=>call[0]==='batch'),false);
});

test('AID day and range scope mismatch fail before D1 access',async()=>{
  for(const mutation of [
    rows=>[{old:{...rows[0].old,day:'2026-11-02'},new:rows[0].new}],
    rows=>[{old:{...rows[0].old,aid:'other',source_record_key:'other:383'},new:{...rows[0].new,aid:'other',source_record_key:'other:383'}}],
    ()=>[rowFor(382)],
  ]) {
    const batch=await signed(mutation([{old,new:newer}]));const {DB,calls}=mock(batch);
    await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}));
    assert.equal(calls.length,0);
  }
});

test('more than five rows fails before D1 access',async()=>{
  const rows=[383,384,385,386,387,388].map(rowFor);const batch=await signed(rows);
  const {DB,calls}=mock(batch);
  await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}),/cap exceeded/);
  assert.equal(calls.length,0);
});

test('repair cannot change a row outside exact allowlist',async()=>{
  const batch=await signed([rowFor(401)]);const {DB,calls}=mock(batch);
  await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}),/allowlist/);
  assert.equal(calls.length,0);
});

test('exact post-transaction readback mismatch fails closed',async()=>{
  const batch=await signed();const {DB}=mock(batch,{tamperAfter:true});
  await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}),/readback mismatch/);
});

test('exact replay is idempotent and writes zero rows',async()=>{
  const batch=await signed();const {DB,calls}=mock(batch,{already:true});
  const receipt=await applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify});
  assert.equal(receipt.status,'ALREADY_APPLIED');assert.equal(receipt.d1_rows_written,0);
  assert.equal(calls.some(call=>call[0]==='batch'),false);
});

test('repair SQL has no broad DELETE DROP reseed or checkpoint mutation',async()=>{
  const batch=await signed();const {DB,calls}=mock(batch);
  const receipt=await applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify});
  const sql=calls.flatMap(call=>call[0]==='batch'?call[1].map(stmt=>stmt.sql):[]).join('\n');
  assert.doesNotMatch(sql,/\b(?:DELETE|DROP|TRUNCATE|REPLACE)\b/i);
  assert.doesNotMatch(sql,/provider_state|gap_repairs|checkpoint/i);
  assert.match(sql,/WHERE push_id=\?/);assert.match(sql,/source_record_key=\?/);
  assert.equal(receipt.live_checkpoint_mutations,0);
});

test('HMAC authorization is mandatory before body can reach repair writer',async()=>{
  const batch=await signed();let touched=false;
  const DB={prepare(){touched=true;throw Error('unexpected')},batch(){touched=true;throw Error('unexpected')}};
  const response=await handleOwnerPttCanonicalRemap(new Request('https://api.example/private/ptt/canonical-remap',{
    method:'POST',body:JSON.stringify(batch)}),{PTT_CANONICAL_REMAP_ENABLED:'true',DB},
    {authorize:async()=>false,verifyCanonical:verify});
  assert.equal(response.status,401);assert.equal(touched,false);
});

test('non-exact statement changes never emit ACK',async()=>{
  const batch=await signed();const {DB}=mock(batch,{partialChanges:true});
  await assert.rejects(applyAuthorizedCanonicalRemap({DB,batch,verifyCanonical:verify}),/not exactly applied/);
});
