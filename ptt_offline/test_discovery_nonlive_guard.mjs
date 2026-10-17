import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('discovery rejects ordinary uploads before canonical write',()=>{
  const source=fs.readFileSync(new URL('./worker_host/today/websub-status.mjs',import.meta.url),'utf8');
  const evidence=source.indexOf('const hasLivestreamEvidence');
  const ignored=source.indexOf('ignored_non_live++');
  const write=source.indexOf('await writeEvidence');
  assert.ok(evidence>=0);
  assert.ok(ignored>evidence);
  assert.ok(write>ignored);
  assert.match(source,/liveBroadcastContent==='live'/);
  assert.match(source,/liveBroadcastContent==='upcoming'/);
  assert.match(source,/scheduled \|\| start \|\| end/);
});

test('production cleanup is tightly scoped to processed post-rollout unknown rows',()=>{
  const sql=fs.readFileSync(new URL('./worker_host/today/cleanup-discovery-nonlive.sql',import.meta.url),'utf8');
  assert.match(sql,/status='processed'/);
  assert.match(sql,/lifecycle_state='unknown'/);
  assert.match(sql,/scheduled_start IS NULL/);
  assert.match(sql,/actual_start IS NULL/);
  assert.match(sql,/actual_end IS NULL/);
  assert.match(sql,/2026-10-15T22:22:00Z/);
});
