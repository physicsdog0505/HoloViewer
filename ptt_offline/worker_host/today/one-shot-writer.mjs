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
 if(!plan||!Array.isArray(plan.records)||plan.records.length>50||plan.records.length<1)throw Error('invalid one-shot plan');
 // Intentionally never promise cross-record atomicity: evidence rows can commit
 // individually.  A gap=true coverage sentinel is installed BEFORE the first row,
 // so failure at record N cannot advertise complete/fresh scan success.
 const degraded={roster_version:plan.roster_version,expected_channels:plan.expected_channels,
  scanned_channels:0,gap:true,last_success_at:null,approved_channels:plan.approved_channels};
 await setCoverage(db,degraded);
 let attempted=0,selected=0,replayed=0;
 try{
  for(const record of plan.records){
   attempted++;
   const result=await writeEvidence(db,record);
   if(result.changed)selected++;
   if(result.reason==='replay')replayed++;
  }
  // One-shot uploads+search never self-certifies complete roster coverage.
  await setCoverage(db,{...degraded,scanned_channels:plan.expected_channels,
   last_success_at:plan.observed_at});
  const coverage=await db.prepare('SELECT roster_version,gap,scanned_channels,expected_channels FROM public_today_catalog_meta WHERE singleton=1').first();
  if(!coverage||coverage.roster_version!==plan.roster_version||Number(coverage.gap)!==1||
     Number(coverage.scanned_channels)!==plan.expected_channels)throw Error('coverage readback mismatch');
  for(const record of plan.records){
   const seen=await db.prepare('SELECT checksum FROM public_today_evidence WHERE video_id=? AND observed_at=? AND source_label=?')
    .bind(record.video_id,record.observed_at,record.source_label).first();
   if(!seen)throw Error('evidence readback incomplete');
  }
  return {mode:'ONE_SHOT_INJECTED_DB',status:'PARTIAL_COVERAGE',selected,replayed,
   records_verified:plan.records.length,roster_version:plan.roster_version,gap:true};
 }catch(err){
  // If postcoverage verification fails, explicitly reinstate degraded coverage;
  // if this too fails, operator must inspect remote records before any retry.
  try{await setCoverage(db,degraded)}
  catch{throw Error('PARTIAL WRITE; coverage reset unverified; STOP and inspect remote D1. '+err.message)}
  throw Error('PARTIAL WRITE; coverage marked degraded; STOP and inspect remote D1. attempted='+attempted+' '+err.message);
 }
}
