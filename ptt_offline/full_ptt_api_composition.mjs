// Single #48 integration composition for the existing accepted #47 API shell.
// No Worker entrypoint or second deployment. The caller passes the existing
// createExistingApiRouter factory and supplies an independently trusted
// timestamp verifier for owner-only PTT writes.
import {createPttMountedApiRouter} from './api_shell_ptt_extension.mjs';
import {mountOwnerPublisherOnExistingApiRouter} from './api_owner_shell_extension.mjs';

export function composeFullPttOnExistingApi(createExistingApiRouter,{verifyAuthority}={}) {
  if(typeof createExistingApiRouter!=='function')
    throw new TypeError('accepted existing API factory required');
  const reads=createPttMountedApiRouter(createExistingApiRouter);
  return mountOwnerPublisherOnExistingApiRouter(reads,{verifyAuthority});
}
