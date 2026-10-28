import test from 'node:test';
import assert from 'node:assert/strict';
import {fetchYoutubeVideoItems,normalizeYoutubeVideoItem} from './youtube-metadata-provider.mjs';

const C='UC'+'A'.repeat(22);

function item(id,{state='live',count='12345',start='2026-10-28T12:00:00Z',end=null}={}){
  return {
    id,
    snippet:{channelId:C,title:id,channelTitle:'Channel',liveBroadcastContent:state},
    liveStreamingDetails:{
      scheduledStartTime:'2026-10-28T12:00:00Z',
      ...(start?{actualStartTime:start}:{}),
      ...(end?{actualEndTime:end}:{}),
      ...(count!==undefined?{concurrentViewers:count}:{})
    }
  };
}

test('normalizes positive live concurrentViewers and nulls invalid/non-live values',()=>{
  const now=new Date('2026-10-28T12:10:00Z');
  assert.equal(normalizeYoutubeVideoItem(item('abcdefghijk'),{now}).concurrent_viewers,12345);
  for(const value of ['0','-1','bad','',null,undefined]){
    assert.equal(normalizeYoutubeVideoItem(item('abcdefghijk',{count:value}),{now}).concurrent_viewers,null);
  }
  assert.equal(normalizeYoutubeVideoItem(item('abcdefghijk',{state:'upcoming',start:null,count:'77'}),{now}).concurrent_viewers,null);
  assert.equal(normalizeYoutubeVideoItem(item('abcdefghijk',{state:'none',count:'88',end:'2026-10-28T12:09:00Z'}),{now}).concurrent_viewers,null);
});

test('reuses one existing videos.list request for a multi-id batch',async()=>{
  const seen=[];
  const fetchImpl=async url=>{
    seen.push(url);
    const parsed=new URL(url);
    const ids=parsed.searchParams.get('id').split(',');
    return {
      ok:true,
      async json(){return {items:ids.map(id=>item(id,{count:'7'}))};}
    };
  };
  const ids=['abcdefghijk','lmnopqrstuv'];
  const rows=await fetchYoutubeVideoItems({YOUTUBE_API_KEY:'fixture'},ids,{fetchImpl,now:new Date('2026-10-28T12:10:00Z')});
  assert.equal(seen.length,1);
  const url=new URL(seen[0]);
  assert.equal(url.pathname,'/youtube/v3/videos');
  assert.equal(url.searchParams.get('part'),'snippet,liveStreamingDetails');
  assert.equal(url.searchParams.get('id'),ids.join(','));
  assert.deepEqual(rows.map(x=>x.concurrent_viewers),[7,7]);
});
