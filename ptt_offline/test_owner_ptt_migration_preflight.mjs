import test from 'node:test';
import assert from 'node:assert/strict';
import {planMigration,assertInventory,decodeD1,run,verifyAppliedPttLedger,UUID,ACCOUNT} from './owner_ptt_migration_preflight.mjs';
test('freeze original migration and reject byte drift',()=>{
 const receipt=planMigration();
 assert.equal(receipt.uuid,UUID);
 assert.equal(receipt.sha256,'70f4a2da051b107421c443fb3bf26dda55d3c46bf4b3a66823bb84d3f19ac14f');
 assert.throws(()=>planMigration(Buffer.from('arbitrary')),/immutable/);
});
test('require already deployed Today and legacy coexistence',()=>{
 const initial=['public_catalog','public_history','public_today_schema_migrations','d1_migrations'];
 assert.equal(assertInventory(initial.map(name=>({name}))).wranglerLedgerPresent,true);
 assert.throws(()=>assertInventory([{name:'public_catalog'}]),/missing existing/);
 assert.throws(()=>assertInventory([...initial,'ptt_pushes'].map(name=>({name}))),/partially applied/);
});
test('read-only only, pinned account and no write command',()=>{
 const inventory=['public_catalog','public_history','public_today_schema_migrations','d1_migrations'];
 const calls=[];
 const invoke=(args)=>{
  calls.push(args);
  if(args[0]==='whoami') return ACCOUNT;
  return JSON.stringify([{success:true,results:inventory.map(name=>({name,type:'table'}))}]);
 };
 assert.throws(()=>run(['--apply'],invoke,()=>{}),/write\/apply not implemented/);
 const result=run(['--inspect'],invoke,()=>{});
 assert.equal(result.mode,'READ_ONLY_ACCOUNT_PREFLIGHT');
 assert.equal(calls.length,2);
 assert.equal(calls[1][2],UUID);
 assert.equal(calls.some(a=>a.includes('apply')||a.includes('--file')),false);
});
test('reject invalid Cloudflare metadata',()=>{
 assert.throws(()=>decodeD1('{"success":false,"results":[]}'),/invalid/);
});

test('existing PTT objects are not treated as applied without version ledger',()=>{
 const inventory={pttSchemaPresent:true};
 assert.throws(()=>verifyAppliedPttLedger([],inventory),/ledger missing/);
 assert.deepEqual(verifyAppliedPttLedger([{version:1,description:'ptt'}],inventory),
   {applied:true,verified:true,version:1});
});
