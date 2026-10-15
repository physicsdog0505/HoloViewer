import {refreshPendingVideos} from './websub-status.mjs';
import {reconcileAtomFeeds} from './feed-reconcile.mjs';
// Cloudflare scheduled-handler building block, disabled unless Owner explicitly enables.
// Inject D1 DB with approved additive event queue schema, verified roster and API key.
const ID=/^[A-Za-z0-9_-]{11}$/;
export async function runTodayScheduled(env,{fetchImpl=fetch,now=new Date()}={}){
 if(env?.TODAY_COLLECTOR_ENABLED!=='true')return {status:'disabled',requests:0};
 if(!env.DB||!env.YOUTUBE_API_KEY||!env.TODAY_APPROVED_ROSTER)throw Error('collector configuration missing');
 const roster=JSON.parse(env.TODAY_APPROVED_ROSTER);
 if(!Array.isArray(roster.channels)||roster.channels.length<1||roster.channels.length>500)throw Error('unapproved roster size');
 const fetchVideos=async ids=>{
  if(!ids.length||ids.length>50||ids.some(x=>!ID.test(x)))throw Error('invalid YouTube batch');
  const url=new URL('https://www.googleapis.com/youtube/v3/videos');
  url.searchParams.set('part','snippet,liveStreamingDetails');
  url.searchParams.set('id',ids.join(','));
  url.searchParams.set('key',env.YOUTUBE_API_KEY);
  const r=await fetchImpl(url.toString(),{headers:{accept:'application/json'},signal:AbortSignal.timeout(12000)});
  if(!r.ok)throw Error('YouTube videos.list failed HTTP '+r.status);
  const json=await r.json();
  if(!Array.isArray(json.items))throw Error('malformed videos.list');
  return json.items;
 };
 let reconciliation=null;
 if(env.TODAY_RECONCILE_ENABLED==='true'){
  reconciliation=await reconcileAtomFeeds({db:env.DB,roster,now,maxChannels:3,
   fetchFeed:async url=>{
    const response=await fetchImpl(url,{headers:{accept:'application/atom+xml'},signal:AbortSignal.timeout(12000)});
    if(!response.ok)throw Error('Atom feed unavailable '+response.status);
    const size=Number(response.headers?.get?.('content-length')??0);
    if(size>262144)throw Error('Atom feed too large');
    return response.text();
   }});
  if(reconciliation.failed)throw Error('feed reconciliation interrupted; manual review');
 }
 const status=await refreshPendingVideos({db:env.DB,roster,fetchVideos,now,maxEvents:25});
 return {...status,reconciliation};
}
