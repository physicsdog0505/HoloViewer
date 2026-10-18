import {verifiedChannelAvatar} from './store.mjs';
import {validateSupportColorExport,supportColorFor} from './support-colors.mjs';
/** Production legacy read compatibility plus verified Today/recent-history bridge. */
const videoId=/^[A-Za-z0-9_-]{11}$/;
const HISTORY_FIELDS='video_id,title,channel_id,channel_name,avatar_url,actual_start,actual_end,scheduled_start,source_revision';
const VIDEO_FIELDS='video_id,title,channel_id,channel_name,avatar_url,lifecycle_state,actual_start,actual_end,scheduled_start';
const TRUSTED_TODAY_SOURCE='YouTube liveStreamingDetails';
const TRUSTED_HISTORY_SOURCES=new Set(['stream-catalog-v1:youtube-liveStreamingDetails','youtube-videos-list:liveStreamingDetails']);
const ANCHOR_SOURCE='youtube-liveStreamingDetails-actualStartTime';
function response(data,status=200,age=30){return new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'public, max-age='+age}});}
function validDay(day){if(!/^\d{4}-\d{2}-\d{2}$/.test(day))return false;const d=new Date(day+'T00:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===day;}
function decimal(raw,min,max){return /^\d+$/.test(raw)&&Number.isSafeInteger(Number(raw))&&Number(raw)>=min&&Number(raw)<=max;}
function trustedBounds(row,trusted){
 const start=trusted&&typeof row?.actual_start==='string'&&Number.isFinite(Date.parse(row.actual_start))?row.actual_start:null;
 const end=trusted&&typeof row?.actual_end==='string'&&Number.isFinite(Date.parse(row.actual_end))?row.actual_end:null;
 const valid=start&&end&&Date.parse(end)>Date.parse(start);
 return {actual_start:valid?start:null,actual_end:valid?end:null,anchor_source:valid?ANCHOR_SOURCE:null};
}
function supportColorJson(env){
 if(env?.TODAY_SUPPORT_COLORS_JSON)return String(env.TODAY_SUPPORT_COLORS_JSON);
 const parts=[];
 for(let i=0;i<16;i++){const v=env?.['TODAY_SUPPORT_COLORS_JSON_'+i];if(v==null){if(i===0)return null;break;}parts.push(String(v));}
 return parts.length?parts.join(''):null;
}
function normalizeHistory(row,colors){
 const bounds=trustedBounds(row,TRUSTED_HISTORY_SOURCES.has(row?.source_revision));
 const color=supportColorFor(row?.channel_id,colors);
 return {...row,...bounds,
  avatar_url:verifiedChannelAvatar(row?.trusted_channel_avatar)??verifiedChannelAvatar(row?.avatar_url),
  group:['hololive','holostars','mekpark','other'].includes(row?.channel_group)?row.channel_group:'other',
  ...color};
}
export async function legacyHistory(request,env){
 const p=new URL(request.url).searchParams,day=p.get('day')??'';
 const rawLimit=p.get('limit')??'50',rawOffset=p.get('offset')??'0';
 if(!validDay(day)||!decimal(rawLimit,1,50)||!decimal(rawOffset,0,1000000))return response({error:'invalid_history_query'},400,0);
 const limit=Number(rawLimit),offset=Number(rawOffset);
 const count=await env.DB.prepare('SELECT COUNT(*) AS total FROM public_history WHERE taipei_day=?').bind(day).first();
 const profileExpr=env?.TODAY_PROFILES_ENABLED==='true'
  ? '(SELECT p.avatar_url FROM public_today_channel_profiles p WHERE p.channel_id=h.channel_id ORDER BY p.fetched_at DESC LIMIT 1)'
  : 'NULL';
 const rows=await env.DB.prepare(`SELECT h.*,
   COALESCE(${profileExpr},(SELECT c.avatar_url FROM public_catalog c WHERE c.channel_id=h.channel_id AND c.avatar_url IS NOT NULL ORDER BY COALESCE(c.actual_start,c.scheduled_start) DESC,c.video_id DESC LIMIT 1)) AS trusted_channel_avatar,
   COALESCE((SELECT ac.channel_group FROM public_today_approved_channels ac WHERE ac.channel_id=h.channel_id LIMIT 1),
     (SELECT t.channel_group FROM public_today_canonical t WHERE t.publisher_channel_id=h.channel_id ORDER BY t.lifecycle_observed_at DESC LIMIT 1),'other') AS channel_group
   FROM public_history h WHERE h.taipei_day=? ORDER BY COALESCE(h.actual_start,h.scheduled_start) DESC,h.video_id DESC LIMIT ? OFFSET ?`)
  .bind(day,limit,offset).all();
 let colors=null;
 try{const raw=supportColorJson(env);colors=raw?validateSupportColorExport(JSON.parse(raw)):null;}catch{colors=null;}
 return response({day,total:count?.total??0,limit,offset,items:(rows.results??[]).map(row=>normalizeHistory(row,colors))});
}
export async function legacyVideo(request,env){
 const id=new URL(request.url).pathname.split('/').at(-1)??'';
 if(!videoId.test(id))return response({error:'invalid_video_id'},400,0);

 const today=await env.DB.prepare(`SELECT video_id,title,publisher_channel_id AS channel_id,channel_name,
   lifecycle_state,actual_start,actual_end,scheduled_start,source_label
   FROM public_today_canonical WHERE video_id=? LIMIT 1`).bind(id).first();
 if(today){
   const bounds=trustedBounds(today,today.source_label===TRUSTED_TODAY_SOURCE);
   return response({
    video_id:today.video_id,title:today.title??'',channel_id:today.channel_id??'',channel_name:today.channel_name??'',
    avatar_url:'',lifecycle_state:today.lifecycle_state??'unknown',scheduled_start:today.scheduled_start??null,...bounds
   },200,15);
 }

 const history=await env.DB.prepare(`SELECT video_id,title,channel_id,channel_name,avatar_url,
   actual_start,actual_end,scheduled_start,source_revision
   FROM public_history WHERE video_id=? LIMIT 1`).bind(id).first();
 if(history){
   const bounds=trustedBounds(history,TRUSTED_HISTORY_SOURCES.has(history.source_revision));
   return response({...history,lifecycle_state:'ended',...bounds},200,30);
 }

 const legacy=await env.DB.prepare('SELECT '+VIDEO_FIELDS+' FROM public_catalog WHERE video_id=?').bind(id).first();
 if(!legacy)return response({error:'not_found'},404,0);
 return response({...legacy,actual_start:null,actual_end:null,anchor_source:null},200,15);
}
