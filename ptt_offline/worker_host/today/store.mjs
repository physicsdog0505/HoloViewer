/**
 * Issue #47, single canonical D1 store. No Cloudflare bindings, network or Cron side effects.
 * Inject a D1-compatible db. A write is an atomic batch of evidence and projection.
 */
import {readChannelProfiles,applyChannelProfile} from './channel-profile.mjs';
const idPattern=/^[A-Za-z0-9_-]{11}$/;
const channelPattern=/^UC[A-Za-z0-9_-]{22}$/;
const groups=new Set(['hololive','holostars','mekpark','other']);
const lifecycles=new Set(['unknown','upcoming','live','ended']);
const ckPattern=/^cp_[A-Za-z0-9_-]{8,128}$/;
export const YOUTUBE_LIVE_SOURCE='YouTube liveStreamingDetails';
export const HISTORY_SOURCE_REVISION='youtube-videos-list:liveStreamingDetails';
// Legacy public_catalog avatar is channel artwork, never the video thumbnail.
export function verifiedChannelAvatar(value){
 if(typeof value!=='string'||value.length>2048)return null;
 try{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password||u.port)return null;
  return ['yt3.ggpht.com','yt3.googleusercontent.com','yt3.google.com'].includes(u.hostname)?u.href:null;
 }catch{return null}
}
function validTime(x) {return typeof x==='string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(x) && !Number.isNaN(Date.parse(x));}
function taipeiDay(value){
 const d=new Date(value);
 return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);
}
export function validateEvidence(r) {
  if (!r || !idPattern.test(r.video_id) || !channelPattern.test(r.channel_id) ||
      typeof r.roster_version!=='string' || !r.roster_version ||
      !groups.has(r.group) || !lifecycles.has(r.lifecycle_state) ||
      !validTime(r.observed_at) || typeof r.title!=='string' ||
      typeof r.source_label!=='string' || !r.source_label) throw Error('invalid Today evidence');
  for (const k of ['scheduled_start','actual_start','actual_end']) if (r[k]!=null && !validTime(r[k])) throw Error('invalid evidence time');
  if (r.actual_start && r.actual_start>r.observed_at || r.actual_end && r.actual_end>r.observed_at) throw Error('future actual evidence');
  if (r.actual_start && r.actual_end && r.actual_end<r.actual_start) throw Error('invalid lifecycle ordering');
  if (r.lifecycle_state==='ended' && !r.actual_end) throw Error('end requires positive evidence');
  return r;
}
function canonicalJson(r) {
  const keys=['video_id','channel_id','roster_version','group','title','channel_name','lifecycle_state','observed_at','scheduled_start','actual_start','actual_end','source_label'];
  return JSON.stringify(Object.fromEntries(keys.map(k=>[k,r[k]??null])));
}
// Stable portable checksum for evidence identity. Non-cryptographic: not a security signature.
export function evidenceChecksum(r) {
  const s=canonicalJson(r);let h=2166136261;
  for (let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}
  return (h>>>0).toString(16).padStart(8,'0');
}
export async function writeEvidence(db, evidence, {projectHistory=true}={}) {
  const r=validateEvidence(evidence), hash=evidenceChecksum(r);
  const oldEvidence=await db.prepare('SELECT checksum FROM public_today_evidence WHERE video_id=? AND observed_at=? AND source_label=?')
    .bind(r.video_id,r.observed_at,r.source_label).first();
  if (oldEvidence) {
    if (oldEvidence.checksum!==hash) throw Error('same-key contradictory evidence');
    return {changed:false,reason:'replay'};
  }
  const current=await db.prepare('SELECT lifecycle_state,lifecycle_observed_at,publisher_channel_id,roster_version,source_checksum FROM public_today_canonical WHERE video_id=?')
    .bind(r.video_id).first();
  if (current && (current.publisher_channel_id!==r.channel_id))
    throw Error('canonical publisher/roster mismatch');
  const newer=(!current || r.observed_at>current.lifecycle_observed_at);
  const canSelect=newer && !(current?.lifecycle_state==='ended' && r.lifecycle_state!=='ended');
  const evidenceSql=`INSERT INTO public_today_evidence
    (video_id,observed_at,source_label,checksum,publisher_channel_id,roster_version,channel_group,lifecycle_state,
     scheduled_start,actual_start,actual_end,title,channel_name)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`;
  const mutations=[db.prepare(evidenceSql).bind(r.video_id,r.observed_at,r.source_label,hash,r.channel_id,r.roster_version,r.group,
    r.lifecycle_state,r.scheduled_start??null,r.actual_start??null,r.actual_end??null,r.title,r.channel_name??'')];
  if (canSelect) {
    const sql=`INSERT INTO public_today_canonical
      (video_id,publisher_channel_id,roster_version,channel_group,title,channel_name,lifecycle_state,
       lifecycle_observed_at,checked_at,scheduled_start,actual_start,actual_end,source_label,source_checksum)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(video_id) DO UPDATE SET
      roster_version=excluded.roster_version,channel_group=excluded.channel_group,title=excluded.title,channel_name=excluded.channel_name,
      lifecycle_state=excluded.lifecycle_state,lifecycle_observed_at=excluded.lifecycle_observed_at,
      checked_at=excluded.checked_at,scheduled_start=excluded.scheduled_start,actual_start=excluded.actual_start,
      actual_end=excluded.actual_end,source_label=excluded.source_label,source_checksum=excluded.source_checksum
      WHERE excluded.lifecycle_observed_at>public_today_canonical.lifecycle_observed_at
        AND (public_today_canonical.lifecycle_state!='ended' OR excluded.lifecycle_state='ended')
        AND public_today_canonical.publisher_channel_id=excluded.publisher_channel_id`;
    mutations.push(db.prepare(sql).bind(r.video_id,r.channel_id,r.roster_version,r.group,r.title,r.channel_name??'',
      r.lifecycle_state,r.observed_at,r.observed_at,r.scheduled_start??null,r.actual_start??null,r.actual_end??null,r.source_label,hash));
    if(projectHistory&&r.lifecycle_state==='ended'&&r.source_label===YOUTUBE_LIVE_SOURCE&&r.actual_start&&r.actual_end){
      const catalogAvatar=await db.prepare(`SELECT avatar_url FROM public_catalog
        WHERE channel_id=? AND avatar_url IS NOT NULL
        ORDER BY COALESCE(actual_start,scheduled_start) DESC,video_id DESC LIMIT 1`).bind(r.channel_id).first();
      const historyAvatar=verifiedChannelAvatar(catalogAvatar?.avatar_url)??'';
      const historySql=`INSERT INTO public_history
        (video_id,taipei_day,title,channel_id,channel_name,avatar_url,scheduled_start,actual_start,actual_end,source_revision,published_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(video_id) DO UPDATE SET
          taipei_day=excluded.taipei_day,title=excluded.title,channel_id=excluded.channel_id,
          channel_name=excluded.channel_name,scheduled_start=excluded.scheduled_start,
          actual_start=excluded.actual_start,actual_end=excluded.actual_end,
          source_revision=excluded.source_revision,published_at=excluded.published_at`;
      mutations.push(db.prepare(historySql).bind(
        r.video_id,taipeiDay(r.actual_start),r.title,r.channel_id,r.channel_name??'',historyAvatar,
        r.scheduled_start??null,r.actual_start,r.actual_end,HISTORY_SOURCE_REVISION,r.observed_at
      ));
    }
  }
  await db.batch(mutations);
  return {changed:canSelect,reason:canSelect?'selected':'evidence_only'};
}
export async function setCoverage(db, c) {
  if (!c || typeof c.roster_version!=='string' || !c.roster_version ||
      !Number.isInteger(c.expected_channels) || !Number.isInteger(c.scanned_channels) ||
      c.scanned_channels<0 || c.scanned_channels>c.expected_channels ||
      (c.last_success_at!=null && !validTime(c.last_success_at))) throw Error('invalid coverage');
  // Fail closed on gap: a fresh scan is not an authoritative completeness proof.
  const sql=`INSERT INTO public_today_catalog_meta(singleton,roster_version,last_success_at,expected_channels,scanned_channels,gap,checkpoint)
    VALUES (1,?,?,?,?,?,?)
    ON CONFLICT(singleton) DO UPDATE SET roster_version=excluded.roster_version,last_success_at=excluded.last_success_at,
      expected_channels=excluded.expected_channels,scanned_channels=excluded.scanned_channels,gap=excluded.gap,checkpoint=excluded.checkpoint`;
  // A roster activation requires explicit approved publisher membership.
  // Atomic replacement also revokes removed channels; no implicit inference from old evidence.
  if (!Array.isArray(c.approved_channels) || c.approved_channels.length!==c.expected_channels)
    throw Error('approved channel manifest required');
  const unique=new Set();
  const statements=[db.prepare('DELETE FROM public_today_approved_channels')];
  for (const channel of c.approved_channels) {
    if (!channelPattern.test(channel.id) || !groups.has(channel.group) || unique.has(channel.id))
      throw Error('invalid approved channel manifest');
    unique.add(channel.id);
    statements.push(db.prepare('INSERT INTO public_today_approved_channels(channel_id,roster_version,activated_at,channel_group) VALUES (?,?,?,?)')
      .bind(channel.id,c.roster_version,c.last_success_at??'1970-01-01T00:00:00Z',channel.group));
  }
  statements.push(db.prepare(sql).bind(c.roster_version,c.last_success_at??null,c.expected_channels,c.scanned_channels,c.gap?1:0,
    typeof c.checkpoint==='string'&&ckPattern.test(c.checkpoint)?c.checkpoint:null));
  await db.batch(statements);
}
/** 4174 Home adapter-safe optional fields: never let one malformed optional cell kill the catalog. */
function consumerText(value){return typeof value==='string'?value:'';}
function consumerTime(value){return validTime(value)?value:null;}
function consumerLifecycle(value){return lifecycles.has(value)?value:'unknown';}
/**
 * Public Home grouping contract.
 * Consumers MUST classify from lifecycle_state + stale only; they must not
 * reconstruct YouTube lifecycle from timestamps or provenance.
 */
export function classifyHomeConsumer(stream){
 const lifecycle=consumerLifecycle(stream?.lifecycle_state);
 const stale=stream?.stale===true;
 if(lifecycle==='live')return stale?'degraded':'current_live';
 if(lifecycle==='unknown')return 'degraded';
 if(lifecycle==='upcoming'||lifecycle==='waiting')return 'upcoming';
 if(lifecycle==='ended')return 'ended';
 return 'degraded';
}
function consumerRow(row,nowStamp,profile){
 const video_id=idPattern.test(row?.video_id??'')?row.video_id:null;
 const channel_id=channelPattern.test(row?.publisher_channel_id??'')?row.publisher_channel_id:null;
 // Broken primary identity is a corrupt candidate, not a fabricated Home card.
 if(!video_id||!channel_id)return null;
 const observed=consumerTime(row.lifecycle_observed_at);
 const age=observed?Date.parse(nowStamp)-Date.parse(observed):NaN;
 const fresh=Number.isFinite(age)&&age>=0&&age<=1200000;
 const state=consumerLifecycle(row.lifecycle_state);
 const source_label=consumerText(row.source_label);
 const trusted=source_label===YOUTUBE_LIVE_SOURCE;
 const actual_start=trusted?consumerTime(row.actual_start):null;
 const actual_end=trusted?consumerTime(row.actual_end):null;
 const lifecycle_state=state==='upcoming'?
  (consumerTime(row.scheduled_start)&&row.scheduled_start<=nowStamp?'waiting':'upcoming'):state;
 const stale=state==='live'&&!fresh;
 return applyChannelProfile({
  video_id,title:consumerText(row.title),channel_id,channel_name:consumerText(row.channel_name),
  channel_group:groups.has(row.channel_group)?row.channel_group:'other',
  trusted_channel_avatar:row.trusted_channel_avatar,
  lifecycle_state,observed_at:observed,
  start_at:actual_start??consumerTime(row.scheduled_start),
  actual_start,actual_end,
  anchor_source:actual_start?'youtube-liveStreamingDetails-actualStartTime':null,
  source_label,stale
 },profile);
}
export async function readToday(db,{day,limit=200,offset=0,now=new Date(),env=null,profileTableEnabled=false}={}) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day||'') || new Date(day+'T00:00:00Z').toISOString().slice(0,10)!==day)
    throw Error('invalid canonical Today day');
  if (!Number.isInteger(limit)||limit<1||limit>200) throw Error('invalid limit');
  if (!Number.isSafeInteger(offset)||offset<0||offset>10000) throw Error('invalid offset');
  const coverage=await db.prepare('SELECT * FROM public_today_catalog_meta WHERE singleton=1').first();
  // 4174 product authority:
  // live = date-independent while provider observation is fresh (20m);
  // upcoming = current Taipei day or future;
  // ended = ended today, plus yesterday until 12:00 Asia/Taipei.
  const requestedStart=new Date(day+'T00:00:00+08:00');
  const nextStart=new Date(requestedStart.getTime()+86400000);
  const previousStart=new Date(requestedStart.getTime()-86400000);
  const noon=new Date(requestedStart.getTime()+12*3600000);
  const localDay=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const beforeNoon=day===localDay&&now.getTime()<noon.getTime();
  const start=requestedStart.toISOString().replace(/\.\d{3}Z$/,'Z');
  const end=nextStart.toISOString().replace(/\.\d{3}Z$/,'Z');
  const previous=previousStart.toISOString().replace(/\.\d{3}Z$/,'Z');
  const nowStamp=now.toISOString().replace(/\.\d{3}Z$/,'Z');
  const freshCutoff=new Date(now.getTime()-1200000).toISOString().replace(/\.\d{3}Z$/,'Z');
  const legacyProfileExpr=profileTableEnabled?`(SELECT p.avatar_url FROM public_today_channel_profiles p WHERE p.channel_id=public_today_canonical.publisher_channel_id AND p.roster_version=ac.roster_version)`:null;
  const rows=await db.prepare(`SELECT public_today_canonical.*,
    ${legacyProfileExpr?`COALESCE(${legacyProfileExpr},`:''}(SELECT c.avatar_url FROM public_catalog c
      WHERE c.channel_id=public_today_canonical.publisher_channel_id AND c.avatar_url IS NOT NULL
      ORDER BY COALESCE(c.actual_start,c.scheduled_start) DESC,c.video_id DESC LIMIT 1)${legacyProfileExpr?')':''} AS trusted_channel_avatar
    FROM public_today_canonical
    JOIN public_today_approved_channels ac
      ON ac.channel_id=public_today_canonical.publisher_channel_id AND ac.roster_version=?
    WHERE (
      (lifecycle_state='live' AND actual_end IS NULL)
      OR
      (lifecycle_state='upcoming' AND COALESCE(actual_start,scheduled_start)>=?)
      OR
      (lifecycle_state='ended' AND actual_end IS NOT NULL AND (
        (actual_end>=? AND actual_end<?)
        OR (?=1 AND actual_end>=? AND actual_end<?)
      ))
    )
    ORDER BY lifecycle_observed_at DESC,video_id DESC LIMIT ? OFFSET ?`)
    .bind(coverage?.roster_version??'',start,start,end,beforeNoon?1:0,previous,start,limit+1,offset).all();
  const truncated=(rows.results??[]).length>limit;
  const last=coverage?.last_success_at??null,age=last?Date.parse(nowStamp)-Date.parse(last):NaN;
  const freshness=!last?'unknown':age>=0&&age<=1800000?'fresh':'stale';
  return {schema_version:'public-consumer-v1',as_of:nowStamp,
    freshness:{status:freshness,last_success_at:last},
    completeness:{status:coverage?(coverage.gap||coverage.scanned_channels>0?'partial':'unverified'):'unverified',
                  gap:!coverage||Boolean(coverage.gap)||truncated,limited:truncated,has_more:truncated,offset,before_noon_grace:beforeNoon},
    checkpoint:coverage?.checkpoint??null,
    streams:await (async()=>{
      const selected=(rows.results??[]).slice(0,limit);
      const profiles=await readChannelProfiles(db,selected.map(r=>r.publisher_channel_id),{env});
      return selected.map(r=>consumerRow(r,nowStamp,profiles.get(r.publisher_channel_id))).filter(Boolean);
    })()};
}
