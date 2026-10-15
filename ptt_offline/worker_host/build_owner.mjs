#!/usr/bin/env node
// #48 owner API bundle dry-run for the EXISTING holoviewer-public-api.
// Caller supplies a confirmed copy of current Wrangler config; never
// silently replaces deployed bindings, variables or existing routes.
import {readFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const EXPECTED_DB_ID='64e1a0ee-1455-4377-9640-3922e8f4d061';
const ENTRY=fileURLToPath(new URL('./index.mjs',import.meta.url));
export function validateExistingConfig(config) {
 if(config?.name!=='holoviewer-public-api')throw Error('existing API Worker name required');
 const db=(config.d1_databases||[]).find(x=>x.binding==='DB');
 if(db?.database_id!==EXPECTED_DB_ID||db.database_name!=='holoviewer-public-v1')
   throw Error('existing D1 identity mismatch');
 const hasOrigin=Object.prototype.hasOwnProperty.call(config.vars??{},'ALLOWED_ORIGIN');
 if(hasOrigin && (typeof config.vars.ALLOWED_ORIGIN!=='string'||!config.vars.ALLOWED_ORIGIN.trim()))
   throw Error('invalid existing ALLOWED_ORIGIN value; do not invent replacement');
 if(config.vars?.PTT_PUBLISH_ENABLED==='true')
   throw Error('build must not silently enable Publisher');
 if(config.main && resolve(config.main)===ENTRY)
   throw Error('do not overwrite accepted owner source config automatically');
 return {worker:config.name,database_id:db.database_id,
   cors_preserved:true,cors_origin_mode:hasOrigin?'configured':'absent_preserved',publisher_default_off:true};
}
export function build(args=process.argv.slice(2),invoke=(bin,argv)=>{
 const r=spawnSync(bin,argv,{stdio:'inherit',env:{...process.env,WRANGLER_SEND_METRICS:'false'}});
 if(r.error||r.status!==0)throw Error('Wrangler dry-run bundle failed');
}) {
 if(args.length!==4||args[0]!=='--existing-config'||args[2]!=='--outdir')
   throw Error('usage: --existing-config confirmed-wrangler.json --outdir output-directory');
 const source=resolve(args[1]),destination=resolve(args[3]);
 const config=JSON.parse(readFileSync(source,'utf8'));
 const receipt=validateExistingConfig(config);
 mkdirSync(destination,{recursive:true});
 invoke('npx',['wrangler','deploy',ENTRY,'--name','holoviewer-public-api',
   '--config',source,'--dry-run','--outdir',destination]);
 return {...receipt,mode:'BUNDLE_DRY_RUN_ONLY',entry:ENTRY,outdir:destination,
   deployed:false};
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
 try{console.log(JSON.stringify(build(),null,2))}
 catch(error){console.error(error.message);process.exitCode=1}
}
