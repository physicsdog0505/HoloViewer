// Run: node --test backend/today/d1/store.test.mjs
// Offline D1-compatible facade using Node built-in SQLite; no Cloudflare calls.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {writeEvidence,setCoverage,readToday} from './store.mjs';
const C='UC'+'A'.repeat(22), V='abcdefghijk';
function fixture({id=V,state='live',observed='2026-10-15T11:59:00Z',end=null,group='hololive'}={}) {
  return {video_id:id,channel_id:C,roster_version:'fixture-v1',group,
    title:'Fixture',channel_name:'Fixture channel',lifecycle_state:state,
    observed_at:observed,scheduled_start:'2026-10-16T00:00:00Z',
    actual_start:state==='upcoming'?null:'2026-10-15T11:00:00Z',
    actual_end:end,source_label:'YouTube'};
}
function db() {
  const sqlite=new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
  const wrap={prepare(sql){return {bind(...params){
    const stmt=sqlite.prepare(sql);
    return {first:async()=>stmt.get(...params)??null,
      all:async()=>({results:stmt.all(...params)}),
      run:async()=>stmt.run(...params)};
  },first:async()=>sqlite.prepare(sql).get()??null};
  },async batch(statements){
    sqlite.exec('BEGIN IMMEDIATE');
    try {const result=[];for(const s of statements)result.push(await s.run());sqlite.exec('COMMIT');return result;}
    catch(e){sqlite.exec('ROLLBACK');throw e;}
  },close(){sqlite.close()},raw:sqlite};
  return wrap;
}
test('create/replay/update/read and durable END',async()=>{
  const d=db();
  assert.equal((await writeEvidence(d,fixture())).changed,true);
  assert.equal((await writeEvidence(d,fixture())).changed,false);
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,1);
  const ended=fixture({state:'ended',observed:'2026-10-15T12:02:00Z',end:'2026-10-15T12:01:00Z'});
  assert.equal((await writeEvidence(d,ended)).changed,true);
  const old=fixture({observed:'2026-10-15T12:04:00Z'});
  assert.equal((await writeEvidence(d,old)).changed,false);
  await setCoverage(d,{roster_version:'fixture-v1',last_success_at:'2026-10-15T12:04:00Z',expected_channels:1,scanned_channels:1,gap:false,checkpoint:'cp_abcdefgh'});
  const result=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T16:00:00Z')});
  assert.equal(result.streams.length,1);
  assert.equal(result.streams[0].lifecycle_state,'ended');
  assert.equal(result.completeness.status,'partial'); // no self-certified COMPLETE
  assert.equal(result.checkpoint,'cp_abcdefgh');
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_evidence').get().n,3);
  d.close();
});
test('same observation key cannot introduce contradictory facts',async()=>{
  const d=db();await writeEvidence(d,fixture());
  await assert.rejects(()=>writeEvidence(d,{...fixture(),title:'Contradiction'}),/contradictory/);
  d.close();
});
test('publisher and roster mismatch rejected',async()=>{
  const d=db();await writeEvidence(d,fixture());
  await assert.rejects(()=>writeEvidence(d,{...fixture({observed:'2026-10-15T12:05:00Z'}),roster_version:'unapproved'}),/mismatch/);
  d.close();
});
test('coverage cannot leak integer checkpoint; empty result stays partial/unverified',async()=>{
  const d=db();
  await setCoverage(d,{roster_version:'fixture-v1',expected_channels:1,scanned_channels:0,gap:true,checkpoint:7});
  const x=await readToday(d,{day:'2026-10-15',now:new Date('2026-10-15T12:00:00Z')});
  assert.equal(x.streams.length,0);
  assert.equal(x.completeness.gap,true);
  assert.equal(x.checkpoint,null);
  assert.notEqual(x.completeness.status,'complete');
  d.close();
});
test('migration can be applied repeatedly without dropping data',async()=>{
  const d=db();await writeEvidence(d,fixture());
  d.raw.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
  assert.equal(d.raw.prepare('SELECT COUNT(*) n FROM public_today_canonical').get().n,1);
  d.close();
});
test('invalid lifecycle and bad day reject without source modifications',async()=>{
  const d=db();
  await assert.rejects(()=>writeEvidence(d,fixture({state:'ended',end:null})),/end requires positive/);
  await assert.rejects(()=>readToday(d,{day:'2026-1-5'}));
  d.close();
});
