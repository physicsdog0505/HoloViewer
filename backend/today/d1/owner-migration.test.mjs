import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {sha256Hex} from './migrate.mjs';
import {executeOwnerTodayMigration,TARGET} from './owner-migration.mjs';
const sql=readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8');
function mockD1(){
 const raw=new DatabaseSync(':memory:');
 function stmt(sql,params=[]){return {bind(...v){return stmt(sql,v)},async run(){return raw.prepare(sql).run(...params)},async first(){return raw.prepare(sql).get(...params)??null}}}
 return {prepare:sql=>stmt(sql),async batch(steps){raw.exec('BEGIN IMMEDIATE');try{for(const step of steps)await step.run();raw.exec('COMMIT')}catch(e){raw.exec('ROLLBACK');throw e}},raw,close(){raw.close()}};
}
test('owner migration requires approval and exact identity before touching D1',async()=>{
 const db=mockD1(),checksum=await sha256Hex(sql);
 const opts={db,sql,expectedSha256:checksum,accountId:TARGET.accountId,databaseId:TARGET.databaseId};
 await assert.rejects(()=>executeOwnerTodayMigration(opts),/approval/);
 await assert.rejects(()=>executeOwnerTodayMigration({...opts,authorized:true,databaseId:'other'}),/identity/);
 await assert.rejects(()=>executeOwnerTodayMigration({...opts,authorized:true,expectedSha256:'0'.repeat(64)}),/SHA-256/);
 assert.equal(db.raw.prepare("SELECT COUNT(*) n FROM sqlite_master WHERE name='public_today_schema_migrations'").get().n,0);
 db.close();
});
test('approved exact SQL applies atomically, idempotent replay preserves unrelated history',async()=>{
 const db=mockD1(),checksum=await sha256Hex(sql);
 db.raw.exec('CREATE TABLE public_history (id TEXT); INSERT INTO public_history VALUES (\'preserved\')');
 const opts={db,sql,expectedSha256:checksum,accountId:TARGET.accountId,databaseId:TARGET.databaseId,authorized:true,appliedAt:'2026-10-15T00:00:00Z'};
 const first=await executeOwnerTodayMigration(opts);
 assert.equal(first.applied,true);
 assert.equal((await executeOwnerTodayMigration(opts)).applied,false);
 assert.equal(db.raw.prepare("SELECT checksum FROM public_today_schema_migrations").get().checksum,checksum);
 assert.equal(db.raw.prepare('SELECT id FROM public_history').get().id,'preserved');
 assert.equal(db.raw.prepare('SELECT COUNT(*) n FROM public_today_schema_migrations').get().n,1);
 db.close();
});
