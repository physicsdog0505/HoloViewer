/** #47 existing API Worker deployment CANDIDATE ONLY; not yet matched to live Dashboard source.
 * Owner must approve a source diff, CORS origin and rollback revision before deploy.
 * PTT is intentionally NOT mounted by this entrypoint.
 */
import {createExistingApiRouter} from './api-shell.mjs';
export default createExistingApiRouter();
