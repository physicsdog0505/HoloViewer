#!/usr/bin/env node
/**
 * #47 owner-executable, forward-only D1 migration via Wrangler's transactionally
 * applied migrations. DRY RUN is default; --apply requires exact digest approval.
 * Does not deploy a Worker or create a D1 database.
 */
import {readFileSync,writeFileSync,mkdtempSync,mkdirSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const SQL_PATH=fileURLToPath(new URL('./0002_today_canonical.sql',import.meta.url));
const DB_ID='64e1a0ee-1455-4377-9640-3922e8f4d061';
const ACCOUNT_ID='f5999f88acc7aa8855f0896eef5d9942';
const BLOB='943e3d49f665060a2f0b71c7ffef44185d754244';
const DB='holoviewer-public-v1';
const MID='0002_today_canonical';
const hex=(bytes,algo)=>createHash(algo).update(bytes).digest('hex');
export function buildPlan(sqlBytes=readFileSync(SQL_PATH)){
 const actualBlob=hex(Buffer.concat([Buffer.from('blob '+sqlBytes.length+'\0'),sqlBytes]),'sha1');
 if(actualBlob!==BLOB)throw Error('immutable Git blob drift: '+actualBlob);
 const sha256=hex(sqlBytes,'sha256');
 // The ledger is appended to the *same Wrangler migration transaction*.
 const sql=sqlBytes.toString('utf8')+"\nINSERT INTO public_today_schema_migrations(migration_id,checksum,applied_at) VALUES ('"+MID+"','"+sha256+"',strftime('%Y-%m-%dT%H:%M:%SZ','now'));\n";
 const config=JSON.stringify({name:'holoviewer-public-api',compatibility_date:'2026-10-14',d1_databases:[{binding:'DB',database_name:DB,database_id:DB_ID,migrations_dir:'migrations',migrations_table:'d1_migrations'}]},null,2)+'\n';
 return {sha256,blob:actualBlob,sql,config,databaseId:DB_ID,accountId:ACCOUNT_ID};
}

function invoke(args,description,{capture=false}={}){
 const result=spawnSync('npx',['wrangler',...args],{encoding:'utf8',stdio:capture?'pipe':'inherit',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
 if(result.error||result.status!==0)throw Error(description+' failed: '+(result.error?.message??result.stderr?.slice(0,300)??result.status));
 return capture?result.stdout:'';
}
export function validateAccountReceipt(output){
 if(!output.includes(ACCOUNT_ID))throw Error('authenticated Cloudflare account mismatch');return true;
}
export function executionArgs(configPath){return ['d1','migrations','apply',DB,'--remote','--config',configPath];}
export const EXPECTED_OBJECTS=Object.freeze(['public_today_schema_migrations','public_today_canonical','public_today_canonical_state','public_today_evidence','public_today_evidence_by_video','public_today_catalog_meta','public_today_approved_channels','public_today_approved_version']);
export function decodeD1(output){
 let data;
 try{data=JSON.parse(output)}catch{throw Error('unparseable D1 JSON receipt')}
 const entries=Array.isArray(data)?data:[data];
 if(!entries.length||entries.some(e=>e?.success!==true||!Array.isArray(e.results)))throw Error('untrusted D1 receipt shape');
 return entries.flatMap(e=>e.results);
}
export function inspectBefore(objects,migrations){
 const names=new Set(objects.map(x=>x.name));
 if(!names.has('public_catalog')||!names.has('public_history'))throw Error('legacy schema baseline missing');
 if(objects.some(x=>String(x.name).startsWith('public_today_')))throw Error('existing Today schema or ledger conflict');
 if(names.has('d1_migrations')){
   if(migrations.some(x=>/today_canonical/i.test(String(x.name??''))))throw Error('existing Wrangler Today migration conflict');
   // A dedicated temp migration directory starts at 0001 and therefore
   // must not run on an already initialized Wrangler tracking ledger.
   throw Error('existing Wrangler migration ledger requires independent mapping review');
 }
 return true;
}
export function inspectAfter(objects,ledger,migrations,sha256){
 const names=new Set(objects.map(x=>x.name));
 if(EXPECTED_OBJECTS.some(x=>!names.has(x)))throw Error('incomplete Today schema receipt');
 if(ledger.length!==1||ledger[0].migration_id!==MID||ledger[0].checksum!==sha256)throw Error('Today checksum ledger receipt mismatch');
 if(!names.has('d1_migrations')||!migrations.some(x=>String(x.name??'').includes('today_canonical')))throw Error('Wrangler migration receipt absent');
 return true;
}
export async function executeOwnerCli(argv,invokeCommand=invoke,log=console.log){
 const plan=buildPlan(),approve=argv.find(x=>x.startsWith('--approve='))?.slice('--approve='.length),apply=argv.includes('--apply');
 if(argv.some(x=>x!=='--apply'&&!x.startsWith('--approve=')))throw Error('unknown argument');
 if(!apply){log(JSON.stringify({mode:'DRY_RUN',source_sha256:plan.sha256,source_git_blob:plan.blob,d1_uuid:DB_ID,account_id:ACCOUNT_ID,wrangler_transactional_migrations:true},null,2));return {applied:false}}
 if(approve!==plan.sha256)throw Error('owner exact SHA-256 approval missing');
 const folder=mkdtempSync(join(tmpdir(),'issue47-today-migration-'));
 let mutationAttempted=false;
 const query=(sql,description)=>decodeD1(invokeCommand(['d1','execute',DB_ID,'--remote','--json','--command',sql],description,{capture:true}));
 const inventory="SELECT name,type FROM sqlite_master WHERE type IN ('table','index') ORDER BY type,name;";
 const migrationRows="SELECT name FROM d1_migrations ORDER BY id;";
 try{
  mkdirSync(join(folder,'migrations'));
  const config=join(folder,'wrangler.json');
  writeFileSync(config,plan.config,{mode:0o600});
  writeFileSync(join(folder,'migrations','0001_today_canonical.sql'),plan.sql,{mode:0o600});
  validateAccountReceipt(invokeCommand(['whoami'],'Cloudflare authenticated account verification',{capture:true}));
  const before=query(inventory,'preflight immutable D1 inventory');
  const hasMigrations=before.some(x=>x.name==='d1_migrations');
  inspectBefore(before,hasMigrations?query(migrationRows,'preflight Wrangler ledger'):[]);
  log('OWNER-GATED migration to '+DB_ID+' with source SHA '+plan.sha256);
  mutationAttempted=true;
  invokeCommand(executionArgs(config),'transactional Wrangler D1 migration');
  const objects=query(inventory,'postflight D1 inventory');
  const ledger=query("SELECT migration_id,checksum,applied_at FROM public_today_schema_migrations WHERE migration_id='"+MID+"';",'postflight Today checksum ledger');
  const migrations=query(migrationRows,'postflight Wrangler migration ledger');
  inspectAfter(objects,ledger,migrations,plan.sha256);
  log('MIGRATION VERIFIED: '+MID);
  return {applied:true,verified:true};
 }catch(error){
  if(mutationAttempted)throw Error('PRODUCTION MUTATION MAY HAVE OCCURRED; DO NOT RETRY. '+error.message);
  throw error;
 }finally{rmSync(folder,{force:true,recursive:true})}
}
export function run(argv=process.argv.slice(2)){return executeOwnerCli(argv);}

if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]){try{run()}catch(err){console.error(err.message);process.exitCode=1}}
