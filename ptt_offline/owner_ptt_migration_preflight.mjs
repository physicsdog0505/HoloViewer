#!/usr/bin/env node
// #48 existing D1 identity + immutable migration preparation.
// Offline default; --inspect only issues read-only Wrangler commands.
// Never modifies existing Today objects, migrations or production D1.
import {readFileSync,writeFileSync,mkdtempSync,rmSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const FILE=fileURLToPath(new URL('./d1_migrations/0001_canonical_ptt.sql',import.meta.url));
const MANIFEST=fileURLToPath(new URL('./d1_migrations/manifest.json',import.meta.url));
export const DB='holoviewer-public-v1';
export const UUID='64e1a0ee-1455-4377-9640-3922e8f4d061';
export const ACCOUNT='f5999f88acc7aa8855f0896eef5d9942';
const digest=(value,algo)=>createHash(algo).update(value).digest('hex');
export function planMigration(bytes=readFileSync(FILE), manifest=JSON.parse(readFileSync(MANIFEST,'utf8'))) {
 const entry=manifest.immutable_migrations?.[0];
 const sha256=digest(bytes,'sha256');
 const blob=digest(Buffer.concat([Buffer.from('blob '+bytes.length+'\0'),bytes]),'sha1');
 if(entry?.version!==1 || entry?.sha256!==sha256 ||
    entry?.git_blob_sha!==blob || entry?.bytes!==bytes.length ||
    manifest.target_database!==DB || manifest.binding!=='DB')
   throw Error('immutable PTT migration receipt mismatch');
 return {database:DB,uuid:UUID,account:ACCOUNT,sha256,blob,
   sqlBytes:bytes.length,existingTodayPreserved:true,
   status:'PREPARED_NOT_APPLIED'};
}
export function assertInventory(rows) {
 if(!Array.isArray(rows))throw Error('invalid D1 inventory');
 const names=new Set(rows.map(r=>r.name));
 if(!names.has('public_catalog')||!names.has('public_history'))
   throw Error('missing existing legacy D1 tables');
 if(!names.has('public_today_schema_migrations'))
   throw Error('previously applied Today migration not present');
 const existing=['ptt_threads','ptt_pushes','ptt_source_evidence',
   'ptt_provider_state','ptt_gap_repairs','public_ptt_schema_migrations'];
 const present=existing.filter(name=>names.has(name));
 if(present.length!==0&&present.length!==existing.length)
   throw Error('partially applied PTT schema: manual review required');
 return {pttSchemaPresent:present.length===existing.length,
   todayPresent:true,legacyPreserved:true,
   wranglerLedgerPresent:names.has('d1_migrations')};
}
export function verifyAppliedPttLedger(rows,inventory) {
 if(!inventory?.pttSchemaPresent)return {applied:false,verified:false};
 if(!Array.isArray(rows)||rows.length!==1||rows[0]?.version!==1)
   throw Error('PTT applied schema ledger missing or unexpected');
 return {applied:true,verified:true,version:1};
}
export function assertWranglerLedger(rows,{pttApplied=false}={}) {
 if(!Array.isArray(rows)||!rows.some(row=>row.name==='0001_today_canonical.sql'))
   throw Error('expected applied Today Wrangler migration identity missing');
 const hasPtt=rows.some(row=>row.name==='0002_canonical_ptt.sql');
 if(hasPtt!==pttApplied)throw Error('PTT Wrangler migration ledger out of sync');
 return true;
}
export function decodeD1(value) {
 const items=JSON.parse(value);
 const groups=Array.isArray(items)?items:[items];
 if(!groups.length||groups.some(g=>g?.success!==true||!Array.isArray(g.results)))
   throw Error('invalid Cloudflare D1 receipt');
 return groups.flatMap(g=>g.results);
}
function invoke(args) {
 const mutation=args[0]==='d1'&&args[1]==='migrations'&&args[2]==='apply';
 const result=spawnSync('npx',['wrangler',...args],{
   encoding:'utf8',stdio:mutation?'inherit':'pipe',
   env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
 if(result.error||result.status!==0)
   throw Error('Wrangler command failed; inspect remote state before retry: '+(result.stderr?.slice(0,200)??result.status));
 return result.stdout;
}
export function run(argv=process.argv.slice(2),exec=invoke,print=console.log) {
 const apply=argv.includes('--apply');
 const approve=argv.find(a=>a.startsWith('--approve='))?.slice(10);
 if(argv.some(a=>a!=='--inspect'&&a!=='--apply'&&!a.startsWith('--approve=')) ||
    (apply&&argv.includes('--inspect')))throw Error('invalid migration arguments');
 const plan=planMigration();
 if(!apply&&!argv.includes('--inspect')){print(JSON.stringify(plan,null,2));return plan;}
 if(apply&&approve!==plan.sha256)throw Error('exact owner checksum approval required');
 const whoami=exec(['whoami']);
 if(!whoami.includes(ACCOUNT))throw Error('Cloudflare account mismatch');
 const objects=decodeD1(exec(['d1','execute',UUID,'--remote','--json',
   '--command',"SELECT name,type FROM sqlite_master WHERE type IN ('table','index') ORDER BY name;"]));
 const inspection=assertInventory(objects);
 if(!inspection.wranglerLedgerPresent)throw Error('existing Wrangler migration ledger missing');
 const oldLedger=decodeD1(exec(['d1','execute',UUID,'--remote','--json','--command',
   'SELECT name FROM d1_migrations ORDER BY id;']));
 assertWranglerLedger(oldLedger,{pttApplied:inspection.pttSchemaPresent});
 let applied={applied:false,verified:false};
 if(inspection.pttSchemaPresent) {
   const ledger=decodeD1(exec(['d1','execute',UUID,'--remote','--json','--command',
     'SELECT version,description FROM public_ptt_schema_migrations ORDER BY version;']));
   applied=verifyAppliedPttLedger(ledger,inspection);
 }
 const receipt={...plan,mode:'READ_ONLY_ACCOUNT_PREFLIGHT',...inspection,...applied};
 if(apply&&!inspection.wranglerLedgerPresent)throw Error('existing Wrangler ledger required for controlled migration');
 if(!apply){print(JSON.stringify(receipt,null,2));return receipt;}
 if(inspection.pttSchemaPresent)throw Error('PTT migration already applied; do not rerun');
 // Wrangler's existing Today ledger has an applied 0001_today_canonical.sql.
 // Retain that name in this temporary migration directory, so migrations apply
 // only the NEW 0002 PTT file without replaying Today or resetting the ledger.
 const dir=mkdtempSync(join(tmpdir(),'ptt48-d1-'));
 const migrations=join(dir,'migrations');
 const file=join(migrations,'0002_canonical_ptt.sql');
 let mutationAttempted=false;
 try{
   mkdirSync(migrations);
   writeFileSync(join(migrations,'0001_today_canonical.sql'),'-- previously applied Today migration; must never execute again\n',{mode:0o600});
   writeFileSync(file,readFileSync(FILE),{mode:0o600});
   const config=join(dir,'wrangler.json');
   writeFileSync(config,JSON.stringify({name:'holoviewer-public-api',compatibility_date:'2026-10-14',d1_databases:[{binding:'DB',database_name:DB,database_id:UUID,migrations_dir:'migrations',migrations_table:'d1_migrations'}]}),{mode:0o600});
   mutationAttempted=true;
   exec(['d1','migrations','apply',DB,'--remote','--config',config]);
   const after=decodeD1(exec(['d1','execute',UUID,'--remote','--json',
     '--command',"SELECT name,type FROM sqlite_master WHERE type IN ('table','index') ORDER BY name;"]));
   const state=assertInventory(after);
   const ledger=decodeD1(exec(['d1','execute',UUID,'--remote','--json',
     '--command','SELECT version,description FROM public_ptt_schema_migrations ORDER BY version;']));
   const newLedger=decodeD1(exec(['d1','execute',UUID,'--remote','--json',
     '--command','SELECT name FROM d1_migrations ORDER BY id;']));
   assertWranglerLedger(newLedger,{pttApplied:true});
   const verified=verifyAppliedPttLedger(ledger,state);
   if(!verified.verified)throw Error('postflight PTT ledger not verified');
   const result={...receipt,...verified,mode:'OWNER_APPLIED_VERIFIED'};
   print(JSON.stringify(result,null,2));return result;
 }catch(error){
   if(mutationAttempted)throw Error('REMOTE MUTATION MAY HAVE OCCURRED; STOP, INSPECT, DO NOT RETRY: '+error.message);
   throw error;
 }finally{rmSync(dir,{force:true,recursive:true});}
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 try{run()}catch(error){console.error(error.message);process.exitCode=1}
}
