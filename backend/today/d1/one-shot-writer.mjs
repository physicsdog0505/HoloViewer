/** One-shot validated evidence handoff. No network, Cloudflare write, or implicit retry.
 * A publisher must inject an authenticated DB binding through its separately reviewed transport.
 */
import {writeEvidence,setCoverage,validateEvidence} from './store.mjs';
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
export function validateOneShotReceipt(receipt,{maxRecords=50,maxChannels=3}={}){
 if(!receipt||receipt.mode!=='PROVIDER_READ_ONLY'||receipt.d1_writes!==0
   ||typeof receipt.roster_version!=='string'||!receipt.roster_version
   ||!Array.isArray(receipt.records)||receipt.records.length<1||receipt.records.length>maxRecords
   ||!Number.isInteger(receipt.api_calls)||receipt.api_calls<1
   ||!Number.isInteger(receipt.channel_count)||receipt.channel_count<1||receipt.channel_count>maxChannels)
   throw Error('invalid or unbounded provider read-only receipt');
 if(receipt.gap!==false)throw Error('provider coverage gap: one-shot write requires independent review');
 const ids=new Set();
 for(const record of receipt.records){
  validateEvidence(record);
  if(record.roster_version!==receipt.roster_version||ids.has(record.video_id))throw Error('receipt identity/version collision');
  ids.add(record.video_id);
 }
 return receipt;
}
export function buildOneShotPlan(receipt,approvedChannels){
 validateOneShotReceipt(receipt);
 if(!Array.isArray(approvedChannels)||approvedChannels.length!==receipt.channel_count
   ||new Set(approvedChannels.map(x=>x.id)).size!==approvedChannels.length)throw Error('approved roster required');
 const membership=new Map();
 for(const channel of approvedChannels){
  if(!CHANNEL.test(channel.id)||!['hololive','holostars','mekpark','other'].includes(channel.group))throw Error('invalid channel');
  membership.set(channel.id,channel.group);
 }
 for(const r of receipt.records)if(membership.get(r.channel_id)!==r.group)throw Error('receipt publisher lacks approved membership');
 return Object.freeze({roster_version:receipt.roster_version,approved_channels:approvedChannels,
  records:receipt.records,expected_channels:approvedChannels.length,
  observed_at:receipt.records.reduce((x,r)=>x>r.observed_at?x:r.observed_at,receipt.records[0].observed_at)});
}
export async function executeOneShot(plan,db,{explicitApproved=false}={}){
 if(!explicitApproved)throw Error('owner write approval required');
 if(!db||typeof db.prepare!=='function'||typeof db.batch!=='function')throw Error('reviewed injected D1 DB required');
 if(!plan||plan.records?.length>50||plan.records?.length<1)throw Error('invalid one-shot plan');
 // This is a local integration seam only; cannot be reached by Public HTTP GET.
 const changes=[];
 for(const r of plan.records)changes.push(await writeEvidence(db,r));
 await setCoverage(db,{roster_version:plan.roster_version,expected_channels:plan.expected_channels,
  scanned_channels:plan.expected_channels,gap:true,last_success_at:plan.observed_at,
  approved_channels:plan.approved_channels});
 return {mode:'ONE_SHOT_INJECTED_DB',written:changes.filter(c=>c.changed).length,
  replayed:changes.filter(c=>c.reason==='replay').length,roster_version:plan.roster_version};
}
