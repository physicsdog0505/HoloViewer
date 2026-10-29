(function(root,factory){
 'use strict';
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.HoloViewerLocalSubtitles=Object.freeze(api);
})(typeof window!=='undefined'?window:globalThis,function(){
 'use strict';

 function fail(message){throw new Error(message)}
 function cleanText(value){return String(value??'').replace(/\r\n?/g,'\n')}
 function parseClock(raw,{comma=false,vtt=false}={}){
  const value=String(raw||'').trim();
  const pattern=comma
   ? /^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/
   : vtt
     ? /^(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})$/
     : /^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/;
  const match=value.match(pattern);
  if(!match)fail('字幕時間格式錯誤：'+value);
  let hours,minutes,seconds,millis;
  if(vtt){
   hours=Number(match[1]||0);minutes=Number(match[2]);seconds=Number(match[3]);millis=Number(match[4]);
  }else{
   hours=Number(match[1]);minutes=Number(match[2]);seconds=Number(match[3]);millis=Number(match[4]);
  }
  if(minutes>59||seconds>59)fail('字幕時間超出範圍：'+value);
  return hours*3600+minutes*60+seconds+millis/1000;
 }
 function validateCueOrder(cues){
  if(!cues.length)fail('字幕檔沒有可用字幕');
  let previousStart=-1;
  for(let i=0;i<cues.length;i++){
   const cue=cues[i];
   if(!Number.isFinite(cue.start)||!Number.isFinite(cue.end)||cue.start<0||cue.end<=cue.start)
    fail('字幕第 '+(i+1)+' 段時間範圍無效');
   if(cue.start<previousStart)fail('字幕時間順序錯誤：第 '+(i+1)+' 段早於前一段');
   if(!String(cue.translation||'').trim())fail('字幕第 '+(i+1)+' 段沒有可顯示文字');
   previousStart=cue.start;
  }
  return cues;
 }
 function parseSrt(body){
  const text=cleanText(body).replace(/^\uFEFF/,'').trim();
  if(!text)fail('字幕檔是空的');
  const blocks=text.split(/\n{2,}/);
  const cues=[];
  for(const block of blocks){
   const lines=block.split('\n');
   const timingIndex=lines.findIndex(line=>line.includes('-->'));
   if(timingIndex<0)fail('SRT 缺少時間軸');
   const timing=lines[timingIndex].trim().match(/^(\S+)\s+-->\s+(\S+)$/);
   if(!timing)fail('SRT 時間軸格式錯誤：'+lines[timingIndex].trim());
   const start=parseClock(timing[1],{comma:true});
   const end=parseClock(timing[2],{comma:true});
   const translation=lines.slice(timingIndex+1).join('\n').trim();
   cues.push({id:String(cues.length),index:cues.length,start,end,original:'',translation});
  }
  return validateCueOrder(cues);
 }
 function parseVtt(body){
  const text=cleanText(body).replace(/^\uFEFF/,'');
  const lines=text.split('\n');
  if(String(lines.shift()||'').trim()!=='WEBVTT')fail('VTT 缺少 WEBVTT 標頭');
  while(lines.length&&lines[0].trim()!=='')lines.shift();
  while(lines.length&&lines[0].trim()==='')lines.shift();
  const blocks=lines.join('\n').trim().split(/\n{2,}/).filter(Boolean);
  const cues=[];
  for(const block of blocks){
   const blockLines=block.split('\n');
   const first=String(blockLines[0]||'').trim();
   if(first.startsWith('NOTE')||first==='STYLE'||first==='REGION')continue;
   const timingIndex=blockLines.findIndex(line=>line.includes('-->'));
   if(timingIndex<0)fail('VTT 缺少時間軸');
   const timing=blockLines[timingIndex].trim().match(/^(\S+)\s+-->\s+(\S+)(?:\s+.*)?$/);
   if(!timing)fail('VTT 時間軸格式錯誤：'+blockLines[timingIndex].trim());
   const start=parseClock(timing[1],{vtt:true});
   const end=parseClock(timing[2],{vtt:true});
   const translation=blockLines.slice(timingIndex+1).join('\n').trim();
   cues.push({id:String(cues.length),index:cues.length,start,end,original:'',translation});
  }
  return validateCueOrder(cues);
 }
 function parseBenchmarkJson(body,{expectedVideoId=''}={}){
  let payload;
  try{payload=JSON.parse(cleanText(body))}catch{fail('benchmark JSON 無效')}
  if(!payload||typeof payload!=='object'||Array.isArray(payload))fail('benchmark JSON 必須是物件');
  const videoId=String(payload.video_id||'');
  if(videoId&&!/^[A-Za-z0-9_-]{11}$/.test(videoId))fail('benchmark JSON video_id 無效');
  if(videoId&&expectedVideoId&&videoId!==expectedVideoId)fail('字幕 video_id 不符：預期 '+expectedVideoId+'，實際 '+videoId);
  if(!Array.isArray(payload.segments)||!payload.segments.length)fail('benchmark JSON segments 為空');
  const ids=new Set(),cues=[];
  for(let i=0;i<payload.segments.length;i++){
   const row=payload.segments[i];
   if(!row||typeof row!=='object'||Array.isArray(row))fail('benchmark JSON 第 '+(i+1)+' 段格式無效');
   if(!('id' in row))fail('benchmark JSON 第 '+(i+1)+' 段缺少 id');
   if(typeof row.id!=='string'&&typeof row.id!=='number')fail('benchmark JSON 第 '+(i+1)+' 段 id 無效');
   const id=String(row.id).trim();
   if(!id||ids.has(id))fail('benchmark JSON segment id 重複或無效：'+id);
   ids.add(id);
   if(!Number.isInteger(row.start_ms)||!Number.isInteger(row.end_ms)||row.start_ms<0||row.end_ms<=row.start_ms)
    fail('benchmark JSON 第 '+(i+1)+' 段 timestamp 無效');
   if(typeof row.ja!=='string'||typeof row.zh_tw!=='string')fail('benchmark JSON 第 '+(i+1)+' 段缺少 ja / zh_tw');
   cues.push({
    id,index:i,start:row.start_ms/1000,end:row.end_ms/1000,
    original:row.ja,translation:row.zh_tw,
    speaker:String(row.speaker??''),
    speakerId:String(row.speaker_id??''),
    speakerKey:String(row.speaker_key??''),
    speakerAccent:/^#[0-9a-fA-F]{6}$/.test(String(row.speaker_accent||''))?String(row.speaker_accent):''
   });
  }
  validateCueOrder(cues);
  return {videoId,cues};
 }
 function extension(name){
  const match=String(name||'').toLowerCase().match(/\.([a-z0-9]+)$/);
  return match?match[1]:'';
 }
 function parseLocalSubtitleFile(name,body,{expectedVideoId=''}={}){
  const ext=extension(name);
  if(ext==='srt')return {format:'srt',videoId:'',cues:parseSrt(body)};
  if(ext==='vtt')return {format:'vtt',videoId:'',cues:parseVtt(body)};
  if(ext==='json'){
   const parsed=parseBenchmarkJson(body,{expectedVideoId});
   return {format:'json',videoId:parsed.videoId,cues:parsed.cues};
  }
  fail('不支援的字幕格式：.'+(ext||'?'));
 }
 function cueAt(cues,current){
  if(!Number.isFinite(current)||!Array.isArray(cues)||!cues.length)return null;
  let low=0,high=cues.length;
  while(low<high){
   const mid=(low+high)>>1;
   if(cues[mid].start<=current)low=mid+1;else high=mid;
  }
  const row=cues[Math.max(0,low-1)];
  return row&&current>=row.start&&current<row.end?row:null;
 }
 return {parseLocalSubtitleFile,parseBenchmarkJson,parseSrt,parseVtt,cueAt};
});
