// Private writer dispatch for the EXISTING holoviewer-public-api Worker.
// This module must be called ONLY after the host verifies the request with
// an owner-controlled secret. It is not a public route and is disabled by default.
import {applyAuthorizedPttBatch} from './d1_owner_writer.mjs';
import {authorizePttHmac} from './ptt_owner_hmac.mjs';
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,
 headers:{'content-type':'application/json','cache-control':'no-store'}});
export async function handleOwnerPttPublish(request,env,{authorize,verifyAuthority}={}) {
  if(request.method!=='POST') return json({error:'method_not_allowed'},405);
  if(env?.PTT_PUBLISH_ENABLED!=='true') return json({error:'publisher_disabled'},503);
  if(!env?.DB || typeof env.DB.batch!=='function') return json({error:'database_unavailable'},503);
  if(typeof verifyAuthority!=='function')
    return json({error:'authority_not_configured'},503);
  const size=Number(request.headers.get('content-length')||0);
  if(size>65536) return json({error:'payload_too_large'},413);
  let batch,raw;
  try {
    raw=await request.text();
    if(raw.length>65536) return json({error:'payload_too_large'},413);
  } catch {return json({error:'invalid_body'},400);}
  try {
    const verified = typeof authorize === 'function'
      ? await authorize(request,env,raw) === true
      : await authorizePttHmac(request,env,raw);
    if(!verified) return json({error:'unauthorized'},401);
  } catch {return json({error:'unauthorized'},401);}
  try {batch=JSON.parse(raw);} catch {return json({error:'invalid_json'},400);}
  try {
    const receipt=await applyAuthorizedPttBatch({DB:env.DB,batch,verifyAuthority:row=>verifyAuthority(row,env)});
    return json(receipt);
  } catch {
    // No automatic retries. The caller must reconcile remote commit state.
    return json({error:'write_not_confirmed',reconcile_required:true},409);
  }
}
