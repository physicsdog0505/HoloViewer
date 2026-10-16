// #48 injection into the exact #47 createExistingApiRouter({pttHandler}) seam.
// #47 owns the shell and its CORS/OPTIONS/health/Today/legacy behavior.
// Do not create another Worker entrypoint or D1 binding.
import {handlePttPublicRead} from './d1_worker_routes.js';

export const REVIEWED_API_SHELL_BASE = '149a80361654b06377dbae580e1d8da2e5010cf0';

export function createPttMountedApiRouter(createExistingApiRouter, options={}) {
  if (typeof createExistingApiRouter !== 'function')
    throw new TypeError('requires exact #47 createExistingApiRouter factory');
  if (Object.prototype.hasOwnProperty.call(options,'pttHandler'))
    throw new TypeError('PTT handler is owned by #48');
  return createExistingApiRouter({...options,pttHandler:handlePttPublicRead});
}
