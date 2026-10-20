'use strict';
(function(root){
 const MANIFEST_SCHEMA='holoviewer-watchalong-manifest-v1';
 const EVENT_SCHEMA='holoviewer-watchalong-event-v1';
 const VIDEO_ID=/^[A-Za-z0-9_-]{11}$/;
 const SHA256=/^[0-9a-f]{64}$/;
 function invariant(ok,msg){if(!ok)throw new Error(msg)}
 function finite(v){return Number.isFinite(Number(v))}
 function manifestEntry(manifest,eventId){
  invariant(manifest?.schema_version===MANIFEST_SCHEMA,'manifest schema mismatch');
  invariant(Array.isArray(manifest?.events),'manifest events missing');
  const entry=manifest.events.find(x=>String(x?.event_id||'')===String(eventId||''));
  invariant(entry,'event missing from manifest');
  invariant(VIDEO_ID.test(String(entry.event_id||'')),'event_id invalid');
  invariant(VIDEO_ID.test(String(entry.master_video_id||'')),'master_video_id invalid');
  invariant(String(entry.event_id)===String(entry.master_video_id),'master/event mismatch');
  invariant(typeof entry.path==='string'&&entry.path.startsWith('/data/watchalong/events/'),'event path invalid');
  invariant(SHA256.test(String(entry.sha256||'')),'sha256 invalid');
  invariant(Number.isInteger(entry.cue_count)&&entry.cue_count>=0,'cue_count invalid');
  invariant(Number.isInteger(entry.source_count)&&entry.source_count>0,'source_count invalid');
  invariant(SHA256.test(String(entry.transcript_hash||'')),'transcript hash invalid');
  invariant(SHA256.test(String(entry.translation_artifact_id||'')),'translation artifact invalid');
  return entry;
 }
 function verifyDigest(actual,expected){
  invariant(SHA256.test(String(actual||'')),'actual sha256 invalid');
  invariant(String(actual)===String(expected),'event sha256 mismatch');
 }
 function validateEvent(entry,event){
  invariant(event?.schema_version===EVENT_SCHEMA,'event schema mismatch');
  invariant(String(event.event_id||'')===String(entry.event_id),'event_id mismatch');
  invariant(String(event.master_video_id||'')===String(entry.master_video_id),'master_video_id mismatch');
  invariant(event.subtitle_timeline==='host','subtitle timeline must be host');
  invariant(Array.isArray(event.source_video_ids)&&event.source_video_ids.length===entry.source_count,'source count mismatch');
  invariant(new Set(event.source_video_ids).size===event.source_video_ids.length,'duplicate source video');
  event.source_video_ids.forEach(id=>invariant(VIDEO_ID.test(String(id||'')),'source_video_id invalid'));
  invariant(Array.isArray(event.segments)&&event.segments.length===entry.source_count,'segment count mismatch');
  let previous=-1;
  event.segments.forEach((segment,index)=>{
   invariant(segment&&typeof segment.segment_id==='string'&&segment.segment_id,'segment_id missing');
   invariant(String(segment.source_video_id||'')===String(event.source_video_ids[index]||''),'segment/source order mismatch');
   invariant(finite(segment.host_start_ms)&&Number(segment.host_start_ms)>=0,'host_start_ms invalid');
   invariant(finite(segment.source_start_ms)&&Number(segment.source_start_ms)>=0,'source_start_ms invalid');
   invariant(Number(segment.host_start_ms)>previous,'segments not sorted');
   previous=Number(segment.host_start_ms);
  });
  const transcript=event.artifacts?.transcript,translation=event.artifacts?.translation;
  invariant(transcript&&translation,'artifacts missing');
  invariant(String(transcript.content_hash||'')===String(entry.transcript_hash),'transcript hash mismatch');
  invariant(String(translation.transcript_hash||'')===String(entry.transcript_hash),'translation transcript mismatch');
  invariant(String(translation.artifact_id||'')===String(entry.translation_artifact_id),'translation artifact mismatch');
  invariant(Number(transcript.cue_count)===Number(entry.cue_count),'transcript cue count mismatch');
  invariant(Number(translation.translated_cues)===Number(entry.cue_count),'translated cue count mismatch');
  invariant(Array.isArray(event.subtitles)&&event.subtitles.length===entry.cue_count,'subtitle cue count mismatch');
  const seen=new Set();let previousStart=-1;
  const complete=String(entry.translation_status||'')==='COMPLETE'||String(event.completeness?.translation||'')==='COMPLETE';
  event.subtitles.forEach(cue=>{
   const id=String(cue?.cue_id||'');
   invariant(id&&!seen.has(id),'duplicate cue_id');seen.add(id);
   invariant(finite(cue.start_ms)&&finite(cue.end_ms),'cue timing invalid');
   invariant(Number(cue.start_ms)>=previousStart,'cues not sorted');
   invariant(Number(cue.end_ms)>Number(cue.start_ms),'cue end invalid');
   previousStart=Number(cue.start_ms);
   if(complete)invariant(String(cue.translation||'').trim(),'COMPLETE cue translation empty');
  });
  return event;
 }
 function segmentIndexAt(segments,hostSeconds){
  if(!Array.isArray(segments)||!segments.length||!finite(hostSeconds))return -1;
  const hostMs=Number(hostSeconds)*1000;let index=0;
  for(let i=1;i<segments.length;i++){if(hostMs>=Number(segments[i].host_start_ms))index=i;else break}
  return index;
 }
 root.HoloViewerWatchalongStatic={manifestEntry,verifyDigest,validateEvent,segmentIndexAt};
})(globalThis);
