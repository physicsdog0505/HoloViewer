import test from 'node:test';
import assert from 'node:assert/strict';
import {refreshTodayDiscovery} from './worker_host/today/discovery-refresh.mjs';
import {mountTodayCadence} from './worker_host/today/cadence-refresh.mjs';

test('Today discovery is explicitly disabled by default and performs no network',async()=>{
  let calls=0;
  const out=await refreshTodayDiscovery({},{
    fetchImpl:async()=>{calls++;throw Error('must not call network')}
  });
  assert.deepEqual(out,{
    status:'disabled',feed_requests:0,channels:0,discovered:0,updated:0
  });
  assert.equal(calls,0);
});

test('combined cadence preserves existing fetch contract with discovery disabled',async()=>{
  const base={async fetch(){return new Response('same',{status:206})}};
  const worker=mountTodayCadence(base,{fetchImpl:async()=>{throw Error('network')}});
  const response=await worker.fetch(new Request('https://api.example/v1/catalog/today'),{});
  assert.equal(response.status,206);
  assert.equal(await response.text(),'same');
});

test('discovery source stays bounded and uses no search.list',async()=>{
  const source=await import('node:fs/promises').then(fs=>
    fs.readFile(new URL('./worker_host/today/discovery-refresh.mjs',import.meta.url),'utf8'));
  assert.match(source,/CHANNELS_PER_WAVE=10/);
  assert.match(source,/WAVES_PER_RUN=3/);
  assert.match(source,/videos\/v3\/videos/);
  assert.doesNotMatch(source,/search\.list/);
  assert.doesNotMatch(source,/youtube\/v3\/search/);
});
