'use strict';

const assert=require('node:assert/strict');
const local=require('./site/assets/local-subtitle-core.js');

function throwsContains(fn,needle){
 let error=null;
 try{fn()}catch(err){error=err}
 assert.ok(error,'expected error');
 assert.match(String(error.message||error),new RegExp(needle));
}

const srt=local.parseLocalSubtitleFile('a.srt',[
 '1',
 '00:00:01,000 --> 00:00:02,500',
 '字幕 A',
 '',
 '2',
 '00:00:03,000 --> 00:00:04,000',
 '第二段'
].join('\n'));
assert.equal(srt.format,'srt');
assert.equal(srt.cues.length,2);
assert.equal(srt.cues[0].start,1);
assert.equal(srt.cues[0].end,2.5);
assert.equal(srt.cues[0].translation,'字幕 A');

const vtt=local.parseLocalSubtitleFile('b.vtt',[
 'WEBVTT',
 '',
 '00:01.000 --> 00:02.000',
 '字幕 B',
 '',
 '00:03.000 --> 00:04.250 align:center',
 '第二段 B'
].join('\n'));
assert.equal(vtt.format,'vtt');
assert.equal(vtt.cues.length,2);
assert.equal(vtt.cues[1].end,4.25);

const json=local.parseLocalSubtitleFile('bench.json',JSON.stringify({
 video_id:'QDlEA7aPSmI',
 segments:[
  {id:0,start_ms:1234,end_ms:5678,ja:'日本語原文',zh_tw:'繁體中文翻譯'},
  {id:1,start_ms:6000,end_ms:7000,ja:'次',zh_tw:'第二段'}
 ]
}),{expectedVideoId:'QDlEA7aPSmI'});
assert.equal(json.format,'json');
assert.equal(json.videoId,'QDlEA7aPSmI');
assert.equal(json.cues[0].start,1.234);
assert.equal(json.cues[0].translation,'繁體中文翻譯');
assert.equal(local.cueAt(json.cues,1.5).id,'0');
assert.equal(local.cueAt(json.cues,5.9),null);

throwsContains(()=>local.parseLocalSubtitleFile('bad.srt','1\n00:00:AA,000 --> 00:00:02,000\nx'),'時間');
throwsContains(()=>local.parseLocalSubtitleFile('bad.json','{oops'), 'JSON');
throwsContains(()=>local.parseLocalSubtitleFile('bad.json',JSON.stringify({
 video_id:'QDlEA7aPSmI',
 segments:[{id:0,start_ms:0,end_ms:1000,ja:'x',zh_tw:'y'}]
}),{expectedVideoId:'AAAAAAAAAAA'}),'video_id');
throwsContains(()=>local.parseLocalSubtitleFile('bad.json',JSON.stringify({
 video_id:'QDlEA7aPSmI',
 segments:[
  {id:0,start_ms:2000,end_ms:3000,ja:'x',zh_tw:'y'},
  {id:1,start_ms:1000,end_ms:1500,ja:'x',zh_tw:'y'}
 ]
}),{expectedVideoId:'QDlEA7aPSmI'}),'順序');
throwsContains(()=>local.parseLocalSubtitleFile('empty.vtt','WEBVTT\n\n'),'沒有可用字幕');
throwsContains(()=>local.parseLocalSubtitleFile('bad.txt','x'),'不支援');

console.log('LOCAL_SUBTITLE_CORE=PASS');
