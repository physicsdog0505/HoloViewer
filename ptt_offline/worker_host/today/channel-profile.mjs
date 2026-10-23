import {validateSupportColorExport,supportColorFor} from './support-colors.mjs';
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const HEX=/^#[0-9A-Fa-f]{6}$/;
const GROUPS=new Set(['hololive','holostars','mekpark','other']);
const MODES=new Set(['neutral','solid','dual_color']);
const AVATAR_HOSTS=new Set(['yt3.ggpht.com','yt3.googleusercontent.com','yt3.google.com']);

export function neutralChannelProfile(channelId){
 return {
  channel_id:CHANNEL.test(channelId??'')?channelId:null,
  channel_name:null,
  display_name:null,
  avatar_url:null,
  group:null,
  member_accent:null,
  member_accent_dual:null,
  support_mode:'neutral',
  support_color_source:null,
  profile_revision:null,
  updated_at:null
 };
}
function safeAvatar(value){
 if(typeof value!=='string'||!value)return null;
 try{
  const u=new URL(value);
  if(u.protocol!=='https:'||u.username||u.password||u.port||!AVATAR_HOSTS.has(u.hostname))return null;
  return u.href;
 }catch{return null}
}
function safeTime(value){
 if(typeof value!=='string'||!Number.isFinite(Date.parse(value)))return null;
 return new Date(value).toISOString().replace(/\.\d{3}Z$/,'Z');
}
function parseDual(value){
 if(value==null||value==='')return null;
 let raw=value;
 if(typeof raw==='string'){try{raw=JSON.parse(raw)}catch{return null}}
 if(!Array.isArray(raw)||raw.length!==2||!raw.every(x=>HEX.test(String(x))))return null;
 return raw.map(x=>String(x).toUpperCase());
}
export function normalizeChannelProfile(row,channelId=''){
 const id=CHANNEL.test(row?.channel_id??'')?row.channel_id:(CHANNEL.test(channelId)?channelId:null);
 if(!id)return null;
 const mode=MODES.has(row?.support_mode)?row.support_mode:'neutral';
 const accent=HEX.test(String(row?.member_accent??''))?String(row.member_accent).toUpperCase():null;
 const dual=parseDual(row?.member_accent_dual);
 return {
  channel_id:id,
  channel_name:typeof row?.channel_name==='string'&&row.channel_name?row.channel_name:null,
  display_name:typeof row?.display_name==='string'&&row.display_name?row.display_name:null,
  avatar_url:safeAvatar(row?.avatar_url),
  group:GROUPS.has(row?.channel_group??row?.group)?(row.channel_group??row.group):null,
  member_accent:mode==='neutral'?null:accent,
  member_accent_dual:mode==='dual_color'?dual:null,
  support_mode:mode==='dual_color'&&dual?'dual_color':mode==='solid'&&accent?'solid':'neutral',
  support_color_source:typeof row?.support_color_source==='string'&&row.support_color_source?row.support_color_source:null,
  profile_revision:typeof row?.profile_revision==='string'&&row.profile_revision?row.profile_revision:null,
  updated_at:safeTime(row?.updated_at)
 };
}
function supportColorJson(env){
 if(env?.TODAY_SUPPORT_COLORS_JSON)return String(env.TODAY_SUPPORT_COLORS_JSON);
 const parts=[];
 for(let i=0;i<16;i++){
  const value=env?.['TODAY_SUPPORT_COLORS_JSON_'+i];
  if(value==null){if(i===0)return null;break}
  parts.push(String(value));
 }
 return parts.length?parts.join(''):null;
}
function runtimeColorMap(env){
 try{
  const raw=supportColorJson(env);
  return raw?validateSupportColorExport(JSON.parse(raw)):null;
 }catch{return null}
}
function applyRuntimeColor(profile,channelId,env){
 const runtime=supportColorFor(channelId,runtimeColorMap(env));
 if(profile.support_mode!=='neutral')return profile;
 return {...profile,
  member_accent:runtime.member_accent,
  member_accent_dual:runtime.member_accent_dual,
  support_mode:runtime.support_mode,
  support_color_source:runtime.support_color_source
 };
}

async function batchRows(db,sql,ids){
 if(!ids.length)return [];
 try{
  const placeholders=ids.map(()=>'?').join(',');
  const rows=await db.prepare(sql.replace('__IDS__',placeholders)).bind(...ids).all();
  return rows?.results??[];
 }catch{return []}
}
function firstPer(rows,key){
 const out=new Map();
 for(const row of rows){
  const id=row?.[key]??(key==='channel_id'?row?.publisher_channel_id:null);
  if(CHANNEL.test(id??'')&&!out.has(id))out.set(id,row);
 }
 return out;
}
function emptyLegacyMap(ids){
 return new Map(ids.map(id=>[id,neutralChannelProfile(id)]));
}
async function readLegacyCandidates(db,ids){
 const out=emptyLegacyMap(ids);

 const oldProfiles=firstPer(await batchRows(db,
  `SELECT channel_id,channel_title,avatar_url,fetched_at FROM public_today_channel_profiles
   WHERE channel_id IN (__IDS__) ORDER BY channel_id,fetched_at DESC`,ids),'channel_id');
 for(const id of ids){
  const row=oldProfiles.get(id);if(!row)continue;
  const p=out.get(id);
  p.channel_name=typeof row.channel_title==='string'&&row.channel_title?row.channel_title:null;
  p.avatar_url=safeAvatar(row.avatar_url);
 }

 const catalogAvatar=firstPer(await batchRows(db,
  `SELECT channel_id,avatar_url,actual_start,scheduled_start,video_id FROM public_catalog
   WHERE channel_id IN (__IDS__) AND avatar_url IS NOT NULL
   ORDER BY channel_id,COALESCE(actual_start,scheduled_start) DESC,video_id DESC`,ids),'channel_id');
 for(const id of ids){
  const row=catalogAvatar.get(id);if(!row)continue;
  const p=out.get(id);
  if(!p.avatar_url)p.avatar_url=safeAvatar(row.avatar_url);
 }
 const catalogName=firstPer(await batchRows(db,
  `SELECT channel_id,channel_name,actual_start,scheduled_start,video_id FROM public_catalog
   WHERE channel_id IN (__IDS__) AND channel_name IS NOT NULL
   ORDER BY channel_id,COALESCE(actual_start,scheduled_start) DESC,video_id DESC`,ids),'channel_id');
 for(const id of ids){
  const row=catalogName.get(id);if(!row)continue;
  const p=out.get(id);
  if(!p.channel_name&&typeof row.channel_name==='string'&&row.channel_name)p.channel_name=row.channel_name;
 }

 const approved=firstPer(await batchRows(db,
  `SELECT channel_id,channel_group,activated_at,roster_version FROM public_today_approved_channels
   WHERE channel_id IN (__IDS__)
   ORDER BY channel_id,activated_at DESC,roster_version DESC`,ids),'channel_id');
 for(const id of ids){
  const row=approved.get(id);if(!row)continue;
  if(GROUPS.has(row.channel_group))out.get(id).group=row.channel_group;
 }

 const today=firstPer(await batchRows(db,
  `SELECT publisher_channel_id AS channel_id,channel_group,channel_name,lifecycle_observed_at,video_id
   FROM public_today_canonical WHERE publisher_channel_id IN (__IDS__)
   ORDER BY publisher_channel_id,lifecycle_observed_at DESC,video_id DESC`,ids),'channel_id');
 for(const id of ids){
  const row=today.get(id);if(!row)continue;
  const p=out.get(id);
  if(p.group==null&&GROUPS.has(row.channel_group))p.group=row.channel_group;
  if(!p.channel_name&&typeof row.channel_name==='string'&&row.channel_name)p.channel_name=row.channel_name;
 }

 const history=firstPer(await batchRows(db,
  `SELECT channel_id,channel_name,avatar_url,actual_start,scheduled_start,video_id FROM public_history
   WHERE channel_id IN (__IDS__)
   ORDER BY channel_id,COALESCE(actual_start,scheduled_start) DESC,video_id DESC`,ids),'channel_id');
 for(const id of ids){
  const row=history.get(id);if(!row)continue;
  const p=out.get(id);
  if(!p.channel_name&&typeof row.channel_name==='string'&&row.channel_name)p.channel_name=row.channel_name;
  if(!p.avatar_url)p.avatar_url=safeAvatar(row.avatar_url);
 }

 for(const p of out.values()){
  p.support_color_source=p.avatar_url||p.group||p.channel_name?'legacy-migration-projection':null;
 }
 return out;
}
function mergeCanonicalOverLegacy(canonical,legacy){
 if(!canonical)return legacy;
 return {
  ...legacy,
  ...canonical,
  channel_id:canonical.channel_id??legacy.channel_id,
  channel_name:canonical.channel_name??legacy.channel_name,
  display_name:canonical.display_name??legacy.display_name,
  avatar_url:canonical.avatar_url??legacy.avatar_url,
  group:canonical.group??legacy.group,
  profile_revision:canonical.profile_revision??legacy.profile_revision,
  updated_at:canonical.updated_at??legacy.updated_at
 };
}
export async function readChannelProfiles(db,channelIds,{env=null}={}){
 const ids=[...new Set((Array.isArray(channelIds)?channelIds:[]).filter(x=>CHANNEL.test(x)))];
 const out=new Map();
 if(!ids.length)return out;

 const legacy=await readLegacyCandidates(db,ids);
 const canonicalRows=await batchRows(db,
  `SELECT channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,
          support_mode,support_color_source,profile_revision,updated_at
   FROM public_channel_profiles WHERE channel_id IN (__IDS__)`,ids);
 const canonical=new Map();
 for(const row of canonicalRows){
  const normalized=normalizeChannelProfile(row,row.channel_id);
  if(normalized)canonical.set(row.channel_id,normalized);
 }
 for(const id of ids){
  const merged=mergeCanonicalOverLegacy(canonical.get(id)??null,legacy.get(id)??neutralChannelProfile(id));
  out.set(id,applyRuntimeColor(merged,id,env));
 }
 return out;
}
export async function readChannelProfile(db,channelId,{env=null}={}){
 if(!CHANNEL.test(channelId??''))return neutralChannelProfile(null);
 const profiles=await readChannelProfiles(db,[channelId],{env});
 return profiles.get(channelId)??neutralChannelProfile(channelId);
}

export function applyChannelProfile(row,profile,{includeNested=true}={}){
 const merged=profile??neutralChannelProfile(row?.channel_id??'');
 const {trusted_channel_avatar:_trusted,channel_group:_group,...publicRow}=row??{};
 return {
  ...publicRow,
  channel_id:merged.channel_id,
  channel_name:merged.channel_name??row?.channel_name??null,
  display_name:merged.display_name,
  avatar_url:merged.avatar_url,
  group:merged.group,
  member_accent:merged.member_accent,
  member_accent_dual:merged.member_accent_dual,
  support_mode:merged.support_mode,
  support_color_source:merged.support_color_source,
  profile_revision:merged.profile_revision,
  profile_updated_at:merged.updated_at,
  ...(includeNested?{channel:merged}:{})
 };
}
