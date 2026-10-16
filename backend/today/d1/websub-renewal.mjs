/** Bounded WebSub renewal planner. Does not send subscriptions or mutate state. */
const CHANNEL=/^UC[A-Za-z0-9_-]{22}$/;
const HUB='https://pubsubhubbub.appspot.com/subscribe';
export function planSubscriptions(roster,leaseState,{now=new Date(),renewBeforeSeconds=86400,limit=50}={}){
 if(!roster?.version||!Array.isArray(roster.channels)||!Array.isArray(leaseState)||limit<1||limit>50)throw Error('invalid subscription input');
 const previous=new Map(leaseState.map(x=>[x.channel_id,x]));
 const seen=new Set(),due=[];
 for(const c of roster.channels){
  if(!CHANNEL.test(c.id)||seen.has(c.id))throw Error('invalid/duplicate roster identity');
  seen.add(c.id);
  const state=previous.get(c.id),expiry=state?.expires_at?Date.parse(state.expires_at):NaN;
  // Hub verification is asynchronous. Do not resubmit an outstanding lease on every cron tick.
  // The existing 24-hour challenge validation window is the upper bound for a pending request.
  const requested=state?.requested_at?Date.parse(state.requested_at):NaN;
  const pending=state?.state==='pending'&&state.roster_version===roster.version&&
    Number.isFinite(requested)&&requested<=now.getTime()&&now.getTime()-requested<86400000;
  if(pending)continue;
  if(!Number.isFinite(expiry)||expiry-now.getTime()<=renewBeforeSeconds*1000){
   due.push({channel_id:c.id,roster_version:roster.version,
    mode:'subscribe',hub:HUB,topic:'https://www.youtube.com/xml/feeds/videos.xml?channel_id='+c.id});
  }
 }
 // No implicit unsubscribe: removed channels require explicit Owner reconciliation.
 return {mode:'DRY_RUN_ONLY',due:due.slice(0,limit),has_more:due.length>limit,missing_or_due:due.length,
  unapproved_existing:leaseState.filter(x=>!seen.has(x.channel_id)).map(x=>x.channel_id)};
}
