import {readChannelProfile,readChannelProfiles} from './channel-profile.mjs';

const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;

function json(body,status=200,age=300){
 return new Response(JSON.stringify(body),{status,headers:{
  'content-type':'application/json; charset=utf-8',
  'cache-control':'public, max-age='+age,
  'x-content-type-options':'nosniff'
 }});
}

export async function handleChannelProfileRead(request,env){
 if(!request||request.method!=='GET')return json({error:'method_not_allowed'},405,0);
 if(!env?.DB?.prepare)return json({error:'database_not_bound'},503,0);
 let url;try{url=new URL(request.url)}catch{return json({error:'bad_request'},400,0)}
 const prefix='/v1/channels/',suffix='/profile';
 if(!url.pathname.startsWith(prefix)||!url.pathname.endsWith(suffix))return json({error:'not_found'},404,0);
 const channelId=decodeURIComponent(url.pathname.slice(prefix.length,-suffix.length));
 if(!CHANNEL.test(channelId))return json({error:'invalid_channel_id'},400,0);
 const profile=await readChannelProfile(env.DB,channelId,{env});
 return json({schema_version:'holoviewer-channel-profile-v1',profile},200,300);
}

export async function handleChannelProfilesBatchRead(request,env){
 if(!request||request.method!=='GET')return json({error:'method_not_allowed'},405,0);
 if(!env?.DB?.prepare)return json({error:'database_not_bound'},503,0);
 let url;try{url=new URL(request.url)}catch{return json({error:'bad_request'},400,0)}
 if(url.pathname!=='/v1/channels/profiles')return json({error:'not_found'},404,0);
 const raw=url.searchParams.getAll('id')
  .flatMap(value=>String(value||'').split(','))
  .map(value=>value.trim())
  .filter(Boolean);
 const ids=[...new Set(raw)];
 if(!ids.length)return json({error:'channel_ids_required'},400,0);
 if(ids.length>100)return json({error:'too_many_channel_ids',max:100},400,0);
 if(ids.some(id=>!CHANNEL.test(id)))return json({error:'invalid_channel_id'},400,0);
 const profiles=await readChannelProfiles(env.DB,ids,{env});
 return json({
  schema_version:'holoviewer-channel-profiles-v1',
  profiles:ids.map(id=>profiles.get(id)).filter(Boolean)
 },200,300);
}
