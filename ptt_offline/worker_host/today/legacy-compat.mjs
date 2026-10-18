/** Exact production legacy read compatibility; canonical Today remains separate. */
const videoId=/^[A-Za-z0-9_-]{11}$/;
const HISTORY_FIELDS='video_id,title,channel_id,channel_name,avatar_url,actual_start,actual_end,scheduled_start';
const VIDEO_FIELDS='video_id,title,channel_id,channel_name,avatar_url,lifecycle_state,actual_start,actual_end,scheduled_start';
function response(data,status=200,age=30){return new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'public, max-age='+age}});}
function validDay(day){if(!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;const d=new Date(day+'T00:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===day;}
function decimal(raw,min,max){return /^\d+$/.test(raw)&&Number.isSafeInteger(Number(raw))&&Number(raw)>=min&&Number(raw)<=max;}
export async function legacyHistory(request,env){
 const p=new URL(request.url).searchParams,day=p.get('day')??'';
 const rawLimit=p.get('limit')??'50',rawOffset=p.get('offset')??'0';
 if(!validDay(day)||!decimal(rawLimit,1,50)||!decimal(rawOffset,0,1000000))return response({error:'invalid_history_query'},400,0);
 const limit=Number(rawLimit),offset=Number(rawOffset);
 const count=await env.DB.prepare('SELECT COUNT(*) AS total FROM public_history WHERE taipei_day=?').bind(day).first();
 const rows=await env.DB.prepare('SELECT '+HISTORY_FIELDS+' FROM public_history WHERE taipei_day=? ORDER BY COALESCE(actual_start,scheduled_start) DESC,video_id DESC LIMIT ? OFFSET ?').bind(day,limit,offset).all();
 return response({day,total:count?.total??0,limit,offset,items:rows.results??[]});
}
export async function legacyVideo(request,env){
 const id=new URL(request.url).pathname.split('/').at(-1)??'';
 if(!videoId.test(id))return response({error:'invalid_video_id'},400,0);
 let video=await env.DB.prepare('SELECT '+VIDEO_FIELDS+' FROM public_catalog WHERE video_id=?').bind(id).first();
 if(!video){
  const row=await env.DB.prepare(`SELECT video_id,title,publisher_channel_id AS channel_id,channel_name,
    lifecycle_state,actual_start,actual_end,scheduled_start,source_label
    FROM public_today_canonical WHERE video_id=? LIMIT 1`).bind(id).first();
  if(row){
   const trusted=row.source_label==='YouTube';
   video={
    video_id:row.video_id,
    title:row.title??'',
    channel_id:row.channel_id??'',
    channel_name:row.channel_name??'',
    avatar_url:'',
    lifecycle_state:row.lifecycle_state??'unknown',
    actual_start:trusted?row.actual_start??null:null,
    actual_end:trusted?row.actual_end??null:null,
    scheduled_start:row.scheduled_start??null,
    anchor_source:trusted&&row.actual_start?'youtube-liveStreamingDetails-actualStartTime':null
   };
  }
 }
 if(!video)return response({error:'not_found'},404,0);
 return response(video,200,15);
}
