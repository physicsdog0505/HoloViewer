import {saveChannelProfiles} from './websub-hardening.mjs';
/** Explicit Cloudflare-friendly channel profile refresh, no implicit scheduling. */
export async function refreshChannelProfiles({db,roster,fetchChannels,now=new Date(),offset=0,limit=50}={}){
 if(!db?.prepare||!roster?.version||!Array.isArray(roster.channels)||
  typeof fetchChannels!=='function'||!Number.isInteger(offset)||offset<0||
  !Number.isInteger(limit)||limit<1||limit>50)throw Error('invalid profile refresh');
 const chunk=roster.channels.slice(offset,offset+limit);
 if(!chunk.length)return {fetched:0,stored:0,has_more:false};
 const ids=chunk.map(x=>x.id),unique=new Set(ids);
 if(ids.length!==unique.size||ids.some(x=>!/^UC[A-Za-z0-9_-]{22}$/.test(x)))throw Error('duplicate/invalid roster ID');
 const items=await fetchChannels(ids);
 if(!Array.isArray(items)||items.length!==ids.length||new Set(items.map(x=>x.id)).size!==ids.length)
  throw Error('partial channels.list: no silent acceptance');
 if(items.some(x=>!unique.has(x.id)))throw Error('unexpected channel');
 const receipt=await saveChannelProfiles(db,roster,items,{now});
 return {...receipt,fetched:items.length,has_more:offset+chunk.length<roster.channels.length,
   next_offset:offset+chunk.length};
}
export async function fetchYouTubeChannels(ids,apiKey,{fetchImpl=fetch}={}){
 if(!apiKey||ids.length>50||!ids.length)throw Error('credential/batch missing');
 const u=new URL('https://www.googleapis.com/youtube/v3/channels');
 u.searchParams.set('part','snippet');u.searchParams.set('id',ids.join(','));u.searchParams.set('key',apiKey);
 const r=await fetchImpl(u.toString(),{headers:{accept:'application/json'},signal:AbortSignal.timeout(12000)});
 if(!r.ok)throw Error('channels.list failed');
 const body=await r.json();
 if(!Array.isArray(body.items))throw Error('invalid channels.list');
 return body.items;
}
