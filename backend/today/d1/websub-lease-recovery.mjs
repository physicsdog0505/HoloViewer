/** Lease recovery: bounded reviewable decisions, never blind resubmission. */
export function planLeaseRecovery(roster,leases,{now=new Date(),max=25}={}){
 if(!roster?.version||!Array.isArray(roster.channels)||!Array.isArray(leases)||max<1||max>50)throw Error('invalid lease recovery');
 const byId=new Map(leases.map(x=>[x.channel_id,x]));const due=[],review=[];
 for(const c of roster.channels){
  const x=byId.get(c.id);
  if(!x){due.push(c.id);continue}
  if(x.roster_version!==roster.version){review.push({channel_id:c.id,reason:'roster_changed'});continue}
  if(x.state==='pending'){
   const age=now.getTime()-Date.parse(x.requested_at??'');
   if(!Number.isFinite(age)||age<0||age>3600000)review.push({channel_id:c.id,reason:'uncertain_pending_request'});
   continue;
  }
  if(x.state==='rejected'){review.push({channel_id:c.id,reason:'hub_rejected'});continue}
  if(x.state!=='active'||!x.expires_at||Date.parse(x.expires_at)-now.getTime()<=86400000)due.push(c.id);
 }
 return {mode:'DRY_RUN_REVIEW',due:due.slice(0,max),remaining:due.length>max,review};
}
