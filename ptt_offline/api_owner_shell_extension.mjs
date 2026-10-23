// #48 thin private owner-write wrapper for #47's accepted GET-only API shell.
// Existing read router is untouched: only the exact private POST path is
// intercepted. Always fails closed unless explicit enable+HMAC+time authority.
import {handleOwnerPttPublish} from './d1_owner_dispatch.mjs';
import {handleOwnerPttReconcile} from './d1_owner_reconcile.mjs';
export function mountOwnerPublisherOnExistingApiRouter(
  existingApiRouter,{verifyAuthority}={}
) {
  if(!existingApiRouter || typeof existingApiRouter.fetch!=='function')
    throw new TypeError('accepted GET-only API router is required');
  return {async fetch(request,env,ctx){
    const url=new URL(request.url);
    if(url.pathname==='/private/ptt/publish' || url.pathname==='/private/ptt/reconcile') {
      if(request.headers.has('origin'))
        return new Response(JSON.stringify({error:'origin_not_allowed'}),{
          status:403,headers:{'content-type':'application/json','cache-control':'no-store'}});
      if(url.pathname==='/private/ptt/reconcile')
        return handleOwnerPttReconcile(request,env);
      // No ad-hoc authorize callback: owner HMAC secret is enforced by dispatch.
      return handleOwnerPttPublish(request,env,{verifyAuthority});
    }
    return existingApiRouter.fetch(request,env,ctx);
  }};
}
