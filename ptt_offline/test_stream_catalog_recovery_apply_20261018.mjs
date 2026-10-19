import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {
  applyRecoveryPlan,normalizeRecoveryEvidence,recoveryPlan,TARGET_DAY
} from './stream_catalog_recovery_apply_20261018.mjs';
import {writeEvidence,YOUTUBE_LIVE_SOURCE} from './worker_host/today/store.mjs';

const C='UC'+'A'.repeat(22);
function db(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0002_today_canonical.sql',import.meta.url),'utf8'));
 function stmt(sql,params=[]){return {
  bind(...values){return stmt(sql,values)},
  async first(){return sqlite.prepare(sql).get(...params)??null},
  async all(){return {results:sqlite.prepare(sql).all(...params)}},
  async run(){return sqlite.prepare(sql).run(...params)}
 }}
 return {
  raw:sqlite,prepare(sql){return stmt(sql)},
  async batch(statements){
   sqlite.exec('BEGIN IMMEDIATE');
   try{const out=[];for(const s of statements)out.push(await s.run());sqlite.exec('COMMIT');return out;}
   catch(e){sqlite.exec('ROLLBACK');throw e;}
  },
  close(){sqlite.close()}
 };
}
function row(overrides={}){
 return {
  video_id:'TnijhHRqd5w',
  channel_id:'UCDqI2jOz0weumE8s7paEk6g',
  channel_name:'Roboco Ch. - ロボ子',
  title:'Roboco',
  lifecycle_state:'ended',
  scheduled_start:'2026-10-18T15:00:00Z',
  actual_start:'2026-10-18T15:00:06Z',
  actual_end:'2026-10-18T16:04:31Z',
  projection_observed_at:'2026-10-18T16:05:00Z',
  roster_version:'fixture-v1',
  group:'hololive',
  production_status:'missing',
  today_import_candidate:true,
  history_missing_candidate:true,
  ...overrides,
 };
}
function artifact(rows=[row()]){
 return {schema_version:'stream-catalog-recovery-inventory-v1',
  target_day_taipei:TARGET_DAY,recovery_source:'8501 Stream Catalog',rows};
}
test('known Roboco fixture preserves exact actual bounds and approved authority label',()=>{
 const e=normalizeRecoveryEvidence(row());
 assert.equal(e.video_id,'TnijhHRqd5w');
 assert.equal(e.actual_start,'2026-10-18T15:00:06Z');
 assert.equal(e.actual_end,'2026-10-18T16:04:31Z');
 assert.equal(e.source_label,YOUTUBE_LIVE_SOURCE);
});
test('dry-run plans Today and History candidates with zero DB access/writes',async()=>{
 const plan=recoveryPlan(artifact());
 let touched=0;
 const noDb={prepare(){touched++;throw Error('must not touch DB')}};
 const out=await applyRecoveryPlan(noDb,plan,{dryRun:true});
 assert.equal(out.dry_run,true);assert.equal(out.writes,0);assert.equal(touched,0);
 assert.equal(plan.today_candidates.length,1);
 assert.equal(plan.history_missing_candidates.length,1);
});
test('replay is idempotent and does not auto-write History',async()=>{
 const d=db(),plan=recoveryPlan(artifact());
 const first=await applyRecoveryPlan(d,plan,{dryRun:false});
 const second=await applyRecoveryPlan(d,plan,{dryRun:false});
 assert.equal(first.changed,1);
 assert.equal(second.replay,1);
 assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,1);
 assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,1);
 // Recovery importer intentionally defers History. 0002 does not even create public_history.
 d.close();
});
test('production newer projection wins over older recovery evidence',async()=>{
 const d=db();
 await writeEvidence(d,{
  video_id:'newerprod01',channel_id:C,roster_version:'fixture-v1',group:'hololive',
  title:'Prod',channel_name:'Channel',lifecycle_state:'live',
  observed_at:'2026-10-18T10:00:00Z',scheduled_start:'2026-10-18T08:00:00Z',
  actual_start:'2026-10-18T08:01:00Z',actual_end:null,source_label:YOUTUBE_LIVE_SOURCE
 },{projectHistory:false});
 const plan=recoveryPlan(artifact([row({
  video_id:'newerprod01',channel_id:C,lifecycle_state:'live',
  projection_observed_at:'2026-10-18T09:00:00Z',actual_start:'2026-10-18T08:01:00Z',actual_end:null,
  history_missing_candidate:false
 })]));
 const out=await applyRecoveryPlan(d,plan,{dryRun:false});
 assert.equal(out.evidence_only,1);
 const got=d.raw.prepare('SELECT lifecycle_observed_at,title FROM public_today_canonical WHERE video_id=?').get('newerprod01');
 assert.equal(got.lifecycle_observed_at,'2026-10-18T10:00:00Z');
 assert.equal(got.title,'Prod');
 d.close();
});
test('ended production cannot regress to newer live or upcoming recovery state',async()=>{
 for(const state of ['live','upcoming']){
  const d=db();
  await writeEvidence(d,{
   video_id:'endedprod01',channel_id:C,roster_version:'fixture-v1',group:'hololive',
   title:'Ended',channel_name:'Channel',lifecycle_state:'ended',
   observed_at:'2026-10-18T10:00:00Z',scheduled_start:'2026-10-18T08:00:00Z',
   actual_start:'2026-10-18T08:01:00Z',actual_end:'2026-10-18T09:00:00Z',source_label:YOUTUBE_LIVE_SOURCE
  },{projectHistory:false});
  const plan=recoveryPlan(artifact([row({
   video_id:'endedprod01',channel_id:C,lifecycle_state:state,
   projection_observed_at:'2026-10-18T11:00:00Z',
   actual_start:state==='upcoming'?null:'2026-10-18T08:01:00Z',actual_end:null,
   history_missing_candidate:false
  })]));
  const out=await applyRecoveryPlan(d,plan,{dryRun:false});
  assert.equal(out.evidence_only,1);
  const got=d.raw.prepare('SELECT lifecycle_state,actual_start,actual_end FROM public_today_canonical WHERE video_id=?').get('endedprod01');
  assert.equal(got.lifecycle_state,'ended');
  assert.equal(got.actual_start,'2026-10-18T08:01:00Z');
  assert.equal(got.actual_end,'2026-10-18T09:00:00Z');
  d.close();
 }
});
test('recovery preserves exact bounds and never fabricates missing actual times',async()=>{
 const d=db();
 const exact=recoveryPlan(artifact([row({
  video_id:'exactbnd001',channel_id:C,history_missing_candidate:false
 })]));
 await applyRecoveryPlan(d,exact,{dryRun:false});
 let got=d.raw.prepare('SELECT actual_start,actual_end FROM public_today_canonical WHERE video_id=?').get('exactbnd001');
 assert.deepEqual(got,{actual_start:'2026-10-18T15:00:06Z',actual_end:'2026-10-18T16:04:31Z'});
 const livePlan=recoveryPlan(artifact([row({
  video_id:'nobounds001',channel_id:C,lifecycle_state:'live',
  projection_observed_at:'2026-10-18T12:00:00Z',
  scheduled_start:'2026-10-18T11:00:00Z',actual_start:null,actual_end:null,
  history_missing_candidate:false
 })]));
 await applyRecoveryPlan(d,livePlan,{dryRun:false});
 got=d.raw.prepare('SELECT scheduled_start,actual_start,actual_end FROM public_today_canonical WHERE video_id=?').get('nobounds001');
 assert.equal(got.scheduled_start,'2026-10-18T11:00:00Z');
 assert.equal(got.actual_start,null);assert.equal(got.actual_end,null);
 d.close();
});
