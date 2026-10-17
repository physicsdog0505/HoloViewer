/** Minimal D1 subscription ledger used by the existing Today Worker. */
import {topicForChannel} from './websub-receiver.mjs';
const CID=/^UC[A-Za-z0-9_-]{22}$/;
const stamp=x=>{
 if(!(x instanceof Date)||!Number.isFinite(x.valueOf()))throw Error('invalid time');
 return x.toISOString().replace(/\\.\\d{3}Z$/,'Z');
};
export async function recordSubscriptionRequest(db,{channelId,rosterVersion,mode='subscribe',now=new Date()}={}){
 if(!CID.test(channelId??'')||typeof rosterVersion!=='string'||!rosterVersion||
   !['subscribe','unsubscribe'].includes(mode)||!db?.prepare)throw Error('invalid subscription request');
 await db.prepare(`INSERT INTO public_today_websub_leases
 (channel_id,roster_version,topic,requested_mode,state,requested_at,verified_at,expires_at,lease_seconds,last_error)
 VALUES (?,?,?,?, 'pending', ?,NULL,NULL,NULL,NULL)
 ON CONFLICT(channel_id) DO UPDATE SET roster_version=excluded.roster_version,
 topic=excluded.topic,requested_mode=excluded.requested_mode,state='pending',
 requested_at=excluded.requested_at,verified_at=NULL,expires_at=NULL,lease_seconds=NULL,last_error=NULL`)
 .bind(channelId,rosterVersion,topicForChannel(channelId),mode,stamp(now)).run();
 return {channel_id:channelId,state:'pending',mode};
}
export async function confirmSubscriptionChallenge(db,{channelId,rosterVersion,mode,leaseSeconds,now=new Date()}={}){
 if(!CID.test(channelId??'')||!['subscribe','unsubscribe'].includes(mode)||
   !Number.isInteger(leaseSeconds)||leaseSeconds<60||leaseSeconds>2592000)throw Error('invalid challenge');
 const old=await db.prepare('SELECT roster_version,state,requested_mode,requested_at FROM public_today_websub_leases WHERE channel_id=?')
  .bind(channelId).first();
 const requested=Date.parse(old?.requested_at??'');
 if(!old||old.roster_version!==rosterVersion||old.state!=='pending'||old.requested_mode!==mode||
   !Number.isFinite(requested)||requested>now.getTime()||now.getTime()-requested>86400000)
  throw Error('no matching pending subscription');
 const active=mode==='subscribe',expiry=active?stamp(new Date(now.getTime()+leaseSeconds*1000)):null;
 const r=await db.prepare(`UPDATE public_today_websub_leases SET state=?,verified_at=?,expires_at=?,lease_seconds=?,last_error=NULL
 WHERE channel_id=? AND roster_version=? AND requested_mode=? AND state='pending' AND requested_at=?`)
 .bind(active?'active':'expired',stamp(now),expiry,active?leaseSeconds:null,channelId,rosterVersion,mode,old.requested_at).run();
 if(Number(r?.meta?.changes??r?.changes??0)!==1)throw Error('challenge race lost');
 return {state:active?'active':'expired',channel_id:channelId,expires_at:expiry};
}
export async function readSubscriptionLeases(db){
 const r=await db.prepare('SELECT channel_id,roster_version,requested_mode,state,expires_at,requested_at FROM public_today_websub_leases ORDER BY channel_id LIMIT 500').all();
 return r.results??[];
}
