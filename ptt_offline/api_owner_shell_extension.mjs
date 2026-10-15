// #48 thin private owner-write wrapper for #47's accepted GET-only API shell.
// Existing read router is untouched: only the exact private POST path is
// intercepted. Always fails closed unless explicit enable+HMAC+time authority.
import {handleOwnerPttPublish} from './d1_owner_dispatch.mjs';
export function mountOwnerPublisherOnExistingApiRouter(
  existingApiRouter,{verifyAuthority}={}
) {
  if(!existingApiRouter || typeof existingApiRouter.fetch!=='function')
    throw new TypeError('accepted GET-only API router is required');
  return {async fetch(request,env,ctx){
    const url=new URL(request.url);
    if(url.pathname==='/private/ptt/publish') {
      if(request.headers.has('origin'))
        return new Response(JSON.stringify({error:'origin_not_allowed'}),{
          status:403,headers:{'content-type':'application/json','cache-control':'no-store'}});
      // No ad-hoc authorize callback: owner HMAC secret is enforced by dispatch.
      return handleOwnerPttPublish(request,env,{verifyAuthority});
    }
    return existingApiRouter.fetch(request,env,ctx);
  }};
}
