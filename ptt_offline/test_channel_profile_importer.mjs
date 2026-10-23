import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import {runImport} from './worker_host/today/channel-profile-import-local.mjs';

function d1(){
 const sqlite=new DatabaseSync(':memory:');
 sqlite.exec(readFileSync(new URL('./worker_host/today/0005_channel_profiles.sql',import.meta.url),'utf8'));
 let writes=0;
 function stmt(sql,params=[]){return {
  bind(...values){return stmt(sql,values)},
  async first(){return sqlite.prepare(sql).get(...params)??null},
  async all(){return {results:sqlite.prepare(sql).all(...params)}},
  async run(){const r=sqlite.prepare(sql).run(...params);writes+=Number(r.changes??0);return r}
 }}
 return {
  prepare(sql){return stmt(sql)},
  async batch(statements){
   sqlite.exec('BEGIN IMMEDIATE');
   try{const out=[];for(const s of statements)out.push(await s.run());sqlite.exec('COMMIT');return out}
   catch(e){sqlite.exec('ROLLBACK');throw e}
  },
  writes:()=>writes,
  raw:sqlite,
  close(){sqlite.close()}
 };
}
function profile(i,overrides={}){
 const suffix=i.toString(36).toUpperCase().padStart(22,'0');
 return {
  channel_id:'UC'+suffix,
  channel_name:'Channel '+i,
  display_name:'Channel '+i,
  avatar_url:'https://yt3.ggpht.com/avatar-'+i,
  group:i%2?'hololive':'holostars',
  member_accent:null,
  member_accent_dual:null,
  support_mode:'neutral',
  support_color_source:null,
  profile_revision:'today-profile:today85-20261016-d0e326c0496b:2026-10-18T03:52:36Z',
  updated_at:'2026-10-18T03:52:36Z',
  ...overrides
 };
}
function artifact(overrides={}){
 const body={
  schema_version:'holoviewer-channel-profile-import-v1',
  authority:'production-readonly:public_today_approved_channels+public_today_channel_profiles',
  roster_version:'today85-20261016-d0e326c0496b',
  profile_count:85,
  profiles:Array.from({length:85},(_,i)=>profile(i)),
  ...overrides
 };
 return JSON.stringify(body);
}
function sha(text){return createHash('sha256').update(text).digest('hex')}

test('validate mode performs zero writes for exact 85-profile artifact',async()=>{
 const db=d1(); const raw=artifact();
 const out=await runImport({DB:db},raw,{apply:false,approvedSha:sha(raw)});
 assert.equal(out.status,'VALIDATED');
 assert.equal(out.production_mutation,false);
 assert.equal(out.profile_count,85);
 assert.equal(out.plan.inserts,85);
 assert.equal(db.writes(),0);
 db.close();
});

test('apply writes 85 once and replay writes zero',async()=>{
 const db=d1(); const raw=artifact(), digest=sha(raw);
 const first=await runImport({DB:db},raw,{apply:true,approvedSha:digest});
 assert.equal(first.status,'APPLIED');
 assert.equal(first.profiles_written,85);
 const before=db.writes();
 const replay=await runImport({DB:db},raw,{apply:true,approvedSha:digest});
 assert.equal(replay.profiles_written,0);
 assert.equal(db.writes(),before);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_channel_profiles').get().n,85);
 db.close();
});

test('artifact sha mismatch aborts before write',async()=>{
 const db=d1(); const raw=artifact();
 await assert.rejects(()=>runImport({DB:db},raw,{apply:true,approvedSha:'0'.repeat(64)}),/artifact sha mismatch/);
 assert.equal(db.writes(),0);
 db.close();
});

test('same timestamp different canonical content aborts before batch writes',async()=>{
 const db=d1(); const raw=artifact(), digest=sha(raw);
 await runImport({DB:db},raw,{apply:true,approvedSha:digest});
 const body=JSON.parse(raw);
 body.profiles[42].display_name='Conflicting';
 const conflict=JSON.stringify(body), conflictSha=sha(conflict);
 await assert.rejects(()=>runImport({DB:db},conflict,{apply:true,approvedSha:conflictSha}),/same-timestamp profile conflict/);
 assert.equal(db.raw.prepare('SELECT display_name FROM public_channel_profiles WHERE channel_id=?').get(body.profiles[42].channel_id).display_name,'Channel 42');
 db.close();
});

test('duplicate ID and untrusted avatar fail validation',async()=>{
 const db=d1();
 let body=JSON.parse(artifact());
 body.profiles[1].channel_id=body.profiles[0].channel_id;
 let raw=JSON.stringify(body);
 await assert.rejects(()=>runImport({DB:db},raw,{apply:false,approvedSha:sha(raw)}),/artifact channel identity invalid/);

 body=JSON.parse(artifact());
 body.profiles[0].avatar_url='https://example.com/avatar';
 raw=JSON.stringify(body);
 await assert.rejects(()=>runImport({DB:db},raw,{apply:false,approvedSha:sha(raw)}),/artifact avatar invalid/);
 db.close();
});

test('bounded importer uses at most four write batches for 85 profiles',async()=>{
 const db=d1(); let batchCalls=0;
 const counted={...db,async batch(stmts){batchCalls++;return db.batch(stmts)}};
 const raw=artifact();
 const out=await runImport({DB:counted},raw,{apply:true,approvedSha:sha(raw)});
 assert.equal(out.profiles_written,85);
 assert.equal(batchCalls,4);
 db.close();
});
