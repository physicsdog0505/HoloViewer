const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;

function iso(value){
 if(!value)return null;
 const d=new Date(value);
 if(Number.isNaN(d.getTime()))return null;
 return d.toISOString().replace(/\.\d{3}Z$/,'Z');
}
function positiveInt(value){
 if(value==null||value==='')return null;
 const n=Number(value);
 return Number.isSafeInteger(n)&&n>0?n:null;
}
export function normalizeYoutubeVideoItem(item,{now=new Date()}={}){
 if(!item||!VIDEO.test(item.id??'')||!item.snippet||!CHANNEL.test(item.snippet.channelId??''))return null;
 const s=item.snippet,d=item.liveStreamingDetails??{};
 const has_live_streaming_details=item.liveStreamingDetails!=null&&typeof item.liveStreamingDetails==='object';
 const actual_start=iso(d.actualStartTime);
 const actual_end=iso(d.actualEndTime);
 const scheduled_start=iso(d.scheduledStartTime);
 let lifecycle_state='unknown';
 if(actual_end)lifecycle_state='ended';
 else if(s.liveBroadcastContent==='live')lifecycle_state='live';
 else if(s.liveBroadcastContent==='upcoming'){
   lifecycle_state=scheduled_start&&Date.parse(scheduled_start)<=now.getTime()?'waiting':'upcoming';
 } else if(actual_start)lifecycle_state='live';
 const concurrent_viewers=(lifecycle_state==='live'&&actual_end==null)
   ? positiveInt(d.concurrentViewers)
   : null;
 return {
   video_id:item.id,
   channel_id:s.channelId,
   title:String(s.title??''),
   channel_name:String(s.channelTitle??''),
   lifecycle_state,
   scheduled_start,
   actual_start,
   actual_end,
   concurrent_viewers,
   is_livestream:Boolean(has_live_streaming_details||actual_start||actual_end||scheduled_start||s.liveBroadcastContent==='live'||s.liveBroadcastContent==='upcoming')
 };
}
export async function fetchYoutubeVideoItems(env,ids,{fetchImpl=fetch,now=new Date()}={}){
 if(!env?.YOUTUBE_API_KEY)throw Error('youtube_metadata_unavailable');
 if(!Array.isArray(ids)||!ids.length||ids.length>50||ids.some(id=>!VIDEO.test(id)))throw Error('invalid_video_id_batch');
 const url=new URL('https://www.googleapis.com/youtube/v3/videos');
 url.searchParams.set('part','snippet,liveStreamingDetails');
 url.searchParams.set('id',ids.join(','));
 url.searchParams.set('key',String(env.YOUTUBE_API_KEY));
 let response;
 try{
  response=await fetchImpl(url.toString(),{headers:{accept:'application/json'},signal:AbortSignal.timeout(12000)});
 }catch{throw Error('youtube_metadata_unavailable');}
 if(!response.ok)throw Error('youtube_metadata_unavailable');
 let body;
 try{body=await response.json();}catch{throw Error('youtube_metadata_unavailable');}
 if(!Array.isArray(body.items))throw Error('youtube_metadata_unavailable');
 return body.items.map(item=>normalizeYoutubeVideoItem(item,{now})).filter(Boolean);
}
export async function fetchYoutubeVideoMetadata(env,videoId,options={}){
 if(!VIDEO.test(videoId??''))throw Error('invalid_video_id');
 const rows=await fetchYoutubeVideoItems(env,[videoId],options);
 return rows.find(row=>row.video_id===videoId)??null;
}
