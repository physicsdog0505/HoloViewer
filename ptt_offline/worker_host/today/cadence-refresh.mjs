import {refreshTodayDiscovery} from './discovery-refresh.mjs';
import {writeEvidence,YOUTUBE_LIVE_SOURCE} from './store.mjs';

const ID=/^[A-Za-z0-9_-]{11}$/;
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
export const PROVIDER_MISS_RETIRE_THRESHOLD=3;

function iso(x){return x?new Date(x).toISOString().replace(/\.\d{3}Z$/,'Z'):null;}
function recentTaipeiCutoff(now){
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  return new Date(new Date(day+'T00:00:00+08:00').getTime()-6*86400000).toISOString().replace(/\.\d{3}Z$/,'Z');
}

export async function refreshKnownTodayLifecycle(env,{fetchImpl=fetch,now=new Date(),limit=50}={}){
  if(env?.TODAY_CADENCE_ENABLED!=='true')return {status:'disabled',requests:0,updated:0};
  if(!env?.DB?.prepare||!env?.YOUTUBE_API_KEY)throw Error('Today cadence configuration missing');
  if(!Number.isInteger(limit)||limit<1||limit>50)throw Error('invalid lifecycle refresh limit');

  const got=await env.DB.prepare(`
    SELECT video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_observed_at,
      scheduled_start,actual_start,actual_end,
      EXISTS(
        SELECT 1 FROM public_today_websub_events e
        WHERE e.video_id=public_today_canonical.video_id AND e.status='processed'
      ) AS from_discovery
    FROM public_today_canonical
    WHERE lifecycle_state!='ended'
       OR (lifecycle_state='ended' AND actual_end>=?
           AND (source_label!=? OR actual_start IS NULL OR actual_end IS NULL))
    ORDER BY lifecycle_observed_at ASC,video_id ASC
    LIMIT ?`).bind(recentTaipeiCutoff(now),YOUTUBE_LIVE_SOURCE,limit).all();
  const rows=got.results??[];
  const ids=rows.map(r=>r.video_id).filter(id=>ID.test(id??''));
  if(!ids.length)return {status:'idle',requests:0,updated:0,selected:0};

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
  let updated=0,missing=0,removed_non_live=0,retired_missing=0;

  for(const id of ids){
    const base=expected.get(id),v=byId.get(id),s=v?.snippet,d=v?.liveStreamingDetails??{};
    if(!base||!v||!s){
      missing++;
      await env.DB.prepare(`INSERT INTO public_today_provider_misses(video_id,first_missing_at,last_missing_at,miss_count)
        VALUES(?,?,?,1)
        ON CONFLICT(video_id) DO UPDATE SET
          last_missing_at=excluded.last_missing_at,
          miss_count=public_today_provider_misses.miss_count+1`).bind(id,observed_at,observed_at).run();
      const miss=await env.DB.prepare('SELECT miss_count FROM public_today_provider_misses WHERE video_id=?').bind(id).first();
      if((miss?.miss_count??0)>=PROVIDER_MISS_RETIRE_THRESHOLD){
        await env.DB.batch([
          env.DB.prepare('DELETE FROM public_today_canonical WHERE video_id=?').bind(id),
          env.DB.prepare('DELETE FROM public_today_provider_misses WHERE video_id=?').bind(id)
        ]);
        retired_missing++;
      }
      continue;
    }
    await env.DB.prepare('DELETE FROM public_today_provider_misses WHERE video_id=?').bind(id).run();
    if(!CHANNEL.test(base.publisher_channel_id??'')||s.channelId!==base.publisher_channel_id)throw Error('publisher mismatch');
    const actualEnd=iso(d.actualEndTime),actualStart=iso(d.actualStartTime),scheduled=iso(d.scheduledStartTime);
    const hasLivestreamEvidence=Boolean(
      actualEnd || actualStart || scheduled ||
      s.liveBroadcastContent==='live' || s.liveBroadcastContent==='upcoming'
    );
    if(!hasLivestreamEvidence && Boolean(base.from_discovery)){
      await env.DB.batch([
        env.DB.prepare('DELETE FROM public_today_canonical WHERE video_id=?').bind(id),
        env.DB.prepare('DELETE FROM public_today_provider_misses WHERE video_id=?').bind(id)
      ]);
      removed_non_live++;
      continue;
    }
    const lifecycle=actualEnd?'ended':s.liveBroadcastContent==='live'?'live':
      s.liveBroadcastContent==='upcoming'?'upcoming':actualStart?'live':'unknown';
    await writeEvidence(env.DB,{
      video_id:id,
      channel_id:base.publisher_channel_id,
      roster_version:base.roster_version,
      group:base.channel_group,
      title:String(s.title??base.title??''),
      channel_name:String(s.channelTitle??base.channel_name??''),
      lifecycle_state:lifecycle,
      observed_at,
      scheduled_start:scheduled,
      actual_start:actualStart,
      actual_end:actualEnd,
      source_label:YOUTUBE_LIVE_SOURCE
    });
    updated++;
  }
  return {status:'refreshed',requests:1,selected:ids.length,updated,missing,removed_non_live,retired_missing};
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
