import {refreshTodayDiscovery} from './discovery-refresh.mjs';
import {writeEvidence,YOUTUBE_LIVE_SOURCE} from './store.mjs';
import {fetchYoutubeVideoItems} from './youtube-metadata-provider.mjs';

const ID=/^[A-Za-z0-9_-]{11}$/;
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
export const PROVIDER_MISS_RETIRE_THRESHOLD=3;

function iso(x){return x?new Date(x).toISOString().replace(/\.\d{3}Z$/,'Z'):null;}
function recentTaipeiCutoff(now){
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  return new Date(new Date(day+'T00:00:00+08:00').getTime()-6*86400000).toISOString().replace(/\.\d{3}Z$/,'Z');
}

function placeholders(values){return values.map(()=>'?').join(',');}
function same(a,b){return (a??null)===(b??null);}
function evidenceFor(base,v,observed_at){
  const lifecycle=v.lifecycle_state==='waiting'?'upcoming':v.lifecycle_state;
  return {
    video_id:base.video_id,
    channel_id:base.publisher_channel_id,
    roster_version:base.roster_version,
    group:base.channel_group,
    title:String(v.title??base.title??''),
    channel_name:String(v.channel_name??base.channel_name??''),
    lifecycle_state:lifecycle,
    observed_at,
    scheduled_start:v.scheduled_start??null,
    actual_start:v.actual_start??null,
    actual_end:v.actual_end??null,
    concurrent_viewers:v.concurrent_viewers??null,
    source_label:YOUTUBE_LIVE_SOURCE
  };
}
function lifecycleFactsChanged(base,evidence){
  return base.source_label!==evidence.source_label ||
    base.lifecycle_state!==evidence.lifecycle_state ||
    base.title!==evidence.title ||
    base.channel_name!==evidence.channel_name ||
    !same(base.scheduled_start,evidence.scheduled_start) ||
    !same(base.actual_start,evidence.actual_start) ||
    !same(base.actual_end,evidence.actual_end);
}
async function preloadProviderMisses(db,ids){
  if(!ids.length)return new Map();
  const rows=await db.prepare(`SELECT video_id,miss_count FROM public_today_provider_misses WHERE video_id IN (${placeholders(ids)})`)
    .bind(...ids).all();
  return new Map((rows.results??[]).map(row=>[row.video_id,Number(row.miss_count??0)]));
}
async function preloadEvidence(db,ids,observed_at){
  if(!ids.length)return new Map();
  const rows=await db.prepare(`SELECT video_id,checksum FROM public_today_evidence
    WHERE observed_at=? AND source_label=? AND video_id IN (${placeholders(ids)})`)
    .bind(observed_at,YOUTUBE_LIVE_SOURCE,...ids).all();
  return new Map((rows.results??[]).map(row=>[row.video_id,row]));
}
async function preloadCatalogAvatars(db,channelIds){
  const ids=[...new Set(channelIds.filter(id=>CHANNEL.test(id??'')))];
  if(!ids.length)return new Map();
  const rows=await db.prepare(`SELECT channel_id,avatar_url,actual_start,scheduled_start,video_id FROM public_catalog
    WHERE channel_id IN (${placeholders(ids)}) AND avatar_url IS NOT NULL
    ORDER BY channel_id,COALESCE(actual_start,scheduled_start) DESC,video_id DESC`)
    .bind(...ids).all();
  const out=new Map();
  for(const row of rows.results??[])if(!out.has(row.channel_id))out.set(row.channel_id,row.avatar_url);
  return out;
}

export const LIFECYCLE_CANDIDATE_SQL=`
    WITH candidate_ids AS (
      SELECT video_id,checked_at FROM (
        SELECT video_id,checked_at
        FROM public_today_canonical
        WHERE lifecycle_state!='ended'
        ORDER BY checked_at ASC,video_id ASC
        LIMIT ?
      )
      UNION ALL
      SELECT video_id,checked_at FROM (
        SELECT video_id,checked_at
        FROM public_today_canonical
        WHERE lifecycle_state='ended'
          AND actual_end>=?
          AND (source_label!=? OR actual_start IS NULL OR actual_end IS NULL)
        ORDER BY checked_at ASC,video_id ASC
        LIMIT ?
      )
    ),
    selected AS (
      SELECT video_id,checked_at
      FROM candidate_ids
      ORDER BY checked_at ASC,video_id ASC
      LIMIT ?
    )
    SELECT c.video_id,c.publisher_channel_id,c.roster_version,c.channel_group,c.title,c.channel_name,c.lifecycle_state,c.lifecycle_observed_at,
      c.checked_at,c.scheduled_start,c.actual_start,c.actual_end,c.source_label,c.source_checksum,
      EXISTS(
        SELECT 1 FROM public_today_websub_events e
        WHERE e.video_id=c.video_id AND e.status='processed'
      ) AS from_discovery
    FROM selected s
    JOIN public_today_canonical c ON c.video_id=s.video_id
    ORDER BY s.checked_at ASC,s.video_id ASC`;

export async function refreshKnownTodayLifecycle(env,{fetchImpl=fetch,now=new Date(),limit=50}={}){
  if(env?.TODAY_CADENCE_ENABLED!=='true')return {status:'disabled',requests:0,updated:0,read_queries:0};
  if(!env?.DB?.prepare||!env?.YOUTUBE_API_KEY)throw Error('Today cadence configuration missing');
  if(!Number.isInteger(limit)||limit<1||limit>50)throw Error('invalid lifecycle refresh limit');

  let read_queries=1;
  const got=await env.DB.prepare(LIFECYCLE_CANDIDATE_SQL)
    .bind(limit,recentTaipeiCutoff(now),YOUTUBE_LIVE_SOURCE,limit,limit).all();
  const rows=got.results??[];
  const ids=rows.map(r=>r.video_id).filter(id=>ID.test(id??''));
  if(!ids.length)return {status:'idle',requests:0,updated:0,selected:0,read_queries};

  const providerRows=await fetchYoutubeVideoItems(env,ids,{fetchImpl,now});
  const byId=new Map(providerRows.map(item=>[item.video_id,item]));
  const expected=new Map(rows.map(r=>[r.video_id,r]));
  const observed_at=now.toISOString().replace(/\.\d{3}Z$/,'Z');

  const missCounts=await preloadProviderMisses(env.DB,ids);
  read_queries++;

  const missUpserts=[];
  const missCleanup=new Set();
  const retireLive=new Set();
  const removeNonLive=new Set();
  const unchangedIds=[];
  const changed=[];
  let missing=0,removed_non_live=0,retired_missing=0;

  for(const id of ids){
    const base=expected.get(id),v=byId.get(id);
    if(!base||!v){
      missing++;
      if(base?.lifecycle_state==='live'){
        const next=(missCounts.get(id)??0)+1;
        if(next>=PROVIDER_MISS_RETIRE_THRESHOLD){
          retireLive.add(id);
          if(missCounts.has(id))missCleanup.add(id);
          retired_missing++;
        }else{
          missUpserts.push(env.DB.prepare(`INSERT INTO public_today_provider_misses(video_id,first_missing_at,last_missing_at,miss_count)
            VALUES(?,?,?,1)
            ON CONFLICT(video_id) DO UPDATE SET
              last_missing_at=excluded.last_missing_at,
              miss_count=public_today_provider_misses.miss_count+1`).bind(id,observed_at,observed_at));
        }
      }else if(missCounts.has(id)){
        // Re-verification omission must never erase durable ENDED identity/history.
        missCleanup.add(id);
      }
      continue;
    }

    if(missCounts.has(id))missCleanup.add(id);
    if(!CHANNEL.test(base.publisher_channel_id??'')||v.channel_id!==base.publisher_channel_id)throw Error('publisher mismatch');

    const actualEnd=v.actual_end,actualStart=v.actual_start,scheduled=v.scheduled_start;
    const hasLivestreamEvidence=Boolean(
      actualEnd || actualStart || scheduled ||
      v.lifecycle_state==='live' || v.lifecycle_state==='upcoming' || v.lifecycle_state==='waiting'
    );
    if(!hasLivestreamEvidence && Boolean(base.from_discovery)){
      removeNonLive.add(id);
      removed_non_live++;
      continue;
    }

    const evidence=evidenceFor(base,v,observed_at);
    if(lifecycleFactsChanged(base,evidence))changed.push({base,evidence});
    else unchangedIds.push(id);
  }

  const changedIds=changed.map(x=>x.evidence.video_id);
  const evidenceReplay=changedIds.length
    ? await preloadEvidence(env.DB,changedIds,observed_at)
    : new Map();
  if(changedIds.length)read_queries++;

  const endedChannels=changed.filter(x=>x.evidence.lifecycle_state==='ended').map(x=>x.evidence.channel_id);
  const catalogAvatars=endedChannels.length
    ? await preloadCatalogAvatars(env.DB,endedChannels)
    : new Map();
  if(endedChannels.length)read_queries++;

  const mutations=[...missUpserts];
  if(unchangedIds.length){
    const viewerCases=unchangedIds.map(()=> 'WHEN ? THEN ?').join(' ');
    const viewerBinds=unchangedIds.flatMap(id=>[
      id,
      byId.get(id)?.concurrent_viewers??null
    ]);
    mutations.push(env.DB.prepare(`UPDATE public_today_canonical
      SET checked_at=?,
          concurrent_viewers=CASE video_id ${viewerCases} ELSE NULL END
      WHERE video_id IN (${placeholders(unchangedIds)})`)
      .bind(observed_at,...viewerBinds,...unchangedIds));
  }
  if(retireLive.size){
    const retire=[...retireLive];
    mutations.push(env.DB.prepare(`DELETE FROM public_today_canonical
      WHERE lifecycle_state='live' AND video_id IN (${placeholders(retire)})`).bind(...retire));
    for(const id of retire)missCleanup.add(id);
  }
  if(removeNonLive.size){
    const removed=[...removeNonLive];
    mutations.push(env.DB.prepare(`DELETE FROM public_today_canonical
      WHERE video_id IN (${placeholders(removed)})`).bind(...removed));
    for(const id of removed)if(missCounts.has(id))missCleanup.add(id);
  }
  if(missCleanup.size){
    const cleanup=[...missCleanup];
    mutations.push(env.DB.prepare(`DELETE FROM public_today_provider_misses
      WHERE video_id IN (${placeholders(cleanup)})`).bind(...cleanup));
  }
  if(mutations.length)await env.DB.batch(mutations);

  let updated=0;
  for(const item of changed){
    const result=await writeEvidence(env.DB,item.evidence,{
      preloadedEvidence:evidenceReplay.get(item.evidence.video_id)??null,
      preloadedCurrent:item.base,
      preloadedCatalogAvatar:catalogAvatars.get(item.evidence.channel_id)??null
    });
    if(result.changed)updated++;
  }

  return {
    status:'refreshed',
    requests:1,
    selected:ids.length,
    updated,
    unchanged:unchangedIds.length,
    missing,
    removed_non_live,
    retired_missing,
    read_queries
  };
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
