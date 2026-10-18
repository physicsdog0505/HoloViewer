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

export async function auditWebSubPrimaryCoverage(db,{now=new Date()}={}){
  if(!db?.prepare||!(now instanceof Date)||!Number.isFinite(now.getTime()))
    return {status:'HOLD',reason:'invalid_coverage_input'};
  try{
    const meta=await db.prepare(
      'SELECT roster_version,expected_channels FROM public_today_catalog_meta WHERE singleton=1'
    ).first();
    if(typeof meta?.roster_version!=='string'||!meta.roster_version||
       !Number.isInteger(meta.expected_channels)||meta.expected_channels<1||meta.expected_channels>500)
      return {status:'HOLD',reason:'approved_roster_unavailable'};
    const approved=await db.prepare(
      'SELECT COUNT(*) AS n FROM public_today_approved_channels WHERE roster_version=?'
    ).bind(meta.roster_version).first();
    const leases=await db.prepare(
      `SELECT COUNT(*) AS n FROM public_today_websub_leases
       WHERE roster_version=? AND state='active' AND expires_at>?`
    ).bind(meta.roster_version,now.toISOString().replace(/\.\d{3}Z$/,'Z')).first();
    const approvedCount=Number(approved?.n??0),activeCount=Number(leases?.n??0);
    const ready=approvedCount===meta.expected_channels&&activeCount===meta.expected_channels;
    return {status:ready?'PASS':'HOLD',roster_version:meta.roster_version,
      expected_channels:meta.expected_channels,approved_channels:approvedCount,active_leases:activeCount,
      reason:ready?null:'incomplete_active_lease_coverage'};
  }catch{
    return {status:'HOLD',reason:'coverage_schema_unavailable'};
  }
}

export async function reconcileTodayChannelsViaAtom(env,{roster,channelIds,fetchImpl=fetch,now=new Date(),limit=5}={}){
  if(!env?.DB?.prepare||!roster?.version||!Array.isArray(roster.channels)||
     !Array.isArray(channelIds)||!Number.isInteger(limit)||limit<1||limit>10)
    throw Error('invalid bounded Atom reconciliation input');
  const approved=new Map(roster.channels.map(c=>[c.id,c]));
  const unique=[...new Set(channelIds)].filter(id=>approved.has(id)&&CHANNEL.test(id)).slice(0,limit);
  let channels=0,feed_entries=0,discovered=0,failed=0;
  for(const id of unique){
    const channel=approved.get(id);
    try{
      const items=await fetchFeed(channel,fetchImpl);
      channels++;
      for(const entry of items){
        feed_entries++;
        const bytes=new TextEncoder().encode(
          'feed-reconcile-v2:'+entry.channel_id+':'+entry.video_id+':'+roster.version
        );
        const hash=Array.from(
          new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),
          b=>b.toString(16).padStart(2,'0')
        ).join('');
        const stored=await persistEvent(env.DB,{
          raw_sha256:hash,channel_id:entry.channel_id,video_id:entry.video_id,roster_version:roster.version
        },{now});
        if(stored.inserted)discovered++;
      }
    }catch{failed++;}
  }
  return {status:'bounded_atom_reconcile',channels,feed_entries,discovered,failed};
}

async function reconcileWave(db,roster,{fetchImpl,now}){
  const window=await nextReconcileWindow(db,roster,{now,limit:CHANNELS_PER_WAVE});
  const settled=await Promise.allSettled(window.selected.map(async channel=>({
    channel,
    items:await fetchFeed(channel,fetchImpl)
  })));
  let discovered=0,failed=0;
  for(const item of settled){
    if(item.status!=='fulfilled'){failed++;continue;}
    const result=item.value;
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
  // Never let one temporarily unavailable channel freeze the rotating discovery
  // cursor forever. Successful channels are durable; failed channels are revisited
  // on the next roster rotation and the run reports an explicit gap count.
  await commitReconcileWindow(db,window);
  return {channels:window.selected.length,discovered,failed};
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
  if(env?.TODAY_WEBSUB_PRIMARY_ENABLED==='true'&&env?.TODAY_ATOM_FALLBACK_ENABLED!=='true'){
    const configured=env?.TODAY_WEBSUB_RECEIVER_ENABLED==='true'&&
      env?.TODAY_WEBSUB_PROCESS_ENABLED==='true'&&env?.TODAY_WEBSUB_RENEW_ENABLED==='true'&&
      typeof env?.TODAY_WEBSUB_CALLBACK_URL==='string'&&
      typeof env?.TODAY_WEBSUB_SECRET==='string'&&env.TODAY_WEBSUB_SECRET.length>=32&&
      typeof env?.YOUTUBE_API_KEY==='string'&&env.YOUTUBE_API_KEY.length>0;
    if(!configured)return {status:'blocked_websub_primary_not_ready',
      feed_requests:0,channels:0,discovered:0,updated:0};
    const coverage=await auditWebSubPrimaryCoverage(env.DB,{now});
    if(coverage.status!=='PASS')return {status:'blocked_websub_primary_incomplete_coverage',
      coverage,feed_requests:0,channels:0,discovered:0,updated:0};
    return {status:'disabled_websub_primary',coverage,
      feed_requests:0,channels:0,discovered:0,updated:0};
  }
  if(env?.TODAY_DISCOVERY_ENABLED!=='true')
    return {status:'disabled',feed_requests:0,channels:0,discovered:0,updated:0};
  if(!env?.DB?.prepare||!env?.YOUTUBE_API_KEY)throw Error('Today discovery configuration missing');

  const roster=await loadApprovedRoster(env.DB);
  let channels=0,discovered=0,feed_failures=0;
  for(let i=0;i<WAVES_PER_RUN;i++){
    const wave=await reconcileWave(env.DB,roster,{fetchImpl,now});
    channels+=wave.channels;
    discovered+=wave.discovered;
    feed_failures+=wave.failed??0;
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
    feed_failures,
    updated:status.updated??0,
    failed:status.failed??0,
    quota_units:status.quota_units??0
  };
}
