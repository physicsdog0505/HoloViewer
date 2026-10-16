import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const c=JSON.parse(readFileSync(new URL('./wrangler.api-candidate.json',import.meta.url),'utf8'));
test('API deployment candidate points solely to the existing API Worker and canonical D1 binding',()=>{
 assert.equal(c.name,'holoviewer-public-api');
 assert.equal(c.main,'./api-worker-entry.mjs');
 assert.deepEqual(c.d1_databases,[{binding:'DB',database_name:'holoviewer-public-v1',database_id:'64e1a0ee-1455-4377-9640-3922e8f4d061'}]);
 for(const k of ['triggers','routes','migrations_dir','vars','kv_namespaces','r2_buckets','services'])assert.equal(Object.hasOwn(c,k),false,k);
});
