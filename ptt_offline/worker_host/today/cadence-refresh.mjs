import {refreshTodayDiscovery} from './discovery-refresh.mjs';
import {writeEvidence} from './store.mjs';
import {readLifecycleCursor,commitLifecycleCursor} from './websub-hardening.mjs';

const ID=/^[A-Za-z0-9_-]{11}$/;
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const MAX_LIFECYCLE_WATERMARKS=500;

function iso(x){return x?new Date(x).toISOString().replace(/\.\d{3}Z$/,'Z'):null;}

export async function refreshKnownTodayLifecycle(env,{fetchImpl=fetch,now=new Date(),limit=50}={}){
  if(env?.TODAY_CADENCE_ENABLED!=='true')return {status:'disabled',requests:0,updated:0};
  if(!env?.DB?.prepare||!env?.YOUTUBE_API_KEY)throw Error('Today cadence configuration missing');
  if(!Number.isInteger(limit)||limit<1||limit>50)throw Error('invalid lifecycle refresh limit');

  const meta=await env.DB.prepare('SELECT roster_version FROM public_today_catalog_meta WHERE singleton=1').first();
  const rosterVersion=meta?.roster_version;
  if(typeof rosterVersion!=='string'||!rosterVersion)return {status:'idle',requests:0,updated:0,selected:0};
  const cursorState=await readLifecycleCursor(env.DB,rosterVersion);
  const cursor=cursorState.lastVideoId;
  const checkedAtByVideo={...cursorState.checkedAtByVideo};
  const selectSql=`
    SELECT public_today_canonical.video_id,public_today_canonical.publisher_channel_id,
      public_today_canonical.roster_version,public_today_canonical.channel_group,ac.channel_group AS approved_group,
      public_today_canonical.title,public_today_canonical.channel_name,public_today_canonical.lifecycle_state,
      public_today_canonical.lifecycle_observed_at,public_today_canonical.scheduled_start,
      public_today_canonical.actual_start,public_today_canonical.actual_end,
      EXISTS(SELECT 1 FROM public_today_websub_events e
        WHERE e.video_id=public_today_canonical.video_id AND e.status='processed') AS from_discovery
    FROM public_today_canonical
    JOIN public_today_approved_channels ac
      ON ac.channel_id=public_today_canonical.publisher_channel_id AND ac.roster_version=?
    WHERE public_today_canonical.lifecycle_state!='ended'
      AND public_today_canonical.video_id>?
    ORDER BY public_today_canonical.video_id ASC LIMIT ?`;
  let rows=(await env.DB.prepare(selectSql).bind(rosterVersion,cursor,limit).all()).results??[];
  // Wrap only when the cursor is at the end. Do not fill a short tail with the
  // beginning of the list: that would repeatedly check overlapping batches.
  if(!rows.length&&cursor){
    rows=(await env.DB.prepare(selectSql).bind(rosterVersion,'',limit).all()).results??[];
  }
  const ids=rows.map(r=>r.video_id).filter(id=>ID.test(id??''));
  if(!ids.length)return {status:'idle',requests:0,updated:0,selected:0,unchanged:0};
  const url=new URL('https://www.googleapis.com/youtube/v3/videos');
  url.searchParams.set('part','snippet,liveStreamingDetails');
  url.searchParams.set('id',ids.join(','));
  url.searchParams.set('key',String(env.YOUTUBE_API_KEY));
  const response=await fetchImpl(url.toString(),{
    headers:{accept:'application/json'},
    signal:AbortSignal.timeout(12000)
  });
  if(!response.ok)throw Error('YouTube videos.list failed HTTP '+response.status);
  const payload=await response.json();
  if(!Array.isArray(payload.items))throw Error('malformed videos.list');
  const byId=new Map(payload.items.map(item=>[item.id,item]));
  const expected=new Map(rows.map(r=>[r.video_id,r]));
  const observed_at=now.toISOString().replace(/\.\d{3}Z$/,'Z');
  let updated=0,missing=0,removed_non_live=0,unchanged=0;
  for(const id of ids){
    const base=rows.find(r=>r.video_id===id),v=byId.get(id),snippet=v?.snippet,d=v?.liveStreamingDetails??{};
    if(!base||!v||!snippet){missing++;continue;}
    if(!CHANNEL.test(base.publisher_channel_id??'')||snippet.channelId!==base.publisher_channel_id)throw Error('publisher mismatch');
    const actualEnd=iso(d.actualEndTime),actualStart=iso(d.actualStartTime),scheduled=iso(d.scheduledStartTime);
    const hasLivestreamEvidence=Boolean(actualEnd||actualStart||scheduled||
      snippet.liveBroadcastContent==='live'||snippet.liveBroadcastContent==='upcoming');
    if(!hasLivestreamEvidence){
      if(Boolean(base.from_discovery)){
        await env.DB.prepare('DELETE FROM public_today_canonical WHERE video_id=?').bind(id).run();
        delete checkedAtByVideo[id];
        removed_non_live++;
      }else if(base.lifecycle_state!=='unknown'||base.scheduled_start||base.actual_start||base.actual_end){
        // A previously active row that has lost all positive livestream evidence
        // must transition once to unknown; never repeatedly write the same unknown snapshot.
        const result=await writeEvidence(env.DB,{
          video_id:id,channel_id:base.publisher_channel_id,roster_version:rosterVersion,
          group:base.approved_group??base.channel_group,title:String(snippet.title??''),
          channel_name:String(snippet.channelTitle??''),lifecycle_state:'unknown',observed_at,
          scheduled_start:null,actual_start:null,actual_end:null,source_label:'YouTube'
        });
        if(result.changed)updated++;else unchanged++;
        checkedAtByVideo[id]=observed_at;
      }else{
        checkedAtByVideo[id]=observed_at;
        unchanged++;
      }
      continue;
    }
    const lifecycle=actualEnd?'ended':snippet.liveBroadcastContent==='live'?'live':
      snippet.liveBroadcastContent==='upcoming'?'upcoming':actualStart?'live':'unknown';
    const title=String(snippet.title??'');
    const channelName=String(snippet.channelTitle??'');
    const group=base.approved_group??base.channel_group;
    const same=
      base.lifecycle_state===lifecycle &&
      base.title===title &&
      base.channel_name===channelName &&
      base.scheduled_start===scheduled &&
      base.actual_start===actualStart &&
      base.actual_end===actualEnd &&
      base.roster_version===rosterVersion &&
      base.channel_group===group;
    if(same){checkedAtByVideo[id]=observed_at;unchanged++;continue;}
    const result=await writeEvidence(env.DB,{
      video_id:id,channel_id:base.publisher_channel_id,roster_version:rosterVersion,group,
      title,channel_name:channelName,lifecycle_state:lifecycle,observed_at,
      scheduled_start:scheduled,actual_start:actualStart,actual_end:actualEnd,source_label:'YouTube'
    });
    checkedAtByVideo[id]=observed_at;
    if(result.changed)updated++;else unchanged++;
  }
  // Keep the freshness receipt bounded while covering the 200-card Today read window
  // plus headroom. The singleton cursor is the only periodic D1 write on an unchanged sweep.
  const watermarkEntries=Object.entries(checkedAtByVideo)
    .filter(([id,time])=>ID.test(id)&&typeof time==='string'&&Number.isFinite(Date.parse(time)))
    .sort((a,b)=>Date.parse(a[1])-Date.parse(b[1]));
  while(watermarkEntries.length>MAX_LIFECYCLE_WATERMARKS){
    const [expired]=watermarkEntries.shift();
    delete checkedAtByVideo[expired];
  }
  const lastVideoId=ids[ids.length-1];
  if(lastVideoId){
    await commitLifecycleCursor(env.DB,{rosterVersion,lastVideoId,checkedAtByVideo,now});
  }
  return {status:'refreshed',requests:1,selected:ids.length,updated,unchanged,missing,removed_non_live};
}

export function shouldRunLifecycleRefresh(now){
  if(!(now instanceof Date)||Number.isNaN(now.getTime()))throw Error('invalid lifecycle cadence time');
  return now.getUTCMinutes()%5===0;
}

export function mountTodayCadence(base,{fetchImpl=fetch}={}){
  if(!base||typeof base.fetch!=='function')throw Error('existing combined worker required');
  return {
    fetch:(request,env,ctx)=>base.fetch(request,env,ctx),
    async scheduled(event,env,ctx){
      if(typeof base.scheduled==='function')await base.scheduled(event,env,ctx);
      const now=Number.isFinite(event?.scheduledTime)?new Date(event.scheduledTime):new Date();
      const lifecycle=shouldRunLifecycleRefresh(now)
        ? await refreshKnownTodayLifecycle(env,{fetchImpl,now})
        : {status:'cadence_skip',requests:0,updated:0};
      const discovery=await refreshTodayDiscovery(env,{fetchImpl,now});
      return {lifecycle,discovery};
    }
  };
}
