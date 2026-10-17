import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {authorizePttHmac} from './ptt_owner_hmac.mjs';
const te=new TextEncoder();
const secret='production-like-secret-32-character-minimum';
async function headers(body,stamp) {
 const key=await webcrypto.subtle.importKey('raw',te.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const output=await webcrypto.subtle.sign('HMAC',key,te.encode(stamp+'\n'+body));
 return {'x-ptt-timestamp':stamp,'x-ptt-signature':Buffer.from(output).toString('hex')};
}
test('correct HMAC over exact source body',async()=>{
 const body='{"day":"2026-10-15"}',stamp='1792069200000';
 const request=new Request('https://example.test',{headers:await headers(body,stamp)});
 assert.equal(await authorizePttHmac(request,{PTT_PUBLISH_HMAC_SECRET:secret},body,{nowMs:Number(stamp)}),true);
 assert.equal(await authorizePttHmac(request,{PTT_PUBLISH_HMAC_SECRET:secret},body+' ',{nowMs:Number(stamp)}),false);
});
test('reject missing secret, old timestamp and header forgery',async()=>{
 const body='{}',stamp='1792069200000';
 const request=new Request('https://example.test',{headers:await headers(body,stamp)});
 assert.equal(await authorizePttHmac(request,{},body,{nowMs:Number(stamp)}),false);
 assert.equal(await authorizePttHmac(request,{PTT_PUBLISH_HMAC_SECRET:secret},body,{nowMs:Number(stamp)+61000}),false);
 const forged=new Request('https://example.test',{headers:{'x-ptt-timestamp':stamp,'x-ptt-signature':'0'.repeat(64)}});
 assert.equal(await authorizePttHmac(forged,{PTT_PUBLISH_HMAC_SECRET:secret},body,{nowMs:Number(stamp)}),false);
});
