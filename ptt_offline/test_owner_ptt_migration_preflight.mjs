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
 assert.throws(()=>run(['--apply'],invoke,()=>{}),/exact owner checksum approval required/);
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

test('owner pinned apply uses one transactional Wrangler migration and verifies',()=>{
 const plan=planMigration();
 const existing=['public_catalog','public_history','public_today_schema_migrations','d1_migrations'];
 const after=[...existing,'ptt_threads','ptt_pushes','ptt_source_evidence',
   'ptt_provider_state','ptt_gap_repairs','public_ptt_schema_migrations'];
 const commands=[];let wrote=false;
 const execute=(args)=>{
  commands.push(args);
  if(args[0]==='whoami')return ACCOUNT;
  if(args[0]==='d1'&&args[1]==='migrations'&&args[2]==='apply'){wrote=true;return 'ok';}
  const sql=args[args.length-1];
  const rows=sql.includes('SELECT version,description')?
    [{version:1,description:'canonical push, thread scope, replay and forward repair state'}]:
    (wrote?after:existing).map(name=>({name,type:'table'}));
  return JSON.stringify([{success:true,results:rows}]);
 };
 const result=run(['--apply','--approve='+plan.sha256],execute,()=>{});
 assert.equal(result.mode,'OWNER_APPLIED_VERIFIED');
 assert.equal(commands.filter(c=>c[1]==='migrations'&&c[2]==='apply').length,1);
 assert.equal(commands.find(c=>c[1]==='migrations'&&c[2]==='apply')[3],plan.database);
});

test('remote failure after mutation attempt forces STOP without retry',()=>{
 const plan=planMigration();
 let mutations=0;
 const existing=['public_catalog','public_history','public_today_schema_migrations','d1_migrations'];
 const exec=(args)=>{
  if(args[0]==='whoami')return ACCOUNT;
  if(args[0]==='d1'&&args[1]==='migrations'&&args[2]==='apply'){mutations++;throw Error('network lost after possible commit');}
  return JSON.stringify([{success:true,results:existing.map(name=>({name,type:'table'}))}]);
 };
 assert.throws(()=>run(['--apply','--approve='+plan.sha256],exec,()=>{}),
   /REMOTE MUTATION MAY HAVE OCCURRED; STOP, INSPECT, DO NOT RETRY/);
 assert.equal(mutations,1);
});
test('existing PTT migration aborts before any write',()=>{
 const plan=planMigration();
 const existing=['public_catalog','public_history','public_today_schema_migrations',
   'd1_migrations','ptt_threads','ptt_pushes','ptt_source_evidence',
   'ptt_provider_state','ptt_gap_repairs','public_ptt_schema_migrations'];
 let writes=0;
 const exec=(args)=>{
  if(args[0]==='whoami')return ACCOUNT;
  if(args[0]==='d1'&&args[1]==='migrations'&&args[2]==='apply'){writes++;throw Error('must not happen')}
  if(String(args.at(-1)).includes('SELECT version,description'))
    return JSON.stringify([{success:true,results:[{version:1,description:'ptt'}]}]);
  return JSON.stringify([{success:true,results:existing.map(name=>({name,type:'table'}))}]);
 };
 assert.throws(()=>run(['--apply','--approve='+plan.sha256],exec,()=>{}),
   /migration already applied/);
 assert.equal(writes,0);
});
