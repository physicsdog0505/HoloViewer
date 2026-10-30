'use strict';
const assert=require('node:assert/strict');
const vod=require('./site/assets/vod-subtitle-core.js');

const hash='a'.repeat(64),artifact='b'.repeat(64),transcript='c'.repeat(64);
const fixture={
 schema_version:'holodocchi-vod-subtitle-v1',video_id:'QDlEA7aPSmI',
 source_transcript_id:transcript,source_content_hash:hash,
 translation_artifact_id:artifact,
 translation_identity:{transcript_hash:hash,translation_provider:'gemini-web',model:'Gemini Web fixture',target_language:'zh-TW',rules_version:'zh-TW-hololive-v1'},
 segment_count:2,
 cues:[
  {id:0,start_ms:0,end_ms:1000,zh_tw:'第一段'},
  {id:1,start_ms:1200,end_ms:2400,zh_tw:'第二段'}
 ]
};
const parsed=vod.parseAsset(fixture,{expectedVideoId:'QDlEA7aPSmI'});
assert.equal(parsed.videoId,'QDlEA7aPSmI');
assert.equal(parsed.sourceTranscriptId,transcript);
assert.equal(parsed.translationArtifactId,artifact);
assert.equal(parsed.cues[1].start,1.2);
assert.equal(parsed.cues[1].translation,'第二段');
assert.equal(vod.assetPath('QDlEA7aPSmI'),'/data/subtitles/videos/QDlEA7aPSmI.json');

async function main(){
 let requested='';
 const loaded=await vod.load('QDlEA7aPSmI',{baseUrl:'https://subtitles.example/',fetchImpl:async(url,options)=>{
  requested=url;assert.equal(options.credentials,'omit');return {ok:true,status:200,json:async()=>fixture};
 }});
 assert.equal(requested,'https://subtitles.example/data/subtitles/videos/QDlEA7aPSmI.json');
 assert.equal(loaded.segmentCount,2);
 assert.equal(await vod.load('QDlEA7aPSmI',{baseUrl:'https://subtitles.example',fetchImpl:async()=>({ok:false,status:404})}),null);
 assert.equal(await vod.load('QDlEA7aPSmI',{baseUrl:''}),null);
 assert.throws(()=>vod.parseAsset({...fixture,video_id:'AAAAAAAAAAA'},{expectedVideoId:'QDlEA7aPSmI'}),/video_id/);
 assert.throws(()=>vod.parseAsset({...fixture,segment_count:1}),/segment count/);
 assert.throws(()=>vod.parseAsset({...fixture,translation_identity:{...fixture.translation_identity,transcript_hash:'d'.repeat(64)}}),/identity/);
 assert.throws(()=>vod.parseAsset({...fixture,cues:[fixture.cues[1],fixture.cues[0]]}),/id\/order/);
 console.log('VOD_SUBTITLE_CORE=PASS');
}
main().catch(error=>{console.error(error);process.exitCode=1});
