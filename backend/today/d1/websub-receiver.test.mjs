import test from 'node:test';
import assert from 'node:assert/strict';
import {handleWebSub,topicForChannel} from './websub-receiver.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk',secret='test-secret',roster={version:'approved-20261016',channels:[{id:C}]};
const base='https://api.example/internal/today/websub';
const atom=`<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"><entry><yt:videoId>${V}</yt:videoId><yt:channelId>${C}</yt:channelId></entry></feed>`;
async function signature(raw){const enc=new TextEncoder();const k=await crypto.subtle.importKey('raw',enc.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);return 'sha256='+Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',k,enc.encode(raw))),b=>b.toString(16).padStart(2,'0')).join('')}
test('WebSub challenge only for approved topic, mode and lease',async()=>{
 const uri=base+'?hub.mode=subscribe&hub.topic='+encodeURIComponent(topicForChannel(C))+'&hub.challenge=verified&hub.lease_seconds=86400';
 const ok=await handleWebSub(new Request(uri),{roster,secret,saveEvent:async()=>{}});
 assert.equal(ok.status,200);assert.equal(await ok.text(),'verified');
 const bad=await handleWebSub(new Request(uri.replace('verified','verified').replace('hub.mode=subscribe','hub.mode=invalid')),{roster,secret,saveEvent:async()=>{}});
 assert.equal(bad.status,403);
});
test('valid signed Atom delivery persists before 204 ACK; bad signature does not persist',async()=>{
 const events=[];
 const req=async sig=>new Request(base,{method:'POST',headers:{'x-hub-signature-256':sig},body:atom});
 const bad=await handleWebSub(await req('sha256='+'0'.repeat(64)),{roster,secret,saveEvent:async x=>events.push(x)});
 assert.equal(bad.status,401);assert.equal(events.length,0);
 const ok=await handleWebSub(await req(await signature(atom)),{roster,secret,saveEvent:async x=>events.push(x)});
 assert.equal(ok.status,204);assert.equal(events[0].video_id,V);assert.equal(events[0].roster_version,roster.version);
 const fail=await handleWebSub(await req(await signature(atom)),{roster,secret,saveEvent:async()=>{throw Error('D1 unavailable')}});
 assert.equal(fail.status,503);
});

test('classic PubSubHubbub SHA1 signature is accepted',async()=>{
 const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-1'},false,['sign']);
 const hex=Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(atom))),b=>b.toString(16).padStart(2,'0')).join('');
 const saved=[];
 const result=await handleWebSub(new Request(base,{method:'POST',headers:{'x-hub-signature':'sha1='+hex},body:atom}),{roster,secret,saveEvent:async x=>saved.push(x)});
 assert.equal(result.status,204);assert.equal(saved.length,1);
});
