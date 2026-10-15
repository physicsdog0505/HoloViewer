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
function invoke(args,description){
 const result=spawnSync('npx',['wrangler',...args],{encoding:'utf8',stdio:'inherit',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
 if(result.error||result.status!==0)throw Error(description+' failed: '+(result.error?.message??result.status));
}
export function executionArgs(configPath){
 return ['d1','migrations','apply',DB,'--remote','--config',configPath];
}
export function run(argv=process.argv.slice(2)){
 const plan=buildPlan(),approve=argv.find(x=>x.startsWith('--approve='))?.slice('--approve='.length),apply=argv.includes('--apply');
 if(argv.some(x=>x!=='--apply'&&!x.startsWith('--approve=')))throw Error('unknown argument');
 if(!apply){console.log(JSON.stringify({mode:'DRY_RUN',source_sha256:plan.sha256,source_git_blob:plan.blob,d1_uuid:DB_ID,account_id:ACCOUNT_ID,wrangler_transactional_migrations:true},null,2));return}
 if(approve!==plan.sha256)throw Error('owner exact SHA-256 approval missing (use --apply --approve=<printed_sha256>)');
 const folder=mkdtempSync(join(tmpdir(),'issue47-today-migration-'));
 try{
  mkdirSync(join(folder,'migrations'));
  const config=join(folder,'wrangler.json');
  writeFileSync(config,plan.config,{mode:0o600});
  writeFileSync(join(folder,'migrations','0001_today_canonical.sql'),plan.sql,{mode:0o600});
  // Verify existing account/session and schema BEFORE any write. UUID, never name.
  invoke(['whoami'],'Cloudflare authenticated account verification');
  invoke(['d1','execute',DB_ID,'--remote','--command',"SELECT name,type FROM sqlite_master WHERE type IN ('table','index') ORDER BY type,name;"],'pre-migration read-only inventory');
  console.log('OWNER-GATED production mutation: database '+DB_ID+'; source sha256 '+plan.sha256);
  invoke(executionArgs(config),'transactional Wrangler D1 migration');
  invoke(['d1','execute',DB_ID,'--remote','--command',"SELECT migration_id,checksum,applied_at FROM public_today_schema_migrations WHERE migration_id='"+MID+"';"],'post-migration ledger read');
  invoke(['d1','execute',DB_ID,'--remote','--command',"SELECT name,type FROM sqlite_master WHERE name LIKE 'public_today_%' ORDER BY name;"],'post-migration schema read');
 }finally{rmSync(folder,{force:true,recursive:true})}
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]){try{run()}catch(err){console.error(err.message);process.exitCode=1}}
