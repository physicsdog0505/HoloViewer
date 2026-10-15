import {persistEvent} from './websub-store.mjs';
import {nextReconcileWindow,commitReconcileWindow} from './websub-hardening.mjs';
import {refreshPendingVideos} from './websub-status.mjs';

const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const VIDEO=/^[A-Za-z0-9_-]{11}$/;
const MAX_FEED_BYTES=262144;
const FEED_ENTRIES_PER_CHANNEL=2;
const CHANNELS_PER_WAVE=10;
const WAVES_PER_RUN=3;

function entries(xml){
  if(typeof xml!=='string'||xml.length>MAX_FEED_BYTES||/<!DOCTYPE|<!ENTITY/i.test(xml))
    throw Error('invalid feed');
  const out=[];
  for(const block of xml.match(/<entry\b[^>]*>[\s\S]*?<\/entry>/g)??[]){
    const video=block.match(/<yt:videoId>\s*([^<]+)<\/yt:videoId>/)?.[1]?.trim();
    const channel=block.match(/<yt:channelId>\s*([^<]+)<\/yt:channelId>/)?.[1]?.trim();
    if(!VIDEO.test(video??'')||!CHANNEL.test(channel??''))continue;
    out.push({video_id:video,channel_id:channel});
    if(out.length>=FEED_ENTRIES_PER_CHANNEL)break;
  }
  return out;
}

async function loadApprovedRoster(db){
  const meta=await db.prepare(
    'SELECT roster_version FROM public_today_catalog_meta WHERE singleton=1'
  ).first();
  if(!meta?.roster_version)throw Error('Today roster metadata unavailable');
  const got=await db.prepare(
    'SELECT channel_id,channel_group FROM public_today_approved_channels WHERE roster_version=? ORDER BY channel_id'
  ).bind(meta.roster_version).all();
  const rows=got.results??[];
  if(!rows.length||rows.length>500)throw Error('approved Today roster unavailable');
  const channels=rows.map(row=>({id:row.channel_id,group:row.channel_group}));
  if(channels.some(x=>!CHANNEL.test(x.id)))throw Error('invalid approved channel identity');
  return {version:meta.roster_version,channels};
}

async function fetchFeed(channel,fetchImpl){
  const url='https://www.youtube.com/feeds/videos.xml?channel_id='+channel.id;
  const response=await fetchImpl(url,{
    headers:{accept:'application/atom+xml'},
    signal:AbortSignal.timeout(12000)
  });
  if(!response.ok)throw Error('Atom feed unavailable '+response.status);
  const size=Number(response.headers?.get?.('content-length')??0);
  if(size>MAX_FEED_BYTES)throw Error('Atom feed too large');
  const xml=await response.text();
  return entries(xml).filter(x=>x.channel_id===channel.id);
}

async function reconcileWave(db,roster,{fetchImpl,now}){
  const window=await nextReconcileWindow(db,roster,{now,limit:CHANNELS_PER_WAVE});
  const results=await Promise.all(window.selected.map(async channel=>({
    channel,
    items:await fetchFeed(channel,fetchImpl)
  })));
  let discovered=0;
  for(const result of results){
    for(const entry of result.items){
      const bytes=new TextEncoder().encode(
        'feed-reconcile-v2:'+entry.channel_id+':'+entry.video_id+':'+roster.version
      );
      const hash=Array.from(
        new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),
        b=>b.toString(16).padStart(2,'0')
      ).join('');
      await persistEvent(db,{
        raw_sha256:hash,
        channel_id:entry.channel_id,
        video_id:entry.video_id,
        roster_version:roster.version
      },{now});
      discovered++;
    }
  }
  await commitReconcileWindow(db,window);
  return {channels:window.selected.length,discovered};
}

function videoFetcher(env,fetchImpl){
  return async ids=>{
    if(!Array.isArray(ids)||!ids.length||ids.length>50||ids.some(id=>!VIDEO.test(id)))
      throw Error('invalid YouTube batch');
    const url=new URL('https://www.googleapis.com/youtube/v3/videos');
    url.searchParams.set('part','snippet,liveStreamingDetails');
    url.searchParams.set('id',ids.join(','));
    url.searchParams.set('key',String(env.YOUTUBE_API_KEY));
    const response=await fetchImpl(url.toString(),{
      headers:{accept:'application/json'},
      signal:AbortSignal.timeout(12000)
    });
    if(!response.ok)throw Error('YouTube videos.list failed HTTP '+response.status);
    const body=await response.json();
    if(!Array.isArray(body.items))throw Error('malformed videos.list');
    return body.items;
  };
}

export async function refreshTodayDiscovery(env,{fetchImpl=fetch,now=new Date()}={}){
  if(env?.TODAY_DISCOVERY_ENABLED!=='true')
    return {status:'disabled',feed_requests:0,channels:0,discovered:0,updated:0};
  if(!env?.DB?.prepare||!env?.YOUTUBE_API_KEY)throw Error('Today discovery configuration missing');

  const roster=await loadApprovedRoster(env.DB);
  let channels=0,discovered=0;
  for(let i=0;i<WAVES_PER_RUN;i++){
    const wave=await reconcileWave(env.DB,roster,{fetchImpl,now});
    channels+=wave.channels;
    discovered+=wave.discovered;
  }
  const status=await refreshPendingVideos({
    db:env.DB,
    roster,
    fetchVideos:videoFetcher(env,fetchImpl),
    now,
    limit:50
  });
  return {
    status:'reconciled',
    roster_version:roster.version,
    feed_requests:channels,
    channels,
    discovered,
    updated:status.updated??0,
    failed:status.failed??0,
    quota_units:status.quota_units??0
  };
}
