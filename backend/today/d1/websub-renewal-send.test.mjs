import test from 'node:test';import assert from 'node:assert/strict';import {renewSubscriptions} from './websub-renewal-send.mjs';
const C='UC'+'A'.repeat(22),roster={version:'v1',channels:[{id:C}]};
test('default no-network, signed hub request only with explicit activation',async()=>{
 const off=await renewSubscriptions({roster,leases:[],post:async()=>{throw Error('must not call')}});
 assert.equal(off.sent,0);assert.equal(off.status,'DISABLED');
 let sent=0;const on=await renewSubscriptions({roster,leases:[],enabled:true,callback:'https://api.example/internal/today/websub',secret:'s'.repeat(32),
  post:async (url,body)=>{sent++;assert.equal(url,'https://pubsubhubbub.appspot.com/subscribe');assert.equal(body.get('hub.topic').includes(C),true);return {status:202}}});
 assert.equal(sent,1);assert.equal(on.status,'SUBMITTED_PENDING_CHALLENGE');
});
test('hub rejection stops subsequent subscriptions',async()=>{
 const list={version:'v1',channels:[{id:C},{id:'UC'+'B'.repeat(22)}]};
 let calls=0;const x=await renewSubscriptions({roster:list,leases:[],enabled:true,callback:'https://api.example/internal/today/websub',
  secret:'s'.repeat(32),post:async()=>{calls++;return {status:500}}});
 assert.equal(calls,1);assert.equal(x.status,'STOP_REVIEW');
});
