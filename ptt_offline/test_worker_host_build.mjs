import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {validateExistingConfig,build} from './worker_host/build_owner.mjs';
const config={name:'holoviewer-public-api',
 d1_databases:[{binding:'DB',database_name:'holoviewer-public-v1',
  database_id:'64e1a0ee-1455-4377-9640-3922e8f4d061'}],
 vars:{ALLOWED_ORIGIN:'https://holoviewer.example',PTT_PUBLISH_ENABLED:'false'}};
test('one existing API Worker and DB required; Publisher not automatically enabled',()=>{
 assert.equal(validateExistingConfig(config).publisher_default_off,true);
 assert.throws(()=>validateExistingConfig({...config,name:'new-worker'}),/existing API Worker/);
 assert.throws(()=>validateExistingConfig({...config,vars:{ALLOWED_ORIGIN:''}}),/ALLOWED_ORIGIN/);
 assert.throws(()=>validateExistingConfig({...config,vars:{...config.vars,PTT_PUBLISH_ENABLED:'true'}}),/silently enable/);
});
test('build invokes only existing-worker Wrangler dry run',()=>{
 const dir=mkdtempSync(join(tmpdir(),'ptt48-host-test-'));
 try{
  const source=join(dir,'current.json');writeFileSync(source,JSON.stringify(config));
  let seen;
  const receipt=build(['--existing-config',source,'--outdir',join(dir,'bundle')],
    (bin,args)=>{seen={bin,args};});
  assert.equal(receipt.deployed,false);
  assert.equal(seen.bin,'npx');
  assert.ok(seen.args.includes('--dry-run'));
  assert.ok(seen.args.includes('--outdir'));
  assert.equal(seen.args.includes('--remote'),false);
  assert.equal(seen.args[seen.args.indexOf('--name')+1],'holoviewer-public-api');
 }finally{rmSync(dir,{recursive:true,force:true})}
});
