'use strict';

(function(root){
 const MANIFEST_SCHEMA='holoviewer-watchalong-manifest-v1';
 const EVENT_SCHEMA='holoviewer-watchalong-event-v1';
 const VIDEO_ID=/^[A-Za-z0-9_-]{11}$/;
 const SHA256=/^[0-9a-f]{64}$/;

 function invariant(condition,message){
  if(!condition)throw new Error(message);
 }
 function finite(value){return Number.isFinite(Number(value))}
 function manifestEntry(manifest,eventId){
  invariant(manifest&&manifest.schema_version===MANIFEST_SCHEMA,'watchalong manifest schema mismatch');
  invariant(Array.isArray(manifest.events),'watchalong manifest events missing');
  const entry=manifest.events.find(item=>String(item?.event_id||'')===String(eventId||''));
  invariant(entry,'watchalong event missing from manifest');
  invariant(VIDEO_ID.test(String(entry.event_id||'')),'watchalong manifest event_id invalid');
  invariant(VIDEO_ID.test(String(entry.master_video_id||'')),'watchalong manifest master_video_id invalid');
  invariant(String(entry.master_video_id)===String(entry.event_id),'watchalong manifest master/event mismatch');
  invariant(typeof entry.path==='string'&&entry.path.startsWith('/data/watchalong/events/')&&entry.path.endsWith('.json'),'watchalong event path invalid');
  invariant(SHA256.test(String(entry.sha256||'')),'watchalong manifest sha256 invalid');
  invariant(Number.isInteger(entry.cue_count)&&entry.cue_count>=0,'watchalong manifest cue_count invalid');
  invariant(Number.isInteger(entry.source_count)&&entry.source_count>0,'watchalong manifest source_count invalid');
  invariant(SHA256.test(String(entry.transcript_hash||'')),'watchalong manifest transcript hash invalid');
  invariant(SHA256.test(String(entry.translation_artifact_id||'')),'watchalong manifest translation artifact invalid');
  return entry;
 }
 function verifyDigest(actual,expected){
  invariant(SHA256.test(String(actual||'')),'watchalong actual sha256 invalid');
  invariant(String(actual)===String(expected),'watchalong event sha256 mismatch');
  return true;
 }
 function validateEvent(entry,event){
  invariant(event&&event.schema_version===EVENT_SCHEMA,'watchalong event schema mismatch');
  invariant(String(event.event_id||'')===String(entry.event_id),'watchalong event_id mismatch');
  invariant(String(event.master_video_id||'')===String(entry.master_video_id),'watchalong master_video_id mismatch');
  invariant(VIDEO_ID.test(String(event.master_video_id||'')),'watchalong master_video_id invalid');
  invariant(event.subtitle_timeline==='host','watchalong subtitle timeline must be host');
  invariant(Array.isArray(event.source_video_ids),'watchalong source_video_ids missing');
  invariant(event.source_video_ids.length===entry.source_count,'watchalong source count mismatch');
  invariant(new Set(event.source_video_ids).size===event.source_video_ids.length,'watchalong duplicate source video');
  event.source_video_ids.forEach(id=>invariant(VIDEO_ID.test(String(id||'')),'watchalong source_video_id invalid'));

  invariant(Array.isArray(event.segments)&&event.segments.length===entry.source_count,'watchalong segment count mismatch');
  let previousHost=-1;
  const segmentIds=new Set();
  event.segments.forEach((segment,index)=>{
   invariant(segment&&typeof segment.segment_id==='string'&&segment.segment_id,'watchalong segment_id missing');
   invariant(!segmentIds.has(segment.segment_id),'watchalong duplicate segment_id');
   segmentIds.add(segment.segment_id);
   invariant(event.source_video_ids.includes(String(segment.source_video_id||'')),'watchalong segment source linkage mismatch');
   invariant(String(segment.source_video_id||'')===String(event.source_video_ids[index]||''),'watchalong segment/source order mismatch');
   invariant(finite(segment.host_start_ms)&&Number(segment.host_start_ms)>=0,'watchalong host_start_ms invalid');
   invariant(finite(segment.source_start_ms)&&Number(segment.source_start_ms)>=0,'watchalong source_start_ms invalid');
   invariant(Number(segment.host_start_ms)>previousHost,'watchalong segments not strictly sorted');
   previousHost=Number(segment.host_start_ms);
  });

  const transcript=event.artifacts?.transcript;
  const translation=event.artifacts?.translation;
  invariant(transcript&&translation,'watchalong artifacts missing');
  invariant(String(transcript.content_hash||'')===String(entry.transcript_hash),'watchalong transcript hash linkage mismatch');
  invariant(String(translation.transcript_hash||'')===String(entry.transcript_hash),'watchalong translation transcript linkage mismatch');
  invariant(String(translation.artifact_id||'')===String(entry.translation_artifact_id),'watchalong translation artifact linkage mismatch');
  invariant(Number(transcript.cue_count)===Number(entry.cue_count),'watchalong transcript cue count mismatch');
  invariant(Number(translation.translated_cues)===Number(entry.cue_count),'watchalong translation cue count mismatch');

  invariant(Array.isArray(event.subtitles)&&event.subtitles.length===entry.cue_count,'watchalong subtitle cue count mismatch');
  const cueIds=new Set();
  let previousStart=-1;
  if(entry.translation_status)invariant(String(event.completeness?.translation||'')===String(entry.translation_status),'watchalong translation status mismatch');
  const complete=String(entry.translation_status||'')==='COMPLETE'||String(event.completeness?.translation||'')==='COMPLETE';
  event.subtitles.forEach(cue=>{
   const cueId=String(cue?.cue_id||'');
   invariant(cueId&&!cueIds.has(cueId),'watchalong duplicate cue_id');
   cueIds.add(cueId);
   invariant(finite(cue.start_ms)&&finite(cue.end_ms),'watchalong cue timing invalid');
   invariant(Number(cue.start_ms)>=previousStart,'watchalong cues not sorted by start_ms');
   invariant(Number(cue.end_ms)>Number(cue.start_ms),'watchalong cue end must follow start');
   previousStart=Number(cue.start_ms);
   if(complete)invariant(String(cue.translation||'').trim().length>0,'watchalong COMPLETE cue translation empty');
  });
  return {
   event,
   segments:event.segments,
   subtitles:event.subtitles,
   initial_offset_seconds:segmentOffsetSeconds(event.segments[0])
  };
 }
 function segmentOffsetSeconds(segment){
  invariant(segment&&finite(segment.host_start_ms)&&finite(segment.source_start_ms),'watchalong segment timing missing');
  return (Number(segment.source_start_ms)-Number(segment.host_start_ms))/1000;
 }
 function segmentIndexAt(segments,hostSeconds){
  if(!Array.isArray(segments)||!segments.length||!finite(hostSeconds))return -1;
  const hostMs=Number(hostSeconds)*1000;
  let index=0;
  for(let i=1;i<segments.length;i++){
   if(hostMs>=Number(segments[i].host_start_ms))index=i;
   else break;
  }
  return index;
 }
 function sourceTargetSeconds(segment,hostSeconds){
  if(!finite(hostSeconds))return null;
  return Number(hostSeconds)+segmentOffsetSeconds(segment);
 }
 function subtitleAt(cues,hostSeconds){
  if(!Array.isArray(cues)||!cues.length||!finite(hostSeconds))return null;
  const ms=Number(hostSeconds)*1000;
  let low=0,high=cues.length;
  while(low<high){
   const mid=(low+high)>>1;
   if(Number(cues[mid].start_ms)<=ms)low=mid+1;
   else high=mid;
  }
  const cue=cues[Math.max(0,low-1)];
  return cue&&Number(cue.start_ms)<=ms&&ms<Number(cue.end_ms)?cue:null;
 }

 root.HoloViewerWatchalongCore={
  MANIFEST_SCHEMA,EVENT_SCHEMA,manifestEntry,verifyDigest,validateEvent,
  segmentOffsetSeconds,segmentIndexAt,sourceTargetSeconds,subtitleAt
 };
})(globalThis);
