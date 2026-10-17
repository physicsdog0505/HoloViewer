import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('known-row lifecycle removes processed discovery rows without livestream evidence',()=>{
  const source=fs.readFileSync(new URL('./worker_host/today/cadence-refresh.mjs',import.meta.url),'utf8');
  assert.match(source,/from_discovery/);
  assert.match(source,/hasLivestreamEvidence/);
  assert.match(source,/DELETE FROM public_today_canonical WHERE video_id=\?/);
  assert.match(source,/removed_non_live/);
});

test('discovery remains disabled in production release config',()=>{
  const source=fs.readFileSync(new URL('./deploy_today_backend_release.py',import.meta.url),'utf8');
  assert.match(source,/TODAY_DISCOVERY_ENABLED"\]="false"/);
});
