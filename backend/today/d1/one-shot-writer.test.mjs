import test from 'node:test';
import assert from 'node:assert/strict';
import {validateOneShotReceipt,buildOneShotPlan,executeOneShot} from './one-shot-writer.mjs';
const C='UC'+'A'.repeat(22),V='abcdefghijk';
const r={video_id:V,channel_id:C,roster_version:'approved-v1',group:'hololive',title:'Sample',channel_name:'Channel',lifecycle_state:'upcoming',scheduled_start:'2026-10-16T00:00:00Z',observed_at:'2026-10-15T12:00:00Z',source_label:'YouTube'};
const receipt={mode:'PROVIDER_READ_ONLY',d1_writes:0,roster_version:'approved-v1',records:[r],channel_count:1,api_calls:2,gap:false};
test('owner gate and roster source proof fail closed',async()=>{
 assert.equal(validateOneShotReceipt(receipt),receipt);
 assert.throws(()=>validateOneShotReceipt({...receipt,gap:true}),/gap/);
 assert.throws(()=>buildOneShotPlan(receipt,[{id:'UC'+'B'.repeat(22),group:'hololive'}]),/membership/);
 const plan=buildOneShotPlan(receipt,[{id:C,group:'hololive'}]);
 await assert.rejects(()=>executeOneShot(plan,{}),/approval/);
 assert.equal(plan.expected_channels,1);
});
