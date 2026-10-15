// Exact #47 accepted API shell snapshot + #48 PTT read/private write.
// Deploy target is ONLY existing holoviewer-public-api, reviewed by #45.
// No second Worker / D1 / Collector process is created here.
import {createExistingApiRouter} from './today/api-shell.mjs';
import {composeFullPttOnExistingApi} from '../full_ptt_api_composition.mjs';
import {verifyPublisherTimeProof} from './time_authority.mjs';
import {mountTodayPublisherOnCombinedApi} from './today/today-private-post.mjs';

const combined = composeFullPttOnExistingApi(createExistingApiRouter,{
  verifyAuthority: async (row,env) => verifyPublisherTimeProof(row,env)
});

export default mountTodayPublisherOnCombinedApi(combined);
