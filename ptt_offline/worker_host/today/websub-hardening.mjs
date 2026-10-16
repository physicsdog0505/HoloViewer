import {verifiedChannelAvatar} from './store.mjs';
const CID=/^UC[A-Za-z0-9_-]{22}$/;
const VID=/^[0-9a-f]{64}$/;
const TS=/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;
const stamp=d=>d.toISOString().replace(/\.\d{3}Z$/,'Z');
// Caller supplies cryptographically random token; avoid using a shared process clock as identity.
export async function claimEvent(db,hash,token,{now=new Date(),leaseSeconds=90}={}){
 if(!VID.test(hash)||!VID.test(token)||leaseSeconds<15||leaseSeconds>300)throw Error('invalid claim');
 const until=stamp(new Date(now.getTime()+leaseSeconds*1000));
 const r=await db.prepare(`UPDATE public_today_websub_events SET status='processing',claim_token=?,claim_until=?
 WHERE event_hash=? AND attempts<5 AND
 (status='pending' OR (status='processing' AND claim_until<?))`)
  .bind(token,until,hash,stamp(now)).run();
 return r.meta?.changes===1||r.changes===1;
}
export async function finishClaim(db,hash,token,{now=new Date()}={}){
 if(!VID.test(hash)||!VID.test(token))throw Error('invalid claim identity');
 const r=await db.prepare(`UPDATE public_today_websub_events SET status='processed',processed_at=?,
 claim_until=NULL,claim_token=NULL,last_error=NULL
 WHERE event_hash=? AND claim_token=? AND status='processing' AND claim_until>=?`)
 .bind(stamp(now),hash,token,stamp(now)).run();
 if((r.meta?.changes??r.changes)!==1)throw Error('claim lost; cannot ACK');
}
export async function failClaim(db,hash,token,error){
 if(!VID.test(hash)||!VID.test(token))throw Error('invalid claim identity');
 const r=await db.prepare(`UPDATE public_today_websub_events SET attempts=attempts+1,
 status=CASE WHEN attempts+1>=5 THEN 'failed' ELSE 'pending' END,
 claim_token=NULL,claim_until=NULL,last_error=?
 WHERE event_hash=? AND claim_token=? AND status='processing'`)
 .bind(String(error).slice(0,200),hash,token).run();
 if((r.meta?.changes??r.changes)!==1)throw Error('claim lost; cannot mark failure');
}
export async function nextReconcileWindow(db,roster,{now=new Date(),limit=3,startIndex=null}={}){
 if(!roster?.version||!Array.isArray(roster.channels)||!roster.channels.length||limit<1||limit>10)throw Error('invalid roster window');
 let start;
 if(startIndex!==null){
  if(!Number.isSafeInteger(startIndex)||startIndex<0)throw Error('invalid explicit roster cursor');
  start=startIndex%roster.channels.length;
 }else{
  const old=await db.prepare('SELECT roster_version,next_index FROM public_today_reconcile_cursor WHERE singleton=1').first();
  start=old?.roster_version===roster.version?old.next_index%roster.channels.length:0;
 }
 const selected=Array.from({length:Math.min(limit,roster.channels.length)},(_,i)=>roster.channels[(start+i)%roster.channels.length]);
 return {start,selected,next:(start+selected.length)%roster.channels.length,rosterVersion:roster.version,updatedAt:stamp(now)};
}
export async function commitReconcileWindow(db,window){
 await db.prepare(`INSERT INTO public_today_reconcile_cursor(singleton,roster_version,next_index,updated_at)
 VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
 roster_version=excluded.roster_version,next_index=excluded.next_index,updated_at=excluded.updated_at
 WHERE public_today_reconcile_cursor.roster_version!=excluded.roster_version
    OR public_today_reconcile_cursor.next_index!=excluded.next_index`)
 .bind(window.rosterVersion,window.next,window.updatedAt).run();
}
export async function readLifecycleCursor(db,rosterVersion){
 const row=await db.prepare('SELECT roster_version,last_video_id,checked_at_json FROM public_today_lifecycle_cursor WHERE singleton=1').first();
 if(row?.roster_version!==rosterVersion)return {lastVideoId:'',checkedAtByVideo:{}};
 let checkedAtByVideo={};
 try{
  const parsed=JSON.parse(String(row.checked_at_json??'{}'));
  if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed))checkedAtByVideo=parsed;
 }catch{}
 return {lastVideoId:String(row.last_video_id??''),checkedAtByVideo};
}
export async function commitLifecycleCursor(db,{rosterVersion,lastVideoId,checkedAtByVideo={},now=new Date()}){
 if(typeof rosterVersion!=='string'||!rosterVersion||typeof lastVideoId!=='string'||
   !checkedAtByVideo||typeof checkedAtByVideo!=='object'||Array.isArray(checkedAtByVideo))throw Error('invalid lifecycle cursor');
 const checkedJson=JSON.stringify(checkedAtByVideo);
 if(checkedJson.length>131072)throw Error('lifecycle freshness watermark too large');
 await db.prepare(`INSERT INTO public_today_lifecycle_cursor(singleton,roster_version,last_video_id,checked_at_json,updated_at)
 VALUES(1,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
 roster_version=excluded.roster_version,last_video_id=excluded.last_video_id,
 checked_at_json=excluded.checked_at_json,updated_at=excluded.updated_at
 WHERE public_today_lifecycle_cursor.roster_version!=excluded.roster_version
    OR public_today_lifecycle_cursor.last_video_id!=excluded.last_video_id
    OR public_today_lifecycle_cursor.checked_at_json!=excluded.checked_at_json`)
 .bind(rosterVersion,lastVideoId,checkedJson,stamp(now)).run();
}
export async function saveChannelProfiles(db,roster,items,{now=new Date()}={}){
 if(!Array.isArray(items)||items.length>50||!roster?.version||!Array.isArray(roster.channels))throw Error('profile batch invalid');
 const allowed=new Set(roster.channels.map(x=>x.id));
 let count=0;
 for(const item of items){
  const id=item?.id,title=item?.snippet?.title,url=item?.snippet?.thumbnails?.default?.url??null;
  if(!CID.test(id??'')||!allowed.has(id)||typeof title!=='string'||!title.trim())throw Error('unapproved profile');
  const avatar=verifiedChannelAvatar(url);
  if(url&&!avatar)throw Error('unverified channel avatar');
  await db.prepare(`INSERT INTO public_today_channel_profiles(channel_id,roster_version,channel_title,avatar_url,fetched_at,source)
 VALUES(?,?,?,?,?,'youtube_channels_list') ON CONFLICT(channel_id) DO UPDATE SET
 roster_version=excluded.roster_version,channel_title=excluded.channel_title,
 avatar_url=excluded.avatar_url,fetched_at=excluded.fetched_at`)
 .bind(id,roster.version,title,avatar,stamp(now)).run();count++;
 }
 return {stored:count};
}
