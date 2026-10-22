import test from 'node:test';
import assert from 'node:assert/strict';
import {signature,handleTodayPrivatePost,mountTodayPublisherOnCombinedApi} from './today-private-post.mjs';
const secret='test-secret';
const when=1792080000000;
function req(body,stamp=String(when),mac='0'.repeat(64)){return new Request('https://api.example/internal/today/one-shot',{method:'POST',headers:{'x-today-timestamp':stamp,'x-today-signature':mac},body});}
test('private signed path rejects disabled, stale, malformed and bad signatures before touching D1',async()=>{
 const payload='{"receipt":{}}';
 const DB={prepare(){throw Error('D1 must not be touched')}};
 const env={DB,TODAY_PUBLISH_HMAC_SECRET:secret,TODAY_PUBLISH_ENABLED:'true'};
 assert.equal((await handleTodayPrivatePost(req(payload),{DB},{now:when})).status,503);
 assert.equal((await handleTodayPrivatePost(req(payload,'123'),env,{now:when})).status,401);
 assert.equal((await handleTodayPrivatePost(req(payload),env,{now:when})).status,401);
 const valid=await signature(secret,String(when),payload);
 assert.equal((await handleTodayPrivatePost(req(payload,String(when),valid),env,{now:when})).status,409);
 assert.notEqual(valid,await signature(secret,String(when),payload+' '));
});

test('mounted Today handler preserves combined legacy and PTT routes and blocks unsigned writes',async()=>{
 const existing={async fetch(request){return new Response(new URL(request.url).pathname,{status:200})}};
 const mounted=mountTodayPublisherOnCombinedApi(existing);
 const legacy=await mounted.fetch(new Request('https://api.example/v1/history'),{});
 assert.equal(await legacy.text(),'/v1/history');
 const ptt=await mounted.fetch(new Request('https://api.example/internal/ptt/publish',{method:'POST'}),{});
 assert.equal(await ptt.text(),'/internal/ptt/publish');
 const disabled=await mounted.fetch(req('{"receipt":{}}'),{});
 assert.equal(disabled.status,503);
});
