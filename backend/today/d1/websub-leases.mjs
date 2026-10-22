/** D1 subscription ledger. Caller MUST authenticate owner request to hub separately.
 * No implicit migration, network calls, or deployment.
 */
import {topicForChannel} from './websub-receiver.mjs';
const CID=/^UC[A-Za-z0-9_-]{22}$/;
function ts(x){if(!(x instanceof Date)||!Number.isFinite(x.valueOf()))throw Error('invalid time');return x.toISOString().replace(/\.\d{3}Z$/,'Z')}
export async function recordSubscriptionRequest(db,{channelId,rosterVersion,now=new Date()}){
 if(!CID.test(channelId??'')||typeof rosterVersion!=='string'||!rosterVersion||!db?.prepare)throw Error('invalid subscription request');
 await db.prepare(`INSERT INTO public_today_websub_leases(channel_id,roster_version,topic,state,requested_at,verified_at,expires_at,lease_seconds,last_error)
 VALUES (?,?,?,'pending',?,NULL,NULL,NULL,NULL)
 ON CONFLICT(channel_id) DO UPDATE SET roster_version=excluded.roster_version,
 topic=excluded.topic,state='pending',requested_at=excluded.requested_at,last_error=NULL`)
 .bind(channelId,rosterVersion,topicForChannel(channelId),ts(now)).run();
 return {channel_id:channelId,state:'pending'};
}
export async function confirmSubscriptionChallenge(db,{channelId,rosterVersion,mode,leaseSeconds,now=new Date()}){
 if(!CID.test(channelId??'')||!['subscribe','unsubscribe'].includes(mode)
   ||!Number.isInteger(leaseSeconds)||leaseSeconds<60||leaseSeconds>2592000)throw Error('invalid challenge');
 const old=await db.prepare('SELECT roster_version,state,requested_at FROM public_today_websub_leases WHERE channel_id=?').bind(channelId).first();
 if(!old||old.roster_version!==rosterVersion||old.state!=='pending'||!old.requested_at
   ||Math.abs(now.getTime()-Date.parse(old.requested_at))>86400000)throw Error('no matching pending subscription');
 const active=mode==='subscribe',expiry=active?ts(new Date(now.getTime()+leaseSeconds*1000)):null;
 await db.prepare(`UPDATE public_today_websub_leases SET state=?,verified_at=?,expires_at=?,lease_seconds=?,last_error=NULL
 WHERE channel_id=? AND roster_version=? AND state='pending'`)
 .bind(active?'active':'expired',ts(now),expiry,active?leaseSeconds:null,channelId,rosterVersion).run();
 return {state:active?'active':'expired',channel_id:channelId,expires_at:expiry};
}
export async function readSubscriptionLeases(db){
 const r=await db.prepare('SELECT channel_id,roster_version,state,expires_at,requested_at FROM public_today_websub_leases ORDER BY channel_id LIMIT 500').all();
 return r.results??[];
}
