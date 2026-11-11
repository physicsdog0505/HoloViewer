import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {applyTodayMigration,sha256Hex} from './migrate.mjs';
const SQL=readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8');

function memoryD1(){
 const db=new DatabaseSync(':memory:');
 function statement(sql,params=[]){
   return {
     bind(...values){return statement(sql,values)},
     async first(){return db.prepare(sql).get(...params)??null},
     async all(){return {results:db.prepare(sql).all(...params)}},
     async run(){return db.prepare(sql).run(...params)}
   };
 }
 const wrap={
   prepare(sql){return statement(sql)},
   async batch(batch){
     db.exec('BEGIN IMMEDIATE');
     try {
       const result=[];
       for(const step of batch) result.push(await step.run());
       db.exec('COMMIT');
       return result;
     } catch(e) {
       db.exec('ROLLBACK');
       throw e;
     }
   },
   raw:db,
   close:()=>db.close()
 };
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
 const acceptedChecksum=await sha256Hex(accepted);

 // Reproduce the D1 race deterministically: this contender observes an empty
 // ledger, then a competing transaction commits before its batch begins.
 const originalPrepare=db.prepare.bind(db);
 let forcedAbsent=false;
 db.prepare=(sql)=>{
   const result=originalPrepare(sql);
   if (!forcedAbsent && sql.includes('SELECT checksum FROM public_today_schema_migrations')) {
     return {bind(...values){
       const bound=result.bind(...values);
       return {...bound,first:async()=>{forcedAbsent=true;return null}};
     }};
   }
   return result;
 };

 const startBatch=db.batch.bind(db);
 let winnerInjected=false;
 db.batch=async actions=>{
   if(!winnerInjected){
     winnerInjected=true;
     db.raw.exec('CREATE TABLE IF NOT EXISTS claimed_table (id INTEGER PRIMARY KEY)');
     db.raw.prepare(`INSERT INTO public_today_schema_migrations(migration_id,checksum,applied_at)
       VALUES (?,?,?)`).run('0002_today_canonical',acceptedChecksum,'2026-10-15T00:00:00Z');
   }
   return startBatch(actions);
 };

 await assert.rejects(()=>applyTodayMigration(db,{sql:unaccepted}),/UNIQUE|constraint/i);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name='claimed_table'").get().n,1);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name='unaccepted_extra_table'").get().n,0);
 const ledger=db.raw.prepare('SELECT checksum FROM public_today_schema_migrations').get();
 assert.equal(ledger.checksum,acceptedChecksum);
 db.close();
});
