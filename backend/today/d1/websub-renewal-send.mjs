/** WebSub subscription sender, disabled by default and bounded.
 * Run only from a separately approved scheduled handler.
 */
import {planSubscriptions} from './websub-renewal.mjs';
export async function renewSubscriptions({roster,leases,callback,secret,enabled=false,post,now=new Date(),limit=25}={}){
 const plan=planSubscriptions(roster,leases,{now,limit});
 if(!enabled)return {...plan,status:'DISABLED',sent:0};
 if(typeof post!=='function'||typeof callback!=='string'||!callback.startsWith('https://')||
   typeof secret!=='string'||secret.length<32)throw Error('renewal credentials/transport missing');
 let sent=0;
 const responses=[];
 for(const entry of plan.due){
  const body=new URLSearchParams({'hub.callback':callback,'hub.mode':'subscribe','hub.topic':entry.topic,
   'hub.verify':'async','hub.secret':secret,'hub.lease_seconds':'432000'});
  try {
   const response=await post(entry.hub,body);
   if(![202,204].includes(response.status))throw Error('hub nonaccepted status '+response.status);
   sent++;responses.push({channel_id:entry.channel_id,accepted:true});
  }catch(error){responses.push({channel_id:entry.channel_id,accepted:false,error:String(error.message).slice(0,100)});break;}
 }
 return {status:sent===plan.due.length?'SUBMITTED_PENDING_CHALLENGE':'STOP_REVIEW',sent,
  planned:plan.due.length,has_more:plan.has_more,responses};
}
