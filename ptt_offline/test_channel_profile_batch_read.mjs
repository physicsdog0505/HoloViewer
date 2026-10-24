import test from 'node:test';
import assert from 'node:assert/strict';

import {handleChannelProfilesBatchRead} from './worker_host/today/channel-profile-read.mjs';

function channel(index){
 const suffix=index.toString(36).toUpperCase().padStart(22,'A').slice(-22);
 return 'UC'+suffix;
}

function countedDb(){
 let prepares=0;
 const db={
  get prepares(){return prepares;},
  reset(){prepares=0;},
  prepare(sql){
   prepares+=1;
   return {
    bind(...ids){
     return {
      async all(){
       if(sql.includes('FROM public_channel_profiles')){
        return {results:ids.map((id,i)=>({
         channel_id:id,
         channel_name:'Channel '+i,
         display_name:'Display '+i,
         avatar_url:'https://yt3.ggpht.com/'+id,
         channel_group:'hololive',
         member_accent:'#112233',
         member_accent_dual:null,
         support_mode:'solid',
         support_color_source:'canonical',
         profile_revision:'test-'+i,
         updated_at:'2026-10-25T00:00:00Z'
        }))};
       }
       return {results:[]};
      }
     };
    }
   };
  }
 };
 return db;
}

async function runBatch(count){
 const ids=Array.from({length:count},(_,i)=>channel(i+1));
 const db=countedDb();
 const query=ids.map(id=>'id='+encodeURIComponent(id)).join('&');
 const response=await handleChannelProfilesBatchRead(
  new Request('https://api.example/v1/channels/profiles?'+query),
  {DB:db}
 );
 const body=await response.json();
 return {ids,db,response,body};
}

for(const count of [1,20,80]){
 test('batch profile read uses one fixed resolver pass for '+count+' ids',async()=>{
  const {ids,db,response,body}=await runBatch(count);
  assert.equal(response.status,200);
  assert.equal(body.schema_version,'holoviewer-channel-profiles-v1');
  assert.deepEqual(body.profiles.map(row=>row.channel_id),ids);
  assert.equal(db.prepares,7,'resolver prepare count must stay fixed across batch size');
 });
}

test('batch profile read accepts repeated and comma-separated ids with stable dedupe order',async()=>{
 const a=channel(1),b=channel(2),c=channel(3);
 const db=countedDb();
 const response=await handleChannelProfilesBatchRead(
  new Request('https://api.example/v1/channels/profiles?id='+a+'&id='+b+','+c+'&id='+a),
  {DB:db}
 );
 const body=await response.json();
 assert.equal(response.status,200);
 assert.deepEqual(body.profiles.map(row=>row.channel_id),[a,b,c]);
 assert.equal(db.prepares,7);
});

test('batch profile read rejects empty invalid and over-100 requests before DB access',async()=>{
 const db=countedDb();

 let response=await handleChannelProfilesBatchRead(
  new Request('https://api.example/v1/channels/profiles'),
  {DB:db}
 );
 assert.equal(response.status,400);
 assert.equal((await response.json()).error,'channel_ids_required');
 assert.equal(db.prepares,0);

 response=await handleChannelProfilesBatchRead(
  new Request('https://api.example/v1/channels/profiles?id=not-a-channel'),
  {DB:db}
 );
 assert.equal(response.status,400);
 assert.equal((await response.json()).error,'invalid_channel_id');
 assert.equal(db.prepares,0);

 const ids=Array.from({length:101},(_,i)=>channel(i+1));
 response=await handleChannelProfilesBatchRead(
  new Request('https://api.example/v1/channels/profiles?'+ids.map(id=>'id='+id).join('&')),
  {DB:db}
 );
 assert.equal(response.status,400);
 assert.equal((await response.json()).error,'too_many_channel_ids');
 assert.equal(db.prepares,0);
});
