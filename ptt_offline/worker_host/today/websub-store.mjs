/** Proposal-only durable Cloudflare D1 WebSub event store. Never implicit migration. */
const C=/^UC[A-Za-z0-9_-]{22}$/;
const V=/^[A-Za-z0-9_-]{11}$/;
const H=/^[0-9a-f]{64}$/;
const TIME=/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;
export async function persistEvent(db,event,{now=new Date()}={}){
 if(!db?.prepare||!H.test(event?.raw_sha256??'')||!C.test(event.channel_id??'')||
  (event.video_id!==null&&!V.test(event.video_id??''))||
  typeof event.roster_version!=='string'||!event.roster_version)throw Error('invalid durable event');
 const received=now.toISOString().replace(/\.\d{3}Z$/,'Z');
 await db.prepare(`INSERT INTO public_today_websub_events
 (event_hash,channel_id,video_id,roster_version,received_at,status,attempts)
 VALUES (?,?,?,?,?,'pending',0) ON CONFLICT(event_hash) DO NOTHING`)
 .bind(event.raw_sha256,event.channel_id,event.video_id,event.roster_version,received).run();
 return {persisted:true,event_hash:event.raw_sha256};
}
export async function getPendingEvents(db,{limit=50}={}){
 if(!Number.isInteger(limit)||limit<1||limit>50)throw Error('unbounded pending batch');
 const rows=await db.prepare(`SELECT event_hash,channel_id,video_id,roster_version,attempts
 FROM public_today_websub_events WHERE status='pending' AND attempts<5
 ORDER BY received_at,event_hash LIMIT ?`).bind(limit).all();
 return rows.results??[];
}
export async function markEventProcessed(db,eventHash,{time=new Date()}={}){
 if(!H.test(eventHash))throw Error('bad event hash');
 const stamp=time.toISOString().replace(/\.\d{3}Z$/,'Z');
 return db.prepare(`UPDATE public_today_websub_events SET status='processed',
 processed_at=?,last_error=NULL WHERE event_hash=? AND status IN ('pending','processing')`)
 .bind(stamp,eventHash).run();
}
export async function markEventFailed(db,eventHash,error){
 if(!H.test(eventHash))throw Error('bad event hash');
 return db.prepare(`UPDATE public_today_websub_events SET attempts=attempts+1,
 status=CASE WHEN attempts+1>=5 THEN 'failed' ELSE 'pending' END,
 last_error=? WHERE event_hash=? AND status IN ('pending','processing')`)
 .bind(String(error).slice(0,200),eventHash).run();
}
