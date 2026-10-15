import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {writeEvidence,setCoverage} from './store.mjs';
import {handleTodayRead} from './worker-read.mjs';
const CHANNEL='UC'+'A'.repeat(22);
const VIDEO='abcdefghijk';
class SQLiteD1 {
 constructor(){
  this.sqlite=new DatabaseSync(':memory:');
  this.sqlite.exec(readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8'));
 }
 prepare(sql){
  const stmt=this.sqlite.prepare(sql);
  const bindings=[];
  return {
   bind(...values){bindings.splice(0,bindings.length,...values);return this;},
   async first(){return stmt.get(...bindings)??null;},
   async all(){return {results:stmt.all(...bindings)};},
   async run(){return stmt.run(...bindings);}
  };
 }
 async batch(statements){
  this.sqlite.exec('BEGIN');
  try{
   for(const stmt of statements)await stmt.run();
   this.sqlite.exec('COMMIT');
  }catch(e){this.sqlite.exec('ROLLBACK');throw e;}
 }
 close(){this.sqlite.close();}
}
test('real SQLite migration schema: approved roster + evidence -> API GET canonical live card',async()=>{
 const db=new SQLiteD1();
 try {
  const timestamp='2026-10-15T12:00:00Z';
  await setCoverage(db,{roster_version:'approved-v1',expected_channels:1,scanned_channels:1,
   gap:true,last_success_at:timestamp,approved_channels:[{id:CHANNEL,group:'hololive'}]});
  const evidence={video_id:VIDEO,channel_id:CHANNEL,roster_version:'approved-v1',
   group:'hololive',title:'Genuine-format provider sample (offline only)',channel_name:'Example',
   lifecycle_state:'live',observed_at:timestamp,actual_start:'2026-10-15T11:00:00Z',
   scheduled_start:'2026-10-15T11:00:00Z',actual_end:null,source_label:'YouTube'};
  const first=await writeEvidence(db,evidence);
  assert.equal(first.changed,true);
  assert.equal((await writeEvidence(db,evidence)).reason,'replay');
  const response=await handleTodayRead(new Request('https://api.example/v1/catalog/today?day=2026-10-15'),{DB:db},new Date('2026-10-15T12:02:00Z'));
  assert.equal(response.status,200);
  const body=await response.json();
  assert.equal(body.schema_version,'public-consumer-v1');
  assert.equal(body.streams.length,1);
  assert.equal(body.streams[0].video_id,VIDEO);
  assert.equal(body.streams[0].lifecycle_state,'live');
  assert.equal(body.streams[0].avatar_url,null);
  assert.equal(body.completeness.status,'partial');
  assert.equal(db.sqlite.prepare('SELECT COUNT(*) AS n FROM public_today_evidence').get().n,1);
 }finally{db.close()}
});
