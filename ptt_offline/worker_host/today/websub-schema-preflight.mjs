import {loadApprovedTodayRoster} from './websub-runtime.mjs';

const REQUIRED={
 public_today_websub_events:[
  'event_hash','channel_id','video_id','roster_version','received_at','status','attempts',
  'processed_at','last_error','claim_token','claim_until'
 ],
 public_today_reconcile_cursor:['singleton','roster_version','next_index','updated_at'],
 public_today_lifecycle_cursor:['singleton','roster_version','last_video_id','checked_at_json','updated_at'],
 public_today_websub_leases:[
  'channel_id','roster_version','topic','requested_mode','state','requested_at','verified_at',
  'expires_at','lease_seconds','last_error'
 ]
};
/** Read-only schema/roster preflight. Never applies or repairs a migration. */
export async function auditWebSubSchema(db){
 try{
  const roster=await loadApprovedTodayRoster(db);
  const tables={};
  let ready=true;
  for(const [table,required] of Object.entries(REQUIRED)){
   const result=await db.prepare('PRAGMA table_info('+table+')').all();
   const columns=new Set((result.results??[]).map(row=>row.name));
   const missing=required.filter(column=>!columns.has(column));
   tables[table]={status:missing.length?'HOLD':'PASS',missing_columns:missing};
   if(missing.length)ready=false;
  }
  return {status:ready?'PASS':'HOLD',mode:'READ_ONLY',roster_version:roster.version,
    approved_channels:roster.channels.length,expected_channels:roster.expected_channels,tables};
 }catch{
  return {status:'HOLD',mode:'READ_ONLY',reason:'schema_or_approved_roster_unavailable'};
 }
}
export const requiredWebSubSchema=REQUIRED;
