import test from 'node:test';import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';import {readFileSync} from 'node:fs';
import {refreshChannelProfiles,fetchYouTubeChannels} from './channel-profile-refresh.mjs';
const C='UC'+'A'.repeat(22),D='UC'+'B'.repeat(22);
const raw=new DatabaseSync(':memory:');
raw.exec(readFileSync(new URL('./websub-event-queue.PROPOSED.sql',import.meta.url),'utf8'));
raw.exec(readFileSync(new URL('./websub-hardening.PROPOSED.sql',import.meta.url),'utf8'));
const db={prepare(s){return {bind(...a){return {run:async()=>raw.prepare(s).run(...a)}}}}};
const roster={version:'v85',channels:[{id:C},{id:D}]};
test('bounded profile fetch stores exact approved channel avatars and pages',async()=>{
 const first=await refreshChannelProfiles({db,roster,limit:1,fetchChannels:async ids=>ids.map(id=>({id,snippet:{title:'Test Channel',thumbnails:{default:{url:'https://yt3.ggpht.com/a'}}}}))});
 assert.equal(first.has_more,true);assert.equal(first.stored,1);
 const second=await refreshChannelProfiles({db,roster,offset:1,limit:1,fetchChannels:async ids=>ids.map(id=>({id,snippet:{title:'Next Channel'}}))});
 assert.equal(second.has_more,false);
 assert.equal(raw.prepare('SELECT COUNT(*) n FROM public_today_channel_profiles').get().n,2);
});
test('partial provider response refuses phantom channel',async()=>{
 await assert.rejects(()=>refreshChannelProfiles({db,roster,fetchChannels:async()=>[]}),/partial/);
});
test('YouTube channels.list remains read-only bounded request',async()=>{
 let calls=0;const items=await fetchYouTubeChannels([C],'sample',{fetchImpl:async url=>{
 calls++;assert.equal(new URL(url).searchParams.get('part'),'snippet');
 return {ok:true,json:async()=>({items:[{id:C}]})};
 }});assert.equal(calls,1);assert.equal(items[0].id,C);
});
