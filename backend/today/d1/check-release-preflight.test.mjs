import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectRelease,firstWindow} from './check-release-preflight.mjs';
test('reviewed source fingerprints and #45 frozen canary are stable',()=>{
 const receipt=inspectRelease();
 assert.equal(receipt.result,'OFFLINE_PREFLIGHT_PASS');
 assert.equal(receipt.production_mutation,false);
 assert.match(receipt.migration_sha256,/^[0-9a-f]{64}$/);
 assert.deepEqual(firstWindow,{httpMax:5,d1QueriesMax:12,rowsReadMax:1000,rowsWritten:0,retries:0});
});
