(function(root,factory){
 'use strict';
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.HoloViewerVodSubtitles=Object.freeze(api);
})(typeof window!=='undefined'?window:globalThis,function(){
 'use strict';
 const SCHEMA_VERSION='holodocchi-vod-subtitle-v1';
 const VIDEO_ID=/^[A-Za-z0-9_-]{11}$/;
 const SHA256=/^[0-9a-f]{64}$/;
 function fail(message){throw new Error(message)}
 function assetPath(videoId){
  if(!VIDEO_ID.test(String(videoId||'')))fail('VOD subtitle video_id 無效');
  return '/data/subtitles/videos/'+videoId+'.json';
 }
 function parseAsset(payload,{expectedVideoId=''}={}){
  if(!payload||typeof payload!=='object'||Array.isArray(payload))fail('VOD subtitle asset 必須是物件');
  const expectedKeys=['cues','schema_version','segment_count','source_content_hash','source_transcript_id','translation_artifact_id','translation_identity','video_id'];
  if(Object.keys(payload).sort().join('|')!==expectedKeys.sort().join('|'))fail('VOD subtitle asset 欄位不符');
  if(payload.schema_version!==SCHEMA_VERSION)fail('VOD subtitle schema 不支援');
  if(!VIDEO_ID.test(String(payload.video_id||'')))fail('VOD subtitle video_id 無效');
  if(expectedVideoId&&payload.video_id!==expectedVideoId)fail('VOD subtitle video_id 不符');
  for(const field of ['source_transcript_id','source_content_hash','translation_artifact_id']){
   if(!SHA256.test(String(payload[field]||'')))fail('VOD subtitle '+field+' 無效');
  }
  const identity=payload.translation_identity;
  if(!identity||typeof identity!=='object'||Array.isArray(identity))fail('VOD subtitle translation identity 無效');
  const identityKeys=['model','rules_version','target_language','transcript_hash','translation_provider'];
  if(Object.keys(identity).sort().join('|')!==identityKeys.sort().join('|'))fail('VOD subtitle translation identity 欄位不符');
  if(identity.transcript_hash!==payload.source_content_hash)fail('VOD subtitle transcript identity 不符');
  if(identity.target_language!=='zh-TW')fail('VOD subtitle target language 不符');
  for(const field of ['model','rules_version','translation_provider']){
   if(typeof identity[field]!=='string'||!identity[field].trim())fail('VOD subtitle translation identity 缺少 '+field);
  }
  if(!Number.isInteger(payload.segment_count)||payload.segment_count<1||!Array.isArray(payload.cues)||payload.cues.length!==payload.segment_count)
   fail('VOD subtitle segment count 不符');
  let previousStart=-1;
  const cues=payload.cues.map((row,index)=>{
   if(!row||typeof row!=='object'||Array.isArray(row))fail('VOD subtitle cue 無效');
   const keys=['end_ms','id','start_ms','zh_tw'];
   if(Object.keys(row).sort().join('|')!==keys.sort().join('|')||row.id!==index)fail('VOD subtitle cue id/order 不符');
   if(!Number.isInteger(row.start_ms)||!Number.isInteger(row.end_ms)||row.start_ms<0||row.end_ms<=row.start_ms||row.start_ms<previousStart)
    fail('VOD subtitle cue timestamps 無效');
   if(typeof row.zh_tw!=='string'||!row.zh_tw.trim())fail('VOD subtitle cue 缺少 zh-TW');
   previousStart=row.start_ms;
   return {id:String(row.id),index,start:row.start_ms/1000,end:row.end_ms/1000,original:'',translation:row.zh_tw};
  });
  return {
   videoId:payload.video_id,
   sourceTranscriptId:payload.source_transcript_id,
   sourceContentHash:payload.source_content_hash,
   translationArtifactId:payload.translation_artifact_id,
   segmentCount:payload.segment_count,
   cues
  };
 }
 async function load(videoId,{baseUrl='',fetchImpl=globalThis.fetch}={}){
  const path=assetPath(videoId);
  const base=String(baseUrl||'').replace(/\/+$/,'');
  if(!base)return null;
  if(typeof fetchImpl!=='function')fail('VOD subtitle fetch 不可用');
  const response=await fetchImpl(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});
  if(response.status===404)return null;
  if(!response.ok)fail('VOD subtitle HTTP '+response.status);
  return parseAsset(await response.json(),{expectedVideoId:videoId});
 }
 return {SCHEMA_VERSION,assetPath,parseAsset,load};
});
