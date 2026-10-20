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
export async function readChannelProfile(db,channelId){
 if(!CHANNEL.test(channelId??''))return neutralChannelProfile(null);
 try{
  const row=await db.prepare('SELECT channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at FROM public_channel_profiles WHERE channel_id=? LIMIT 1').bind(channelId).first();
  return row?normalizeChannelProfile(row,channelId):neutralChannelProfile(channelId);
 }catch{
  return neutralChannelProfile(channelId);
 }
}
export async function readChannelProfiles(db,channelIds){
 const ids=[...new Set((Array.isArray(channelIds)?channelIds:[]).filter(x=>CHANNEL.test(x)))];
 const out=new Map(ids.map(id=>[id,neutralChannelProfile(id)]));
 if(!ids.length)return out;
 try{
  const placeholders=ids.map(()=>'?').join(',');
  const rows=await db.prepare(`SELECT channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at FROM public_channel_profiles WHERE channel_id IN (${placeholders})`).bind(...ids).all();
  for(const row of rows.results??[])out.set(row.channel_id,normalizeChannelProfile(row,row.channel_id));
 }catch{}
 return out;
}
export function applyChannelProfile(row,profile){
 const p=profile??neutralChannelProfile(row?.channel_id??'');
 return {
  ...row,
  channel_id:p.channel_id??row?.channel_id??null,
  channel_name:p.channel_name??row?.channel_name??null,
  display_name:p.display_name,
  avatar_url:p.avatar_url,
  group:p.group,
  member_accent:p.member_accent,
  member_accent_dual:p.member_accent_dual,
  support_mode:p.support_mode,
  support_color_source:p.support_color_source,
  profile_revision:p.profile_revision,
  profile_updated_at:p.updated_at,
  channel:p
 };
}
