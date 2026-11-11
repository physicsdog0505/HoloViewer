import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildPlan,executionArgs,validateAccountReceipt,decodeD1,inspectBefore,inspectAfter,EXPECTED_OBJECTS,executeOwnerCli} from './owner-wrangler-migration.mjs';
test('wrangler migration package preserves exact reviewed SQL and inserts ledger atomically',()=>{
 const p=buildPlan(),source=readFileSync(new URL('./0002_today_canonical.sql',import.meta.url),'utf8');
 assert.ok(p.sql.startsWith(source));
 assert.ok(p.sql.includes("INSERT INTO public_today_schema_migrations"));
 assert.ok(p.sql.includes(p.sha256));
 assert.equal(p.blob,'943e3d49f665060a2f0b71c7ffef44185d754244');
 const c=JSON.parse(p.config);
 assert.equal(c.d1_databases[0].database_id,'64e1a0ee-1455-4377-9640-3922e8f4d061');
 assert.equal(c.d1_databases[0].migrations_table,'d1_migrations');
 assert.deepEqual(executionArgs('/tmp/test/wrangler.json'),['d1','migrations','apply','holoviewer-public-v1','--remote','--config','/tmp/test/wrangler.json']);
});
test('wrangler package rejects tampered immutable migration bytes',()=>{
 const raw=readFileSync(new URL('./0002_today_canonical.sql',import.meta.url));
 assert.throws(()=>buildPlan(Buffer.concat([raw,Buffer.from('-- drift')])),/immutable Git blob drift/);
});

test('owner CLI rejects a Cloudflare account not matching production identity',()=>{
 assert.equal(validateAccountReceipt('Account ID: f5999f88acc7aa8855f0896eef5d9942'),true);
 assert.throws(()=>validateAccountReceipt('Account ID: different-account'),/account mismatch/);
});

test('machine-read D1 refuses partial or ambiguous receipts',()=>{
 assert.throws(()=>decodeD1('not json'),/unparseable/);
 assert.throws(()=>decodeD1(JSON.stringify([{success:false,results:[]}])),/untrusted/);
 assert.deepEqual(decodeD1(JSON.stringify([{success:true,results:[{name:'public_history'}]}])),[{name:'public_history'}]);
});
test('preflight hard rejects Today schema and existing migration ledger',()=>{
 const baseline=[{name:'public_catalog'},{name:'public_history'}];
 assert.equal(inspectBefore(baseline,[]),true);
 assert.throws(()=>inspectBefore([...baseline,{name:'public_today_canonical'}],[]),/conflict/);
 assert.throws(()=>inspectBefore([...baseline,{name:'d1_migrations'}],[]),/mapping review/);
});
test('postflight requires complete schema, checksum and Wrangler receipt',()=>{
 const plan=buildPlan();
 const objects=[...EXPECTED_OBJECTS,'d1_migrations'].map(name=>({name}));
 const ledger=[{migration_id:'0002_today_canonical',checksum:plan.sha256}];
 const migrations=[{name:'0001_today_canonical.sql'}];
 assert.equal(inspectAfter(objects,ledger,migrations,plan.sha256),true);
 assert.throws(()=>inspectAfter(objects.slice(1),ledger,migrations,plan.sha256),/incomplete/);
 assert.throws(()=>inspectAfter(objects,[{...ledger[0],checksum:'wrong'}],migrations,plan.sha256),/mismatch/);
 assert.throws(()=>inspectAfter(objects,ledger,[],plan.sha256),/receipt absent/);
});
test('CLI mock covers no-write preflight and successful strict postflight',async()=>{
 const plan=buildPlan();
 let writes=0;
 const queryOK=(results)=>JSON.stringify([{success:true,results}]);
 const commands=(args)=>{
   const joined=args.join(' ');
   if(args[0]==='whoami')return 'Account ID: '+plan.accountId;
   if(args[0]==='d1'&&args[1]==='migrations'&&args[2]==='apply'){writes++;return ''}
   if(joined.includes('sqlite_master'))return queryOK((writes?['public_catalog','public_history','d1_migrations',...EXPECTED_OBJECTS]:['public_catalog','public_history']).map(name=>({name})));
   if(joined.includes('public_today_schema_migrations WHERE'))return queryOK([{migration_id:'0002_today_canonical',checksum:plan.sha256}]);
   if(joined.includes('FROM d1_migrations'))return queryOK([{name:'0001_today_canonical.sql'}]);
   throw Error('unexpected command '+joined);
 };
 const outcome=await executeOwnerCli(['--apply','--approve='+plan.sha256],commands,()=>{});
 assert.equal(outcome.verified,true);assert.equal(writes,1);
 let blockedWrites=0;
 const conflict=(args)=>{if(args[0]==='whoami')return 'Account ID: '+plan.accountId;
 if(args[1]==='execute')return queryOK([{name:'public_catalog'},{name:'public_history'},{name:'public_today_canonical'}]);
 blockedWrites++;throw Error('must not migrate')};
 await assert.rejects(()=>executeOwnerCli(['--apply','--approve='+plan.sha256],conflict,()=>{}),/conflict/);
 assert.equal(blockedWrites,0);
});
test('CLI ambiguous postflight aborts with no automatic retry',async()=>{
 const plan=buildPlan();let writes=0;
 const queryOK=results=>JSON.stringify([{success:true,results}]);
 const commands=args=>{
 if(args[0]==='whoami')return 'Account ID: '+plan.accountId;
 if(args[1]==='migrations'&&args[2]==='apply'){writes++;return ''}
 if(args.join(' ').includes('sqlite_master'))return queryOK((writes?['public_catalog','public_history','d1_migrations',...EXPECTED_OBJECTS]:['public_catalog','public_history']).map(name=>({name})));
 if(args.join(' ').includes('public_today_schema_migrations WHERE'))return queryOK([]);
 throw Error('unexpected query');
 };
 await assert.rejects(()=>executeOwnerCli(['--apply','--approve='+plan.sha256],commands,()=>{}),/DO NOT RETRY/);
 assert.equal(writes,1);
});
