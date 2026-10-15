import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {buildPlan,executionArgs,validateAccountReceipt} from './owner-wrangler-migration.mjs';
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
