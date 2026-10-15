// Private writer dispatch for the EXISTING holoviewer-public-api Worker.
// This module must be called ONLY after the host verifies the request with
// an owner-controlled secret. It is not a public route and is disabled by default.
import {applyAuthorizedPttBatch} from './d1_owner_writer.mjs';
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,
 headers:{'content-type':'application/json','cache-control':'no-store'}});
export async function handleOwnerPttPublish(request,env,{authorize,verifyAuthority}={}) {
  if(request.method!=='POST') return json({error:'method_not_allowed'},405);
  if(env?.PTT_PUBLISH_ENABLED!=='true') return json({error:'publisher_disabled'},503);
  if(!env?.DB || typeof env.DB.batch!=='function') return json({error:'database_unavailable'},503);
  if(typeof authorize!=='function' || typeof verifyAuthority!=='function')
    return json({error:'authority_not_configured'},503);
  try {
    if(await authorize(request,env)!==true) return json({error:'unauthorized'},401);
  } catch {return json({error:'unauthorized'},401);}
  const size=Number(request.headers.get('content-length')||0);
  if(size>65536) return json({error:'payload_too_large'},413);
  let batch;
  try {
    const text=await request.text();
    if(text.length>65536) return json({error:'payload_too_large'},413);
    batch=JSON.parse(text);
  } catch {return json({error:'invalid_json'},400);}
  try {
    const receipt=await applyAuthorizedPttBatch({DB:env.DB,batch,verifyAuthority});
    return json(receipt);
  } catch {
    // No automatic retries. The caller must reconcile remote commit state.
    return json({error:'write_not_confirmed',reconcile_required:true},409);
  }
}
