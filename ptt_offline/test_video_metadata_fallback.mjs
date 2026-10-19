import test from 'node:test';
import assert from 'node:assert/strict';
import {handleVideoMetadataRead} from './worker_host/today/video-metadata-read.mjs';

const MANAGED='UC'+'A'.repeat(22);
const EXTERNAL='UC'+'Z'.repeat(22);
const VID='abcdefghijk';

function request(id=VID){return new Request('https://api.example/v1/videos/'+id+'/metadata');}
function dbFixture({today=null,history=null,legacy=null,managed=false}={}){
 let writes=0,reads=0;
 return {
  get writes(){return writes}, get reads(){return reads},
  prepare(sql){
   if(/\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER)\b/i.test(sql))writes++;
   return {bind(){return {
    async first(){
     reads++;
     if(sql.includes('FROM public_today_canonical'))return today;
     if(sql.includes('FROM public_history'))return history;
     if(sql.includes('FROM public_catalog'))return legacy;
     if(sql.includes('FROM public_today_approved_channels'))return managed?{ok:1}:null;
     throw Error('unexpected SQL: '+sql);
    },
    async run(){writes++;throw Error('write forbidden')}
   }}};
  },
  async batch(){writes++;throw Error('write forbidden')}
 };
}
function youtubeItem({channelId=MANAGED,actualStart='2026-10-18T15:00:06Z',actualEnd='2026-10-18T16:04:31Z',scheduled='2026-10-18T15:00:00Z',live='none'}={}){
 return {
  id:VID,
  snippet:{channelId,title:'Fallback video',channelTitle:'Channel',liveBroadcastContent:live},
  liveStreamingDetails:{
   ...(scheduled?{scheduledStartTime:scheduled}:{}),
   ...(actualStart?{actualStartTime:actualStart}:{}),
   ...(actualEnd?{actualEndTime:actualEnd}:{})
  }
 };
}
function fetchBody(items,status=200){
 return async()=>new Response(JSON.stringify({items}),{status,headers:{'content-type':'application/json'}});
}

test('A catalog hit returns source=catalog and never calls YouTube fallback',async()=>{
 const db=dbFixture({managed:true,today:{
  video_id:VID,title:'Catalog video',channel_id:MANAGED,channel_name:'Managed',
  lifecycle_state:'ended',scheduled_start:'2026-10-18T15:00:00Z',
  actual_start:'2026-10-18T15:00:06Z',actual_end:'2026-10-18T16:04:31Z',
  source_label:'YouTube liveStreamingDetails'
 }});
 let fetches=0;
 const res=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:async()=>{fetches++;throw Error('must not fetch')}
 });
 assert.equal(res.status,200);
 const body=await res.json();
 assert.equal(body.source,'catalog');
 assert.equal(body.managed_channel,true);
 assert.equal(body.lifecycle_state,'ended');
 assert.equal(body.actual_start,'2026-10-18T15:00:06Z');
 assert.equal(body.actual_end,'2026-10-18T16:04:31Z');
 assert.equal(fetches,0);
 assert.equal(db.writes,0);
});

test('B missing managed catalog video uses YouTube fallback without DB writes',async()=>{
 const db=dbFixture({managed:true});
 const res=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:fetchBody([youtubeItem()])
 });
 assert.equal(res.status,200);
 const body=await res.json();
 assert.equal(body.source,'youtube-fallback');
 assert.equal(body.managed_channel,true);
 assert.equal(body.channel_id,MANAGED);
 assert.equal(body.lifecycle_state,'ended');
 assert.equal(body.actual_start,'2026-10-18T15:00:06Z');
 assert.equal(body.actual_end,'2026-10-18T16:04:31Z');
 assert.equal(db.writes,0);
});

test('C external YouTube video returns metadata with managed_channel=false and no writes',async()=>{
 const db=dbFixture({managed:false});
 const res=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:fetchBody([youtubeItem({channelId:EXTERNAL})])
 });
 assert.equal(res.status,200);
 const body=await res.json();
 assert.equal(body.source,'youtube-fallback');
 assert.equal(body.managed_channel,false);
 assert.equal(body.channel_id,EXTERNAL);
 assert.equal(body.actual_start,'2026-10-18T15:00:06Z');
 assert.equal(body.actual_end,'2026-10-18T16:04:31Z');
 assert.equal(db.writes,0);
});

test('D unavailable metadata fails closed and does not guess scheduled into actual bounds',async()=>{
 const db=dbFixture({managed:false});
 const missing=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:fetchBody([])
 });
 assert.equal(missing.status,404);
 const m=await missing.json();
 assert.equal(m.error,'youtube_video_not_found');
 assert.equal(m.lifecycle_state,'unknown');

 const onlyScheduled=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  now:new Date('2026-10-18T14:00:00Z'),
  fetchImpl:fetchBody([youtubeItem({channelId:EXTERNAL,actualStart:null,actualEnd:null,scheduled:'2026-10-18T15:00:00Z',live:'upcoming'})])
 });
 assert.equal(onlyScheduled.status,200);
 const s=await onlyScheduled.json();
 assert.equal(s.lifecycle_state,'upcoming');
 assert.equal(s.scheduled_start,'2026-10-18T15:00:00Z');
 assert.equal(s.actual_start,null);
 assert.equal(s.actual_end,null);
 assert.equal(db.writes,0);
});

test('provider/network failure is explicit unknown error with no writes',async()=>{
 const db=dbFixture();
 const res=await handleVideoMetadataRead(request(),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:async()=>{throw Error('network')}
 });
 assert.equal(res.status,503);
 const body=await res.json();
 assert.equal(body.error,'youtube_metadata_unavailable');
 assert.equal(body.lifecycle_state,'unknown');
 assert.equal(db.writes,0);
});

test('invalid video id is rejected before provider access',async()=>{
 const db=dbFixture();
 let fetched=false;
 const res=await handleVideoMetadataRead(request('short'),{DB:db,YOUTUBE_API_KEY:'key'},{
  fetchImpl:async()=>{fetched=true;throw Error('unexpected')}
 });
 assert.equal(res.status,400);
 assert.equal(fetched,false);
 assert.equal(db.writes,0);
});
