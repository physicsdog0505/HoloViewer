/** Bounded public Atom feed reconciliation for missed WebSub events.
 * Inject fetchFeed and durable D1 queue. Does not touch YouTube search.list.
 */
import {persistEvent} from './websub-store.mjs';
import {nextReconcileWindow,commitReconcileWindow} from './websub-hardening.mjs';
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/,VIDEO=/^[A-Za-z0-9_-]{11}$/;
function entries(xml){
 if(typeof xml!=='string'||xml.length>262144||/<!DOCTYPE|<!ENTITY/i.test(xml))throw Error('invalid feed');
 const result=[];
 for(const block of xml.match(/<entry\b[^>]*>[\s\S]*?<\/entry>/g)??[]){
  const video=block.match(/<yt:videoId>\s*([^<]+)<\/yt:videoId>/)?.[1]?.trim();
  const channel=block.match(/<yt:channelId>\s*([^<]+)<\/yt:channelId>/)?.[1]?.trim();
  if(!VIDEO.test(video??'')||!CHANNEL.test(channel??''))throw Error('feed identity invalid');
  result.push({video_id:video,channel_id:channel});
 }
 return result;
}
export async function reconcileAtomFeeds({db,roster,fetchFeed,now=new Date(),maxChannels=3}={}){
 if(!db?.prepare||typeof fetchFeed!=='function'||!roster?.version||!Array.isArray(roster.channels)
   ||!Number.isInteger(maxChannels)||maxChannels<1||maxChannels>10)throw Error('invalid feed reconciliation');
 const window=await nextReconcileWindow(db,roster,{now,limit:maxChannels});
 const channels=window.selected,ids=new Set(),record={channels:0,discovered:0,failed:0,more_channels:roster.channels.length>maxChannels};
 for(const channel of channels){
  if(!CHANNEL.test(channel.id)||ids.has(channel.id))throw Error('bad approved channel');
  ids.add(channel.id);
  try{
   const xml=await fetchFeed('https://www.youtube.com/feeds/videos.xml?channel_id='+channel.id);
   const items=entries(xml);
   if(items.length>20)throw Error('feed event bound exceeded');
   for(const entry of items){
    if(entry.channel_id!==channel.id)throw Error('cross-channel feed');
    const bytes=new TextEncoder().encode('feed-reconcile-v1:'+channel.id+':'+entry.video_id+':'+roster.version);
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
    await persistEvent(db,{raw_sha256:hash,channel_id:channel.id,video_id:entry.video_id,roster_version:roster.version},{now});
    record.discovered++;
   }
   record.channels++;
  }catch(error){record.failed++;break;}
 }
 if(!record.failed)await commitReconcileWindow(db,window);
 return {...record,status:record.failed?'STOP_REVIEW':'PARTIAL_DISCOVERY',gap:true};
}
