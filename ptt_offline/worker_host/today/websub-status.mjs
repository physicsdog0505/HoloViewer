import {getPendingEvents} from './websub-store.mjs';
import {writeEvidence} from './store.mjs';
import {claimEvent,finishClaim,failClaim} from './websub-hardening.mjs';
// Intended for an explicitly configured Cloudflare scheduled handler; no auto activation.
export async function refreshPendingVideos({db,roster,fetchVideos,now=new Date(),limit=25}){
 if(!db?.prepare||typeof fetchVideos!=='function'||!Array.isArray(roster?.channels)||!roster.version||limit<1||limit>50)throw Error('invalid worker configuration');
 const approved=new Map(roster.channels.map(c=>[c.id,c.group]));
 const candidates=await getPendingEvents(db,{limit,now});
 const owned=[];
 for(const event of candidates){
  const rand=crypto.getRandomValues(new Uint8Array(32));
  const token=Array.from(rand,b=>b.toString(16).padStart(2,'0')).join('');
  if(await claimEvent(db,event.event_hash,token,{now}))owned.push({...event,claimToken:token});
 }
 let ignored_stale_roster=0,deleted_notices=0,reconcile_required=false;
 const events=[];
 for(const event of owned){
  if(event.roster_version!==roster.version||!approved.has(event.channel_id)){
   await finishClaim(db,event.event_hash,event.claimToken,{now});
   ignored_stale_roster++;
   continue;
  }
  if(event.video_id===null){
   // YouTube deleted-entry callbacks omit the video ID. ACK the durable notice
   // to prevent poison retries, but surface that a bounded reconciliation is needed.
   await finishClaim(db,event.event_hash,event.claimToken,{now});
   deleted_notices++;
   reconcile_required=true;
   continue;
  }
  if(!/^[A-Za-z0-9_-]{11}$/.test(event.video_id)){
   await failClaim(db,event.event_hash,event.claimToken,'invalid queued video identity');
   continue;
  }
  events.push(event);
 }
 const targets=events;
 const ids=[...new Set(targets.map(e=>e.video_id))];
 let results=[];
 if(ids.length){
  try{results=await fetchVideos(ids)}catch(error){
   for(const e of targets)await failClaim(db,e.event_hash,e.claimToken,error.message);
   return {updated:0,failed:targets.length,ignored_stale_roster,deleted_notices,reconcile_required,quota_units:1};
  }
  if(!Array.isArray(results)){
   for(const e of targets)await failClaim(db,e.event_hash,e.claimToken,'malformed videos.list result');
   return {updated:0,failed:targets.length,ignored_stale_roster,deleted_notices,reconcile_required,quota_units:1};
  }
 }
 const byId=new Map(results.map(v=>[v.id,v]));
 const currentById=new Map();
 if(ids.length){
  const placeholders=ids.map(()=>'?').join(',');
  const currentRows=await db.prepare(`SELECT video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,
   lifecycle_state,scheduled_start,actual_start,actual_end FROM public_today_canonical WHERE video_id IN (${placeholders})`)
   .bind(...ids).all();
  for(const row of currentRows.results??[])currentById.set(row.video_id,row);
 }
 const observed_at=now.toISOString().replace(/\.\d{3}Z$/,'Z');
 let updated=0,failed=0,ignored_non_live=0,unchanged=0,ignored_terminal_regression=0;
 for(const e of events){
  try{
   const v=byId.get(e.video_id),s=v?.snippet,d=v?.liveStreamingDetails??{};
   if(!s||s.channelId!==e.channel_id||e.roster_version!==roster.version||!approved.has(e.channel_id))throw Error('unverified video/channel');
   const fmt=x=>x?new Date(x).toISOString().replace(/\.\d{3}Z$/,'Z'):null;
   const scheduled=fmt(d.scheduledStartTime),end=fmt(d.actualEndTime),start=fmt(d.actualStartTime);
   const hasLivestreamEvidence=Boolean(
     s.liveBroadcastContent==='live' ||
     s.liveBroadcastContent==='upcoming' ||
     scheduled || start || end
   );
   if(!hasLivestreamEvidence){
     await finishClaim(db,e.event_hash,e.claimToken,{now});
     ignored_non_live++;
     continue;
   }
   const lifecycle_state=end?'ended':s.liveBroadcastContent==='live'?'live':
     s.liveBroadcastContent==='upcoming'?'upcoming':start?'live':'unknown';
   const group=approved.get(e.channel_id);
   const current=currentById.get(v.id)??null;
   if(current&&current.publisher_channel_id!==e.channel_id)throw Error('canonical publisher mismatch');
   if(current&&current.lifecycle_state==='ended'&&lifecycle_state!=='ended'){
    // Ended is terminal; a later duplicate/pending notice cannot resurrect it.
    await finishClaim(db,e.event_hash,e.claimToken,{now});ignored_terminal_regression++;continue;
   }
   const same=Boolean(current)&&current.roster_version===roster.version&&current.channel_group===group&&
    current.title===String(s.title??'')&&current.channel_name===String(s.channelTitle??'')&&
    current.lifecycle_state===lifecycle_state&&current.scheduled_start===scheduled&&
    current.actual_start===start&&current.actual_end===end;
   if(same){
    await finishClaim(db,e.event_hash,e.claimToken,{now});unchanged++;continue;
   }
   await writeEvidence(db,{video_id:v.id,channel_id:e.channel_id,group,roster_version:roster.version,
    title:s.title,channel_name:s.channelTitle??'',lifecycle_state,observed_at,scheduled_start:scheduled,
    actual_start:start,actual_end:end,source_label:'YouTube'});
   await finishClaim(db,e.event_hash,e.claimToken,{now});updated++;
  }catch(error){
   try{await failClaim(db,e.event_hash,e.claimToken,error.message)}catch{}
   failed++
  }
 }
 return {updated,failed,ignored_non_live,unchanged,ignored_terminal_regression,ignored_stale_roster,deleted_notices,reconcile_required,quota_units:ids.length?1:0,complete:false};
}
