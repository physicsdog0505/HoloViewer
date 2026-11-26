(()=>{
'use strict';

const VIDEO_RE=/^[A-Za-z0-9_-]{11}$/;
const START_TOLERANCE_MS=20*60*1000;

function text(value){return value===undefined||value===null?'':String(value).trim()}
function timeMs(value){
 const ms=Date.parse(text(value));
 return Number.isFinite(ms)?ms:null;
}
function metadataRows(digest,metadata){
 const byId=new Map();
 const add=row=>{
  if(!row||typeof row!=='object')return;
  const id=text(row.video_id);
  if(VIDEO_RE.test(id))byId.set(id,row);
 };
 (Array.isArray(digest?.streams)?digest.streams:[]).forEach(add);
 if(metadata instanceof Map){
  for(const [key,value] of metadata.entries()){
   if(value&&typeof value==='object')add({...value,video_id:text(value.video_id)||text(key)});
  }
 }else if(Array.isArray(metadata)){
  metadata.forEach(add);
 }else if(metadata&&typeof metadata==='object'){
  for(const [key,value] of Object.entries(metadata)){
   if(value&&typeof value==='object')add({...value,video_id:text(value.video_id)||text(key)});
  }
 }
 return byId;
}
function candidateGroups(digest){
 const out=[];
 const push=(kind,index,row)=>{
  if(!row||typeof row!=='object'||!Array.isArray(row.video_ids))return;
  out.push({
   kind,
   index,
   videoIds:row.video_ids,
   label:text(row.title||row.short_title||row.summary||'多人連動')
  });
 };
 (Array.isArray(digest?.stories)?digest.stories:[]).forEach((row,index)=>push('story',index,row));
 (Array.isArray(digest?.overview?.highlights)?digest.overview.highlights:[]).forEach((row,index)=>push('highlight',index,row));
 return out;
}
function validUniqueVideoIds(raw){
 if(!Array.isArray(raw)||raw.length<2)return null;
 const ids=[];
 const seen=new Set();
 for(const value of raw){
  const id=text(value);
  if(!VIDEO_RE.test(id))return null;
  if(!seen.has(id)){seen.add(id);ids.push(id)}
 }
 return ids.length>=2?ids:null;
}
function normalizedStream(row,id){
 const lifecycle=text(row?.lifecycle_state||row?.state).toLowerCase();
 return {
  ...row,
  video_id:id,
  channel_id:text(row?.channel_id),
  channel_name:text(row?.channel_name||row?.channel_title),
  lifecycle_state:lifecycle||'unknown',
  actual_start:text(row?.actual_start),
  actual_end:text(row?.actual_end),
  scheduled_start:text(row?.scheduled_start),
  start_at:text(row?.start_at)
 };
}
function completeActualWindow(row){
 const start=timeMs(row?.actual_start),end=timeMs(row?.actual_end);
 return start!==null&&end!==null&&end>start?{start,end}:null;
}
function timingCompatible(rows){
 if(!Array.isArray(rows)||rows.length<2)return false;
 const windows=rows.map(completeActualWindow);
 const complete=windows.every(Boolean);
 if(complete){
  const latestStart=Math.max(...windows.map(x=>x.start));
  const earliestEnd=Math.min(...windows.map(x=>x.end));
  return earliestEnd>latestStart;
 }
 const known=windows.filter(Boolean);
 for(let i=0;i<known.length;i++){
  for(let j=i+1;j<known.length;j++){
   if(Math.min(known[i].end,known[j].end)<=Math.max(known[i].start,known[j].start))return false;
  }
 }
 const starts=rows.map(row=>timeMs(row?.actual_start)||timeMs(row?.start_at)||timeMs(row?.scheduled_start));
 if(starts.some(value=>value===null))return false;
 return Math.max(...starts)-Math.min(...starts)<=START_TOLERANCE_MS;
}
function stableHash(value){
 let hash=2166136261;
 for(let i=0;i<value.length;i++){
  hash^=value.charCodeAt(i);
  hash=Math.imul(hash,16777619)>>>0;
 }
 return hash.toString(16).padStart(8,'0');
}
function deriveDigestCollabEvents(digest,metadata){
 if(!digest||digest.schema_version!==1||digest.kind!=='holodocchi.daily_digest')return [];
 const day=text(digest.target_day);
 if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||text(digest.timezone)!=='Asia/Taipei')return [];
 const byId=metadataRows(digest,metadata);
 const events=[];
 const seenSets=new Set();
 for(const group of candidateGroups(digest)){
  const ids=validUniqueVideoIds(group.videoIds);
  if(!ids)continue;
  const key=ids.slice().sort().join(',');
  if(seenSets.has(key))continue;
  const rows=[];
  let missing=false;
  for(const id of ids){
   const source=byId.get(id);
   if(!source){missing=true;break}
   const row=normalizedStream(source,id);
   if(!row.channel_id){missing=true;break}
   rows.push(row);
  }
  if(missing)continue;
  if(new Set(rows.map(row=>row.channel_id)).size<2)continue;
  if(!timingCompatible(rows))continue;
  seenSets.add(key);
  const sortedIds=ids.slice().sort();
  events.push({
   event_id:'digest-'+day+'-'+stableHash(day+'|'+sortedIds.join('|')),
   day,
   label:group.label||'多人連動',
   confidence:'candidate',
   streams:rows,
   source:{kind:'daily_digest',target_day:day,group_kind:group.kind,group_index:group.index}
  });
 }
 return events;
}

const api=Object.freeze({deriveDigestCollabEvents,timingCompatible,START_TOLERANCE_MS});
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(typeof window!=='undefined')window.HOLOVIEWER_DIGEST_COLLAB=api;
})();
