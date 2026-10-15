import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {applyTodayMigration,sha256Hex} from './migrate.mjs';
const SQL=readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8');
function memoryD1(){
 const db=new DatabaseSync(':memory:');
 const wrap={prepare(sql){const stmt=db.prepare(sql);return {
   bind(...values){return {first:async()=>stmt.get(...values)??null,run:async()=>stmt.run(...values)}},
   first:async()=>stmt.get()??null,run:async()=>stmt.run()
 }},async batch(batch){
   db.exec('BEGIN IMMEDIATE');
   try {for(const step of batch)await step.run();db.exec('COMMIT')}
   catch(e){db.exec('ROLLBACK');throw e}
 },raw:db,close:()=>db.close()};
 return wrap;
}
test('migration create, exact replay no-op, ledger and schema durable',async()=>{
 const db=memoryD1();
 const once=await applyTodayMigration(db,{sql:SQL,appliedAt:'2026-10-15T00:00:00Z'});
 assert.equal(once.applied,true);
 assert.equal(once.checksum,await sha256Hex(SQL));
 const again=await applyTodayMigration(db,{sql:SQL,appliedAt:'2026-10-16T00:00:00Z'});
 assert.equal(again.applied,false);
 const row=db.raw.prepare('SELECT * FROM public_today_schema_migrations').get();
 assert.equal(row.checksum,once.checksum);
 assert.equal(row.applied_at,'2026-10-15T00:00:00Z');
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM sqlite_master WHERE name=?').get('public_today_canonical').n,1);
 db.close();
});
test('migration checksum drift fails and retains initial provenance',async()=>{
 const db=memoryD1();
 await applyTodayMigration(db,{sql:SQL});
 await assert.rejects(()=>applyTodayMigration(db,{sql:SQL+'\n-- unexpected drift'}),/checksum drift/);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_schema_migrations').get().n,1);
 db.close();
});
test('unsupported destructive migration rejected before DB modification',async()=>{
 const db=memoryD1();
 await assert.rejects(()=>applyTodayMigration(db,{sql:'DROP TABLE public_today_canonical;'}),/unsafe migration/);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM sqlite_master WHERE name=?').get('public_today_schema_migrations').n,0);
 db.close();
});

test('concurrent migration checksum loser rolls back all extra schema',async()=>{
 const db=memoryD1();
 const accepted="CREATE TABLE IF NOT EXISTS claimed_table (id INTEGER PRIMARY KEY);";
 const unaccepted="CREATE TABLE IF NOT EXISTS unaccepted_extra_table (id INTEGER PRIMARY KEY);";
 // Force both appliers to observe absent ledger, then let the accepted
 // migration win before the second transactional batch begins.
 const startBatch=db.batch.bind(db);
 let firstBatch=null;
 const barrier=new Promise(resolve=>{firstBatch=resolve});
 const originalPrepare=db.prepare.bind(db);
 let emptyReads=0;
 db.prepare=(sql)=>{
   const result=originalPrepare(sql);
   if (sql.includes('SELECT checksum FROM public_today_schema_migrations')) {
     return {bind(...values){
       const bound=result.bind(...values);
       return {...bound,first:async()=>{
         if(emptyReads++<2)return null;
         return bound.first();
       }};
     }};
   }
   return result;
 };
 let releaseSecond;
 const firstCommitted=new Promise(resolve=>{releaseSecond=resolve});
 let batches=0;
 db.batch=async actions=>{
   batches++;
   if(batches===2)await firstCommitted;
   try{return await startBatch(actions)}
   finally {if(batches===1)releaseSecond()}
 };
 const outcomes=await Promise.allSettled([
   applyTodayMigration(db,{sql:accepted}),
   applyTodayMigration(db,{sql:unaccepted})
 ]);
 assert.equal(outcomes.filter(x=>x.status==='fulfilled').length,1);
 assert.equal(outcomes.filter(x=>x.status==='rejected').length,1);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name='claimed_table'").get().n,1);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name='unaccepted_extra_table'").get().n,0);
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_schema_migrations').get().n,1);
 db.close();
});
