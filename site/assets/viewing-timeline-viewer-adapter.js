'use strict';
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.HoloViewerTimelineViewerAdapter=Object.freeze(api);
})(typeof globalThis!=='undefined'?globalThis:null,function(){
 function invariant(ok,message){if(!ok)throw new Error(message)}
 function create(session,{timeline,initialMasterTimeMs=0,primaryPovId=''}={}){
  invariant(timeline&&typeof timeline.validateSession==='function','timeline core missing');
  timeline.validateSession(session);
  let masterTimeMs=0;
  let primary=String(primaryPovId||session.povs[0]?.pov_id||'');
  invariant(session.povs.some(pov=>String(pov.pov_id)===primary),'primary pov invalid');

  function clampMaster(value){
   const n=Math.trunc(Number(value));
   if(!Number.isFinite(n))return masterTimeMs;
   return Math.max(0,Math.min(session.master_end_ms-1,n));
  }
  function setMasterTimeMs(value){masterTimeMs=clampMaster(value);return masterTimeMs}
  function setPrimaryPov(povId){
   const id=String(povId||'');
   invariant(session.povs.some(pov=>String(pov.pov_id)===id),'primary pov invalid');
   primary=id;
   return primary;
  }
  function resolution(povId){return timeline.resolvePov(session,String(povId),masterTimeMs)}
  function absoluteTimeMs(){return timeline.sessionAbsoluteTime(session,masterTimeMs)}
  function plan(currentSources={}){
   return session.povs.map(pov=>{
    const resolved=resolution(pov.pov_id);
    const current=String(currentSources[pov.pov_id]||'');
    if(resolved.status!=='READY')return {...resolved,replace:false,current_video_id:current};
    return {...resolved,replace:Boolean(current&&current!==resolved.video_id),current_video_id:current};
   });
  }
  function masterFromSource(povId,videoId,sourceTimeMs){
   const id=String(povId||''),video=String(videoId||''),source=Number(sourceTimeMs);
   if(!Number.isFinite(source)||source<0)return null;
   const pov=session.povs.find(item=>String(item.pov_id)===id);
   if(!pov)return null;
   const candidates=[];
   for(const segment of pov.segments){
    if(String(segment.video_id)!==video)continue;
    const duration=segment.master_end_ms-segment.master_start_ms;
    const localStart=segment.source_start_ms;
    const localEnd=localStart+duration;
    let candidate=null;
    if(source>=localStart&&source<localEnd){
     candidate=segment.master_start_ms+(source-localStart);
    }else if(source>=localEnd&&masterTimeMs>=segment.master_start_ms&&masterTimeMs<segment.master_end_ms){
     candidate=segment.master_end_ms;
    }else if(source<localStart&&masterTimeMs>=segment.master_start_ms&&masterTimeMs<segment.master_end_ms){
     candidate=segment.master_start_ms;
    }
    if(candidate!==null)candidates.push(Math.max(0,Math.min(session.master_end_ms-1,Math.trunc(candidate))));
   }
   if(!candidates.length)return null;
   candidates.sort((a,b)=>Math.abs(a-masterTimeMs)-Math.abs(b-masterTimeMs)||a-b);
   return candidates[0];
  }

  setMasterTimeMs(initialMasterTimeMs);
  return Object.freeze({
   session,
   get masterTimeMs(){return masterTimeMs},
   get primaryPovId(){return primary},
   setMasterTimeMs,
   setPrimaryPov,
   resolution,
   absoluteTimeMs,
   plan,
   masterFromSource,
  });
 }
 function createClock(adapter,{nowMs=0}={}){
  invariant(adapter&&typeof adapter.setMasterTimeMs==='function','timeline adapter missing');
  let lastWallMs=Number.isFinite(Number(nowMs))?Number(nowMs):0;
  function step({nowMs,running=false,mappedMasterMs=null}={}){
   const now=Number(nowMs);
   invariant(Number.isFinite(now),'clock now invalid');
   const elapsed=Math.max(0,now-lastWallMs);
   lastWallMs=now;
   const hasMapped=mappedMasterMs!==null&&mappedMasterMs!==undefined&&mappedMasterMs!==''&&Number.isFinite(Number(mappedMasterMs));
   if(hasMapped){
    adapter.setMasterTimeMs(Number(mappedMasterMs));
   }else if(running&&elapsed>0){
    adapter.setMasterTimeMs(adapter.masterTimeMs+Math.trunc(elapsed));
   }
   return adapter.masterTimeMs;
  }
  function reset(nowMs=lastWallMs){
   const now=Number(nowMs);
   invariant(Number.isFinite(now),'clock now invalid');
   lastWallMs=now;
   return adapter.masterTimeMs;
  }
  return Object.freeze({step,reset,get lastWallMs(){return lastWallMs}});
 }
 return Object.freeze({create,createClock});
});
