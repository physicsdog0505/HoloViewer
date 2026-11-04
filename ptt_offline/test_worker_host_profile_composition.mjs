import test from 'node:test';
import assert from 'node:assert/strict';

import host from './worker_host/index.mjs';

const known='UC'+'A'.repeat(22);
const unknown='UC'+'Z'.repeat(22);
const pttRow={
 push_id:'ptt-row',aid:'aid-day',day:'2026-11-03',source_line:1,kind:'推',
 author:'viewer',content:'fixture',occurred_at:'2026-11-03T01:00:00Z',floor:1,
 source_url:'https://www.ptt.cc'
};

function compositionDb(){
 let writes=0;
 return {
  get writes(){return writes;},
  prepare(sql){
   if(/\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP)\b/i.test(sql)){
    writes+=1;
    throw new Error('unexpected write');
   }
   const execute=(args=[])=>({
    async all(){
     if(sql.includes('FROM public_channel_profiles'))return {results:[{
      channel_id:known,channel_name:'Known Channel',display_name:'Known Display',
      avatar_url:'https://yt3.ggpht.com/'+known,channel_group:'hololive',
      member_accent:'#123456',member_accent_dual:null,support_mode:'solid',
      support_color_source:'canonical',profile_revision:'pr235-fixture',
      updated_at:'2026-10-25T00:00:00Z'
     }]};
     if(sql.includes('FROM ptt_provider_state'))return {results:[{
      aid:'aid-day',last_success_at:'2026-11-03T01:00:10Z',has_gap:0
     }]};
     if(sql.includes('FROM ptt_threads'))return {results:[{aid:'aid-day'}]};
     if(sql.includes('FROM ptt_pushes')){
      const requestedDay=args[0];
      return {results:requestedDay===pttRow.day?[pttRow]:[]};
     }
     return {results:[]};
    },
    async first(){
     if(sql.includes('public_today_catalog_meta'))return {
      roster_version:'v85',last_success_at:'2026-11-03T01:00:10Z',
      expected_channels:85,scanned_channels:85,gap:0,checkpoint:'fixture'
     };
     return null;
    }
   });
   return {
    ...execute(),
    bind(...args){return execute(args);}
   };
  }
 };
}

const request=path=>new Request('https://public-api.example'+path);

test('actual PTT composition retains PR235 batch profile route and accepted unknown contract',async()=>{
 const DB=compositionDb();
 const response=await host.fetch(request(
  '/v1/channels/profiles?id='+known+'&id='+known+'&id='+unknown
 ),{DB});
 assert.equal(response.status,200);
 const body=await response.json();
 assert.equal(body.schema_version,'holoviewer-channel-profiles-v1');
 assert.deepEqual(body.profiles.map(row=>row.channel_id),[known,unknown]);
 assert.equal(body.profiles[0].avatar_url,'https://yt3.ggpht.com/'+known);
 assert.equal(body.profiles[0].profile_revision,'pr235-fixture');
 assert.deepEqual(body.profiles[1],{
  channel_id:unknown,channel_name:null,display_name:null,avatar_url:null,group:null,
  member_accent:null,member_accent_dual:null,support_mode:'neutral',
  support_color_source:null,profile_revision:null,updated_at:null
 });
 assert.equal(DB.writes,0);
});

test('mounting the profile route preserves catalog collab and all PTT reads',async()=>{
 const DB=compositionDb();
 const catalog=await host.fetch(request('/v1/catalog/today?day=2026-11-03'),{DB});
 assert.equal(catalog.status,200);
 assert.equal((await catalog.json()).schema_version,'public-consumer-v1');

 const collab=await host.fetch(request('/v1/collab/live'),{DB});
 assert.equal(collab.status,200);
 const collabBody=await collab.json();
 assert.equal(collabBody.schema_version,'public-experience-v1');
 assert.equal(collabBody.kind,'collab');

 for(const route of [
  '/v1/ptt/recent?limit=10',
  '/v1/ptt/today?day=2026-11-03',
  '/v1/ptt/history?day=2026-11-03'
 ]){
  const response=await host.fetch(request(route),{DB});
  assert.equal(response.status,200,route);
  assert.equal((await response.json()).schema_version,'public-consumer-v1');
 }
 assert.equal(DB.writes,0);
});

test('private PTT publish and reconcile mounts remain present and fail closed',async()=>{
 const DB=compositionDb();
 for(const route of [
  '/private/ptt/publish',
  '/private/ptt/reconcile',
  '/private/ptt/canonical-remap'
 ]){
  const response=await host.fetch(new Request('https://public-api.example'+route,{
   method:'POST',body:'{}'
  }),{DB});
  assert.notEqual(response.status,404,route);
  assert.ok(response.status>=400,route);
 }
 assert.equal(DB.writes,0);
});
