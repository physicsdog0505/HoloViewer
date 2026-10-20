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

export async function readChannelProfile(db,channelId,{env=null}={}){
 if(!CHANNEL.test(channelId??''))return neutralChannelProfile(null);
 try{
  const row=await db.prepare('SELECT channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at FROM public_channel_profiles WHERE channel_id=? LIMIT 1').bind(channelId).first();
  const profile=row?normalizeChannelProfile(row,channelId):neutralChannelProfile(channelId);
  return applyRuntimeColor(profile,channelId,env);
 }catch{
  return applyRuntimeColor(neutralChannelProfile(channelId),channelId,env);
 }
}
export async function readChannelProfiles(db,channelIds,{env=null}={}){
 const ids=[...new Set((Array.isArray(channelIds)?channelIds:[]).filter(x=>CHANNEL.test(x)))];
 const out=new Map(ids.map(id=>[id,applyRuntimeColor(neutralChannelProfile(id),id,env)]));
 if(!ids.length)return out;
 try{
  const placeholders=ids.map(()=>'?').join(',');
  const rows=await db.prepare(`SELECT channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at FROM public_channel_profiles WHERE channel_id IN (${placeholders})`).bind(...ids).all();
  for(const row of rows.results??[])out.set(row.channel_id,applyRuntimeColor(normalizeChannelProfile(row,row.channel_id),row.channel_id,env));
 }catch{}
 return out;
}
export function applyChannelProfile(row,profile,{includeNested=true}={}){
 const base=profile??neutralChannelProfile(row?.channel_id??'');
 const rowHasGroup=Object.prototype.hasOwnProperty.call(row??{},'channel_group')||Object.prototype.hasOwnProperty.call(row??{},'group');
 const fallbackGroup=GROUPS.has(row?.channel_group??row?.group)?(row.channel_group??row.group):(rowHasGroup?'other':null);
 const merged={
  ...base,
  channel_id:base.channel_id??(CHANNEL.test(row?.channel_id??'')?row.channel_id:null),
  channel_name:base.channel_name??(typeof row?.channel_name==='string'&&row.channel_name?row.channel_name:null),
  avatar_url:base.avatar_url??safeAvatar(row?.trusted_channel_avatar)??safeAvatar(row?.avatar_url),
  group:base.group??fallbackGroup
 };
 return {
  ...row,
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
