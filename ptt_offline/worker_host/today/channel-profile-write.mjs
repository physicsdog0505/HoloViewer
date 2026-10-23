import {normalizeChannelProfile} from './channel-profile.mjs';

const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const GROUPS=new Set(['hololive','holostars','mekpark','other']);
const MODES=new Set(['neutral','solid','dual_color']);
const HEX=/^#[0-9A-Fa-f]{6}$/;

function validTimestamp(value){
 return typeof value==='string'&&Number.isFinite(Date.parse(value));
}
function encodeDual(value){
 if(value==null)return null;
 if(!Array.isArray(value)||value.length!==2||!value.every(x=>HEX.test(String(x))))throw Error('invalid profile dual accent');
 return JSON.stringify(value.map(x=>String(x).toUpperCase()));
}
export function validateChannelProfileWrite(row){
 if(!row||!CHANNEL.test(row.channel_id??''))throw Error('invalid channel_id');
 if(!GROUPS.has(row.group))throw Error('invalid profile group');
 if(!MODES.has(row.support_mode??'neutral'))throw Error('invalid support mode');
 if(typeof row.profile_revision!=='string'||!row.profile_revision)throw Error('profile_revision required');
 if(!validTimestamp(row.updated_at))throw Error('updated_at required');
 if(row.member_accent!=null&&!HEX.test(String(row.member_accent)))throw Error('invalid member accent');
 if(row.support_mode==='dual_color')encodeDual(row.member_accent_dual);
 if(row.support_mode==='solid'&&!HEX.test(String(row.member_accent??'')))throw Error('solid accent required');
 const normalized=normalizeChannelProfile({
  channel_id:row.channel_id,
  channel_name:row.channel_name??null,
  display_name:row.display_name??null,
  avatar_url:row.avatar_url??null,
  channel_group:row.group,
  member_accent:row.member_accent??null,
  member_accent_dual:row.member_accent_dual??null,
  support_mode:row.support_mode??'neutral',
  support_color_source:row.support_color_source??null,
  profile_revision:row.profile_revision,
  updated_at:row.updated_at
 },row.channel_id);
 if(!normalized)throw Error('invalid profile');
 return normalized;
}
function profileContentKey(p){
 return JSON.stringify([
  p.channel_id,p.channel_name,p.display_name,p.avatar_url,p.group,p.member_accent,
  p.member_accent_dual,p.support_mode,p.support_color_source,p.profile_revision,p.updated_at
 ]);
}
export async function upsertChannelProfiles(db,rows){
 if(!db?.prepare||!Array.isArray(rows))throw Error('profile writer input required');
 const seen=new Set(),statements=[];
 for(const raw of rows){
  const p=validateChannelProfileWrite(raw);
  if(seen.has(p.channel_id))throw Error('duplicate channel profile');
  seen.add(p.channel_id);
  const existing=await db.prepare('SELECT channel_id,channel_name,display_name,avatar_url,channel_group AS "group",member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at FROM public_channel_profiles WHERE channel_id=? LIMIT 1').bind(p.channel_id).first();
  if(existing){
   const current=validateChannelProfileWrite({...existing,member_accent_dual:existing.member_accent_dual?JSON.parse(existing.member_accent_dual):null});
   if(current.updated_at===p.updated_at){
    if(profileContentKey(current)===profileContentKey(p))continue;
    throw Error('same-timestamp profile conflict');
   }
   if(Date.parse(p.updated_at)<Date.parse(current.updated_at))continue;
  }
  statements.push(db.prepare(`INSERT INTO public_channel_profiles
   (channel_id,channel_name,display_name,avatar_url,channel_group,member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at)
   VALUES(?,?,?,?,?,?,?,?,?,?,?)
   ON CONFLICT(channel_id) DO UPDATE SET
    channel_name=excluded.channel_name,display_name=excluded.display_name,avatar_url=excluded.avatar_url,
    channel_group=excluded.channel_group,member_accent=excluded.member_accent,member_accent_dual=excluded.member_accent_dual,
    support_mode=excluded.support_mode,support_color_source=excluded.support_color_source,
    profile_revision=excluded.profile_revision,updated_at=excluded.updated_at
   WHERE excluded.updated_at>public_channel_profiles.updated_at`)
   .bind(p.channel_id,p.channel_name,p.display_name,p.avatar_url,p.group,p.member_accent,encodeDual(p.member_accent_dual),
    p.support_mode,p.support_color_source,p.profile_revision,p.updated_at));
 }
 if(statements.length)await db.batch(statements);
 return {profiles_written:statements.length};
}
