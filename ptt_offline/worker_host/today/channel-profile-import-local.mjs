import {upsertChannelProfiles,validateChannelProfileWrite} from './channel-profile-write.mjs';

const CID=/^UC[A-Za-z0-9_-]{22}$/;
const SCHEMA='holoviewer-channel-profile-import-v1';
const ROSTER='today85-20261016-d0e326c0496b';
const EXPECTED_COUNT=85;
const BATCH_SIZE=25;
const AVATAR_HOSTS=new Set(['yt3.ggpht.com','yt3.googleusercontent.com','yt3.google.com']);

function json(body,status=200){
 return new Response(JSON.stringify(body),{
  status,
  headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}
 });
}
function bytesToHex(bytes){
 return [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
}
async function sha256(text){
 return bytesToHex(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)));
}
function sanitizedError(error){
 const message=String(error?.message??error??'error');
 if(/secret|token|authorization|cookie|credential/i.test(message))return 'validation_failed';
 return message.slice(0,160);
}
function strictAvatar(value){
 if(value==null)return null;
 if(typeof value!=='string'||!value)throw Error('artifact avatar invalid');
 let url;try{url=new URL(value)}catch{throw Error('artifact avatar invalid')}
 if(url.protocol!=='https:'||url.username||url.password||url.port||!AVATAR_HOSTS.has(url.hostname))
  throw Error('artifact avatar invalid');
 return value;
}
function canonicalKey(p){
 return JSON.stringify([
  p.channel_id,p.channel_name,p.display_name,p.avatar_url,p.group,p.member_accent,
  p.member_accent_dual,p.support_mode,p.support_color_source,p.profile_revision,p.updated_at
 ]);
}
function parseArtifact(raw){
 let body;try{body=JSON.parse(raw)}catch{throw Error('artifact JSON invalid')}
 if(body?.schema_version!==SCHEMA)throw Error('artifact schema mismatch');
 if(body?.roster_version!==ROSTER)throw Error('artifact roster mismatch');
 if(body?.profile_count!==EXPECTED_COUNT||!Array.isArray(body?.profiles)||body.profiles.length!==EXPECTED_COUNT)
  throw Error('artifact profile count mismatch');
 if(typeof body?.authority!=='string'||!body.authority.startsWith('production-readonly:'))
  throw Error('artifact authority invalid');
 const seen=new Set(),rows=[];
 for(const input of body.profiles){
  if(!CID.test(input?.channel_id??'')||seen.has(input.channel_id))throw Error('artifact channel identity invalid');
  seen.add(input.channel_id);
  strictAvatar(input.avatar_url);
  rows.push(validateChannelProfileWrite(input));
 }
 return {body,rows};
}
async function existingProfiles(db,rows){
 const ids=rows.map(x=>x.channel_id);
 const placeholders=ids.map(()=>'?').join(',');
 const out=new Map();
 try{
  const result=await db.prepare(`SELECT channel_id,channel_name,display_name,avatar_url,channel_group AS "group",
    member_accent,member_accent_dual,support_mode,support_color_source,profile_revision,updated_at
    FROM public_channel_profiles WHERE channel_id IN (${placeholders})`).bind(...ids).all();
  for(const raw of result.results??[]){
   let dual=null;
   if(raw.member_accent_dual){try{dual=JSON.parse(raw.member_accent_dual)}catch{throw Error('stored dual accent invalid')}}
   const p=validateChannelProfileWrite({...raw,member_accent_dual:dual});
   out.set(p.channel_id,p);
  }
 }catch(error){
  if(/no such table|does not exist/i.test(String(error?.message??error)))throw Error('canonical profile table missing');
  throw error;
 }
 return out;
}
async function validateAgainstExisting(db,rows){
 const existing=await existingProfiles(db,rows);
 let inserts=0,updates=0,noops=0,older=0;
 for(const p of rows){
  const current=existing.get(p.channel_id);
  if(!current){inserts++;continue}
  const incomingTime=Date.parse(p.updated_at), currentTime=Date.parse(current.updated_at);
  if(incomingTime===currentTime){
   if(canonicalKey(p)!==canonicalKey(current))throw Error('same-timestamp profile conflict');
   noops++;continue;
  }
  if(incomingTime<currentTime){older++;continue}
  updates++;
 }
 return {plan:{inserts,updates,noops,older},existing};
}
async function runImport(env,raw,{apply=false,approvedSha=null}={}){
 if(!env?.DB?.prepare||!env?.DB?.batch)throw Error('DB binding required');
 const digest=await sha256(raw);
 if(!/^[0-9a-f]{64}$/.test(approvedSha??''))throw Error('approved artifact sha required');
 if(digest!==approvedSha)throw Error('artifact sha mismatch');
 const {body,rows}=parseArtifact(raw);
 const {plan,existing}=await validateAgainstExisting(env.DB,rows);
 if(!apply)return {
  status:'VALIDATED',production_mutation:false,artifact_sha256:digest,
  roster_version:body.roster_version,profile_count:rows.length,batch_size:BATCH_SIZE,plan
 };
 let written=0;
 for(let i=0;i<rows.length;i+=BATCH_SIZE){
  const result=await upsertChannelProfiles(env.DB,rows.slice(i,i+BATCH_SIZE),{existingById:existing});
  written+=result.profiles_written;
 }
 return {
  status:'APPLIED',production_mutation:true,artifact_sha256:digest,
  roster_version:body.roster_version,profile_count:rows.length,batch_size:BATCH_SIZE,
  profiles_written:written,plan
 };
}

export {runImport,parseArtifact};

export default {
 async fetch(request,env){
  const url=new URL(request.url);
  if(request.method!=='POST'||url.pathname!=='/run')return json({error:'not_found'},404);
  if(request.headers.get('content-type')!=='application/json')return json({error:'content_type_required'},415);
  const mode=url.searchParams.get('mode');
  if(mode!=='validate'&&mode!=='apply')return json({error:'invalid_mode'},400);
  const approvedSha=request.headers.get('x-hv-artifact-sha256');
  const raw=await request.text();
  try{
   const result=await runImport(env,raw,{apply:mode==='apply',approvedSha});
   return json(result,200);
  }catch(error){
   return json({status:'ABORTED',production_mutation:mode==='apply'?'unknown_or_partial':'false',
    error:sanitizedError(error)},409);
  }
 }
};
