import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,readFileSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {inspectRelease,firstWindow} from './check-release-preflight.mjs';

const files=[
 'backend/today/d1/0002_today_canonical.sql',
 'backend/today/d1/api-shell.mjs',
 'backend/today/d1/migrate.mjs',
 'backend/today/d1/store.mjs',
 'backend/today/d1/PRODUCTION_EXECUTION_RUNBOOK.md'
];
const sourceRoot=new URL('../../../',import.meta.url);
function isolatedFixture(action){
 const path=mkdtempSync(join(tmpdir(),'issue47-preflight-'));
 try{
   for(const file of files){
     const dest=join(path,file);
     mkdirSync(dirname(dest),{recursive:true});
     writeFileSync(dest,readFileSync(new URL(file,sourceRoot)));
   }
   const root=pathToFileURL(path+'/');
   return action({path,root});
 }finally{rmSync(path,{recursive:true,force:true})}
}
test('reviewed source fingerprints and #45 frozen canary are stable',()=>{
 const receipt=inspectRelease();
 assert.equal(receipt.result,'OFFLINE_PREFLIGHT_PASS');
 assert.equal(receipt.production_mutation,false);
 assert.match(receipt.migration_sha256,/^[0-9a-f]{64}$/);
 assert.deepEqual(firstWindow,{httpMax:5,d1QueriesMax:12,rowsReadMax:1000,rowsWritten:0,retries:0});
});
test('release preflight rejects any changed migration bytes rather than recalculating a new authority',()=>{
 isolatedFixture(({path,root})=>{
   const sql=join(path,files[0]);
   writeFileSync(sql,Buffer.concat([readFileSync(sql),Buffer.from('\n-- unexpected drift\n')]));
   assert.throws(()=>inspectRelease(root),/reviewed source fingerprint drift: backend\/today\/d1\/0002_today_canonical\.sql/);
 });
});
test('release preflight rejects changed API shell and does not touch cloud',()=>{
 isolatedFixture(({path,root})=>{
   const shell=join(path,files[1]);
   writeFileSync(shell,Buffer.concat([readFileSync(shell),Buffer.from('\n// drift\n')]));
   assert.throws(()=>inspectRelease(root),/reviewed source fingerprint drift: backend\/today\/d1\/api-shell\.mjs/);
 });
});
test('release preflight refuses runbook with loosened read-only canary ceiling',()=>{
 isolatedFixture(({path,root})=>{
   const file=join(path,files[4]);
   writeFileSync(file,readFileSync(file,'utf8').replaceAll('D1 queries <= 12','D1 queries <= 120'));
   assert.throws(()=>inspectRelease(root),/runbook canary constraint missing: D1 queries <= 12/);
 });
});
