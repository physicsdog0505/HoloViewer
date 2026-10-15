// Offline-only #47 release source fingerprint and #45 canary contract preflight.
// No network, Cloudflare auth, D1, or production mutation.
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const pins={
 'backend/today/d1/0002_today_canonical.sql':'943e3d49f665060a2f0b71c7ffef44185d754244',
 'backend/today/d1/api-shell.mjs':'70f61d0a0a454bc305d5cb666ce28485ea6d8ed7',
 'backend/today/d1/migrate.mjs':'33a9dae21302ac05f63b7f9ad21ef920350a41b9',
 'backend/today/d1/store.mjs':'8a1127cc3a785598be6bb4c7596b19a9afe25487'
};
export const firstWindow={httpMax:5,d1QueriesMax:12,rowsReadMax:1000,rowsWritten:0,retries:0};
export function inspectRelease(rootPath=new URL('../../../',import.meta.url)){
 const actual={};
 for(const [file,expected] of Object.entries(pins)){
  const bytes=readFileSync(new URL(file,rootPath));
  const blob=createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
  if(blob!==expected)throw Error(`reviewed source fingerprint drift: ${file}: ${blob}`);
  actual[file]=blob;
 }
 const sql=readFileSync(new URL('backend/today/d1/0002_today_canonical.sql',rootPath));
 const sha256=createHash('sha256').update(sql).digest('hex');
 const runbook=readFileSync(new URL('backend/today/d1/PRODUCTION_EXECUTION_RUNBOOK.md',rootPath),'utf8');
 const canary=runbook.split('## E. Unified hosted read-only canary')[1]?.split('## F. Later ingestion activation')[0];
 if(!canary)throw Error('runbook unified canary section missing');
 for(const needle of ['HTTP requests <= 5','D1 queries <= 12','Rows Read delta <= 1,000','Rows Written exactly 0','automatic retries 0','/v1/ptt/history?day=<same>&limit=1&after=']){
  if(!(needle==='D1 queries <= 12' ? /D1 queries <= 12(?![0-9])/.test(canary) : canary.includes(needle)))throw Error(`runbook canary constraint missing: ${needle}`);
 }
 return {result:'OFFLINE_PREFLIGHT_PASS',source_blobs:actual,migration_sha256:sha256,first_window:firstWindow,production_mutation:false};
}
if(process.argv[1] && import.meta.url===new URL('file://'+process.argv[1]).href){
 console.log(JSON.stringify(inspectRelease(),null,2));
}
