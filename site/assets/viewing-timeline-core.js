'use strict';
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.HoloViewerViewingTimeline=Object.freeze(api);
})(typeof globalThis!=='undefined'?globalThis:null,function(){
 const SCHEMA='holoviewer-viewing-timeline-v1';
 const VIDEO_ID=/^[A-Za-z0-9_-]{11}$/;
 const ID=/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

 function invariant(ok,message){if(!ok)throw new Error(message)}
 function integer(value){return Number.isInteger(value)}
 function validateSession(session){
  invariant(session&&session.schema_version===SCHEMA,'timeline schema mismatch');
  invariant(ID.test(String(session.session_id||'')),'session_id invalid');
  invariant(integer(session.absolute_start_ms)&&session.absolute_start_ms>=0,'absolute_start_ms invalid');
  invariant(integer(session.master_end_ms)&&session.master_end_ms>0,'master_end_ms invalid');
  if(session.revision!==undefined&&session.revision!==null&&session.revision!==''){
   invariant(ID.test(String(session.revision)),'revision invalid');
  }
  invariant(Array.isArray(session.povs)&&session.povs.length>0,'povs missing');
  const povIds=new Set();
  session.povs.forEach(pov=>{
   const povId=String(pov?.pov_id||'');
   invariant(ID.test(povId),'pov_id invalid');
   invariant(!povIds.has(povId),'duplicate pov_id');
   povIds.add(povId);
   invariant(Array.isArray(pov.segments),'segments missing');
   const segmentIds=new Set();
   let previousEnd=0;
   pov.segments.forEach((segment,index)=>{
    const segmentId=String(segment?.segment_id||'');
    invariant(ID.test(segmentId),'segment_id invalid');
    invariant(!segmentIds.has(segmentId),'duplicate segment_id');
    segmentIds.add(segmentId);
    invariant(VIDEO_ID.test(String(segment?.video_id||'')),'video_id invalid');
    invariant(integer(segment?.master_start_ms)&&segment.master_start_ms>=0,'master_start_ms invalid');
    invariant(integer(segment?.master_end_ms)&&segment.master_end_ms>segment.master_start_ms,'master_end_ms invalid');
    invariant(segment.master_end_ms<=session.master_end_ms,'segment outside session');
    invariant(integer(segment?.source_start_ms)&&segment.source_start_ms>=0,'source_start_ms invalid');
    if(index>0)invariant(segment.master_start_ms>=previousEnd,'segment overlap');
    previousEnd=segment.master_end_ms;
   });
  });
  return true;
 }

 function sessionAbsoluteTime(session,masterTimeMs){
  validateSession(session);
  invariant(integer(masterTimeMs),'master time invalid');
  if(masterTimeMs<0||masterTimeMs>=session.master_end_ms)return null;
  return session.absolute_start_ms+masterTimeMs;
 }

 function findPov(session,povId){
  return session.povs.find(pov=>String(pov.pov_id)===String(povId))||null;
 }

 function resolvePov(session,povId,masterTimeMs){
  validateSession(session);
  invariant(integer(masterTimeMs),'master time invalid');
  const absoluteTimeMs=masterTimeMs>=0&&masterTimeMs<session.master_end_ms
   ?session.absolute_start_ms+masterTimeMs:null;
  const pov=findPov(session,povId);
  invariant(pov,'unknown pov_id');
  if(absoluteTimeMs===null){
   return {status:'NO_COVERAGE',pov_id:String(povId),master_time_ms:masterTimeMs,absolute_time_ms:null};
  }
  const segment=pov.segments.find(item=>
   masterTimeMs>=item.master_start_ms&&masterTimeMs<item.master_end_ms
  );
  if(!segment){
   return {status:'NO_COVERAGE',pov_id:String(povId),master_time_ms:masterTimeMs,absolute_time_ms:absoluteTimeMs};
  }
  return {
   status:'READY',
   pov_id:String(povId),
   segment_id:String(segment.segment_id),
   video_id:String(segment.video_id),
   master_time_ms:masterTimeMs,
   source_time_ms:segment.source_start_ms+(masterTimeMs-segment.master_start_ms),
   absolute_time_ms:absoluteTimeMs,
  };
 }

 function breakpointsForPov(session,povId){
  validateSession(session);
  const pov=findPov(session,povId);
  invariant(pov,'unknown pov_id');
  return pov.segments.slice(1).map(segment=>segment.master_start_ms);
 }

 return Object.freeze({SCHEMA,validateSession,sessionAbsoluteTime,resolvePov,breakpointsForPov});
});
