import test from 'node:test';
import assert from 'node:assert/strict';
import {handleOwnerPttPublish} from './d1_owner_dispatch.mjs';
const request=(method='POST',body='{}')=>new Request('https://worker.example/private/ptt/publish',
 {method,headers:{'content-type':'application/json'},body:method==='POST'?body:undefined});
test('disabled by default even with credentials',async()=>{
 const r=await handleOwnerPttPublish(request(),{DB:{batch(){throw Error('write')}}},{authorize:()=>true,verifyAuthority:()=>true});
 assert.equal(r.status,503);
});
test('denies missing independent authority without mutation',async()=>{
 const r=await handleOwnerPttPublish(request(),{PTT_PUBLISH_ENABLED:'true',DB:{batch(){throw Error('write')}}},{});
 assert.equal(r.status,503);
});
test('denies unauthenticated input without mutation',async()=>{
 const r=await handleOwnerPttPublish(request(),{PTT_PUBLISH_ENABLED:'true',DB:{batch(){throw Error('write')}}},
   {authorize:()=>false,verifyAuthority:()=>true});
 assert.equal(r.status,401);
});
test('invalid payload returns controlled error',async()=>{
 const r=await handleOwnerPttPublish(request('POST','{bad'),{PTT_PUBLISH_ENABLED:'true',DB:{batch(){throw Error('write')}}},
 {authorize:()=>true,verifyAuthority:()=>true});
 assert.equal(r.status,400);
});
