import {getPendingEvents,markEventProcessed,markEventFailed} from './websub-store.mjs';
import {writeEvidence} from './store.mjs';
import {claimEvent,finishClaim,failClaim} from './websub-hardening.mjs';
// Intended for an explicitly configured Cloudflare scheduled handler; no auto activation.
export async function refreshPendingVideos({db,roster,fetchVideos,now=new Date(),limit=25}){
 if(!db?.prepare||typeof fetchVideos!=='function'||!Array.isArray(roster?.channels)||!roster.version||limit<1||limit>50)throw Error('invalid worker configuration');
 const approved=new Map(roster.channels.map(c=>[c.id,c.group]));
 const candidates=await getPendingEvents(db,{limit});
 const owned=[];
 for(const event of candidates){
  const rand=crypto.getRandomValues(new Uint8Array(32));
  const token=Array.from(rand,b=>b.toString(16).padStart(2,'0')).join('');
  if(await claimEvent(db,event.event_hash,token,{now}))owned.push({...event,claimToken:token});
 }
 const events=owned;
 const targets=events.filter(e=>e.video_id&&e.roster_version===roster.version&&approved.has(e.channel_id));
 const ids=[...new Set(targets.map(e=>e.video_id))];
 let results=[];
 if(ids.length){
  try{results=await fetchVideos(ids)}catch(error){
   for(const e of targets)await failClaim(db,e.event_hash,e.claimToken,error.message);
   return {updated:0,failed:targets.length,quota_units:1};
  }
  if(!Array.isArray(results))throw Error('malformed videos.list result');
 }
 const byId=new Map(results.map(v=>[v.id,v]));
 const observed_at=now.toISOString().replace(/\.\d{3}Z$/,'Z');
 let updated=0,failed=0;
 for(const e of events){
  try{
   const v=byId.get(e.video_id),s=v?.snippet,d=v?.liveStreamingDetails??{};
   if(!s||s.channelId!==e.channel_id||e.roster_version!==roster.version||!approved.has(e.channel_id))throw Error('unverified video/channel');
   const fmt=x=>x?new Date(x).toISOString().replace(/\.\d{3}Z$/,'Z'):null;
   const end=fmt(d.actualEndTime),start=fmt(d.actualStartTime);
   const lifecycle_state=end?'ended':s.liveBroadcastContent==='live'?'live':s.liveBroadcastContent==='upcoming'?'upcoming':'unknown';
   await writeEvidence(db,{video_id:v.id,channel_id:e.channel_id,group:approved.get(e.channel_id),roster_version:roster.version,
    title:s.title,channel_name:s.channelTitle??'',lifecycle_state,observed_at,scheduled_start:fmt(d.scheduledStartTime),
    actual_start:start,actual_end:end,source_label:'YouTube'});
   await finishClaim(db,e.event_hash,e.claimToken,{now});updated++;
  }catch(error){await markEventFailed(db,e.event_hash,error.message);failed++}
 }
 return {updated,failed,quota_units:ids.length?1:0,complete:false};
}
