import test from 'node:test';
import assert from 'node:assert/strict';
import {validateOneShotReceipt,buildOneShotPlan,executeOneShot} from './one-shot-writer.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk';
const r={video_id:V,channel_id:C,roster_version:'approved-v1',group:'hololive',title:'Sample',channel_name:'Channel',lifecycle_state:'upcoming',scheduled_start:'2026-10-16T00:00:00Z',observed_at:'2026-10-15T12:00:00Z',source_label:'YouTube'};
const receipt={mode:'PROVIDER_READ_ONLY',d1_writes:0,roster_version:'approved-v1',records:[r],channel_count:1,api_calls:2,gap:false};
test('owner gate and roster source proof fail closed',async()=>{
 assert.equal(validateOneShotReceipt(receipt),receipt);
 assert.throws(()=>validateOneShotReceipt({...receipt,gap:true}),/gap/);
 assert.throws(()=>buildOneShotPlan(receipt,[{id:'UC'+'B'.repeat(22),group:'hololive'}]),/membership/);
 const plan=buildOneShotPlan(receipt,[{id:C,group:'hololive'}]);
 await assert.rejects(()=>executeOneShot(plan,{}),/approval/);
 assert.equal(plan.expected_channels,1);
});

test('failure at record N leaves degraded coverage, never a success receipt',async()=>{
 const plan=buildOneShotPlan({...receipt,records:[r,{...r,video_id:'zyxwvutsrqp'}]},[{id:C,group:'hololive'}]);
 let coverage=null,writes=0;
 const db={prepare(sql){
  if(sql.startsWith('DELETE FROM public_today_approved_channels'))return {run:async()=>{}};
  if(sql.startsWith('INSERT INTO public_today_approved_channels'))return {bind(){return {run:async()=>{}}}};
  if(sql.startsWith('INSERT INTO public_today_catalog_meta'))return {bind(version,last,expected,scanned,gap){return {run:async()=>{coverage={version,last,expected,scanned,gap}}}}};
  if(sql.startsWith('SELECT checksum FROM public_today_evidence'))return {bind(){return {first:async()=>null}}};
  if(sql.startsWith('SELECT lifecycle_state'))return {bind(){return {first:async()=>null}}};
  if(sql.startsWith('INSERT INTO public_today_evidence'))return {bind(){return {run:async()=>{writes++;if(writes===2)throw Error('disk failure')}}}};
  if(sql.startsWith('INSERT INTO public_today_canonical'))return {bind(){return {run:async()=>{}}}};
  throw Error('unexpected statement '+sql.slice(0,60));
 },async batch(statements){for(const statement of statements)await statement.run()}};
 await assert.rejects(()=>executeOneShot(plan,db,{explicitApproved:true}),/PARTIAL WRITE; coverage marked degraded/);
 assert.equal(coverage.gap,1);
 assert.equal(coverage.scanned,0);
 assert.equal(coverage.last,null);
});
