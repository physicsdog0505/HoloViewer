'use strict';
(function(root){
 const MONTHLY_SCHEMA='holoviewer-ptt-monthly-catalog-v1';
 const LEGACY_SCHEMA='ptt-r2-archive-v1';
 const DAILY_SCHEMA='holoviewer-ptt-daily-static-package-v1';
 const DAY_V1='holoviewer-ptt-history-day-v1';
 const DAY_V2='holoviewer-ptt-history-day-v2';
 const catalogCache=new Map();
 const manifestCache=new Map();

 function integrity(message){const error=new Error(message);error.archiveIntegrity=true;return error}
 function unavailable(message){const error=new Error(message);error.archiveUnavailable=true;return error}
 function isSha(value){return /^[0-9a-f]{64}$/.test(String(value||''))}
 function safeKey(value){
  const key=String(value||'');
  return Boolean(key&&!key.startsWith('/')&&key.endsWith('.json')&&!key.split('/').some(part=>!part||part==='.'||part==='..'));
 }
 function rangeOf(value){
  const startRaw=value?.partition_start??value?.range_start??value?.bucket_start;
  const endRaw=value?.partition_end??value?.range_end??value?.bucket_end;
  const startMs=Date.parse(String(startRaw||'')),endMs=Date.parse(String(endRaw||''));
  return Number.isFinite(startMs)&&Number.isFinite(endMs)&&endMs>startMs?{startMs,endMs}:null;
 }
 function pushCount(value){
  const count=value?.push_count??value?.pushes;
  return Number.isInteger(count)&&count>=0?count:null;
 }
 function identity(row){
  const stable=String(row?.source_record_key||row?.push_id||'');
  if(stable)return stable;
  const aid=String(row?.aid||''),line=Number(row?.source_line);
  if(aid&&Number.isInteger(line)&&line>=0)return aid+'|source_line:'+line;
  return '';
 }
 function dayStartMs(day){const ms=Date.parse(String(day)+'T00:00:00+08:00');return Number.isFinite(ms)?ms:null}
 function nextDayStartMs(day){const start=dayStartMs(day);return start===null?null:start+86400000}
 async function sha256Hex(buffer){
  if(!root.crypto?.subtle)throw integrity('瀏覽器不支援歷史檔案 SHA-256 驗證');
  const digest=await root.crypto.subtle.digest('SHA-256',buffer);
  return [...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
 }
 async function fetchBytes(url){
  let response;
  try{response=await fetch(url,{mode:'cors',credentials:'omit',cache:'no-cache',headers:{Accept:'application/json'}})}
  catch(error){throw unavailable('歷史 PTT 無法讀取：'+url+' · '+String(error?.message||error))}
  if(!response.ok){
   const error=unavailable('歷史 PTT HTTP '+response.status+'：'+url);
   error.httpStatus=response.status;
   throw error;
  }
  const contentType=String(response.headers.get('content-type')||'').toLowerCase();
  if(contentType&&!contentType.startsWith('application/json'))throw integrity('歷史 PTT Content-Type 不符：'+url);
  return response.arrayBuffer();
 }
 function parseJson(buffer,label){
  try{return JSON.parse(new TextDecoder().decode(buffer))}
  catch{throw integrity(label+' JSON 無效')}
 }
 function validateCatalog(value,month){
  if(value?.schema_version!==MONTHLY_SCHEMA||value?.month!==month||value?.timezone!=='Asia/Taipei'||!Array.isArray(value?.days))
   throw integrity('歷史 PTT monthly catalog 格式不支援');
  const seen=new Set();
  for(const row of value.days){
   const day=String(row?.day||''),source=row?.source,manifest=source?.manifest;
   const expectedSchema=source?.kind==='daily-package-v1'?DAILY_SCHEMA:
    source?.kind==='legacy-archive-v1'?LEGACY_SCHEMA:'';
   if(!/^\d{4}-\d{2}-\d{2}$/.test(day)||!day.startsWith(month+'-')||seen.has(day)||
      row?.coverage_status!=='COMPLETE'||!expectedSchema||
      !/^https:\/\//.test(String(source?.base||''))||!safeKey(manifest?.key)||!isSha(manifest?.sha256)||
      manifest?.schema_version!==expectedSchema)
    throw integrity('歷史 PTT monthly catalog day entry 無效');
   seen.add(day);
  }
  return value;
 }
 async function fetchCatalog(catalogBase,month,force=false){
  const base=String(catalogBase||'').replace(/\/$/,'');
  if(!/^https:\/\//.test(base))return null;
  const key=base+'|'+month;
  if(catalogCache.has(key)&&!force)return catalogCache.get(key);
  const url=base+'/ptt/v1/manifests/monthly/'+month+'.json';
  let buffer;
  try{buffer=await fetchBytes(url)}
  catch(error){
   if(error?.archiveUnavailable)return null;
   throw error;
  }
  const value=validateCatalog(parseJson(buffer,'monthly catalog'),month);
  catalogCache.set(key,value);return value;
 }
 function legacySource(month,legacyMonths){
  const raw=legacyMonths?.[month],base=String(raw?.base||'').replace(/\/$/,''),manifest=String(raw?.manifest||'');
  if(!/^https:\/\//.test(base)||!manifest.startsWith('/'))return null;
  return {month,day:'',base,manifest:manifest.replace(/^\//,''),schema:LEGACY_SCHEMA,manifestSha256:''};
 }
 async function sourceForDay({day,catalogBase,legacyMonths,force=false}){
  const month=String(day||'').slice(0,7);
  const catalog=await fetchCatalog(catalogBase,month,force);
  if(catalog){
   const row=catalog.days.find(item=>String(item.day)===day);
   if(!row)return {coverageStatus:'MISSING',source:null,catalog:true};
   const source=row.source,manifest=source.manifest;
   return {coverageStatus:'COMPLETE',catalog:true,source:{
    month,day,base:String(source.base).replace(/\/$/,''),manifest:String(manifest.key),
    schema:String(manifest.schema_version||''),manifestSha256:String(manifest.sha256||'')
   }};
  }
  const source=legacySource(month,legacyMonths);
  return {coverageStatus:null,source,catalog:false};
 }
 function validateLegacyManifest(manifest){
  if(manifest?.schema_version!==LEGACY_SCHEMA||manifest?.precision!=='minute'||manifest?.timezone!=='UTC'||
     !Array.isArray(manifest?.objects)||!Array.isArray(manifest?.days))throw integrity('歷史 PTT legacy manifest 格式不支援');
  for(const item of manifest.objects){
   if(!safeKey(item?.key)||!isSha(item?.sha256)||!rangeOf(item)||pushCount(item)===null)
    throw integrity('歷史 PTT legacy manifest 物件索引無效');
  }
  return manifest;
 }
 function validateDailyManifest(manifest,day){
  if(manifest?.schema_version!==DAILY_SCHEMA||manifest?.taipei_day!==day||!Array.isArray(manifest?.objects))
   throw integrity('歷史 PTT daily manifest 格式不支援');
  let total=0;
  for(const item of manifest.objects){
   const count=pushCount(item);
   if(!safeKey(item?.key)||!isSha(item?.sha256)||count===null)throw integrity('歷史 PTT daily manifest 物件索引無效');
   total+=count;
  }
  if(!Number.isInteger(manifest?.total_pushes)||manifest.total_pushes!==total)throw integrity('歷史 PTT daily manifest push count 不符');
  return manifest;
 }
 async function fetchManifest(source,force=false){
  const cacheKey=[source.base,source.manifest,source.manifestSha256].join('|');
  if(manifestCache.has(cacheKey)&&!force)return manifestCache.get(cacheKey);
  const url=source.base+'/'+source.manifest.replace(/^\//,'');
  const buffer=await fetchBytes(url);
  if(source.manifestSha256){
   const digest=await sha256Hex(buffer);
   if(digest!==source.manifestSha256)throw integrity('歷史 PTT manifest SHA 不符：'+url);
  }
  const value=parseJson(buffer,'archive manifest');
  const manifest=source.schema===DAILY_SCHEMA?validateDailyManifest(value,source.day):
   source.schema===LEGACY_SCHEMA?validateLegacyManifest(value):null;
  if(!manifest)throw integrity('歷史 PTT archive source schema 不支援');
  manifestCache.set(cacheKey,manifest);return manifest;
 }
 function coverageStatus(manifest,day){
  const row=manifest?.days?.find(item=>String(item?.day||'')===day);
  const status=String(row?.coverage_status||'MISSING');
  return ['COMPLETE','PARTIAL','MISSING','UNKNOWN'].includes(status)?status:'UNKNOWN';
 }
 function validateDailyPayload(payload,day,item){
  if(![DAY_V1,DAY_V2].includes(payload?.schema_version)||!Array.isArray(payload?.pushes))throw integrity('歷史 PTT daily object schema 不支援');
  if(payload.pushes.length!==pushCount(item))throw integrity('歷史 PTT daily object push count 不符');
  const range=rangeOf(payload),start=dayStartMs(day),next=nextDayStartMs(day);
  if(!range||start===null||next===null||range.startMs!==start)throw integrity('歷史 PTT daily object partition range 不符');
  if(payload.schema_version===DAY_V1&&range.endMs!==next)throw integrity('歷史 PTT daily v1 partition range 不符');
  if(payload.schema_version===DAY_V2&&(range.endMs<next||range.endMs>next+27000000))throw integrity('歷史 PTT daily v2 partition_end 不符');
  if(payload?.membership?.silent_drop!==false)throw integrity('歷史 PTT daily membership audit 不符');
  for(const row of payload.pushes){
   const when=Date.parse(String(row?.occurred_at||''));
   if(row?.coverage_day!==day||!Number.isFinite(when)||when<range.startMs||when>=range.endMs||
      !identity(row)||row?.floor==null||row?.floor_quality!=='per-thread-ordinal')
    throw integrity('歷史 PTT daily push contract 不符');
  }
  return range;
 }
 async function fetchObject(source,item){
  const url=source.base+'/'+String(item.key).replace(/^\//,'');
  const buffer=await fetchBytes(url),digest=await sha256Hex(buffer);
  if(digest!==String(item.sha256||''))throw integrity('歷史 PTT object SHA 不符：'+url);
  const payload=parseJson(buffer,'archive object');
  if(source.schema===DAILY_SCHEMA){
   validateDailyPayload(payload,source.day,item);
  }else{
   const expected=rangeOf(item),actual=rangeOf(payload);
   if(payload?.schema_version!==LEGACY_SCHEMA||!Array.isArray(payload?.pushes)||payload.pushes.length!==pushCount(item))
    throw integrity('歷史 PTT legacy object push count 不符');
   if(!expected||!actual||expected.startMs!==actual.startMs||expected.endMs!==actual.endMs)
    throw integrity('歷史 PTT legacy object range 不符');
  }
  return payload.pushes;
 }
 function intersects(a,b,c,d){return a<d&&c<b}
 function dedupeAndReject(rows){
  const seen=new Set();
  for(const row of rows){
   const key=identity(row);
   if(!key||seen.has(key))throw integrity('歷史 PTT duplicate source_record_key');
   seen.add(key);
  }
  return rows.slice().sort((a,b)=>Date.parse(String(a?.occurred_at||''))-Date.parse(String(b?.occurred_at||''))||
   String(a?.aid||'').localeCompare(String(b?.aid||''))||(Number(a?.source_line)||0)-(Number(b?.source_line)||0));
 }
 async function resolveDaySlice({day,rangeStart,rangeEnd,catalogBase,legacyMonths}){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(String(day||''))||!Number.isFinite(rangeStart)||!Number.isFinite(rangeEnd)||rangeEnd<=rangeStart)
   throw integrity('歷史 PTT day/range 無效');
  let resolved=await sourceForDay({day,catalogBase,legacyMonths});
  if(resolved.catalog&&!resolved.source)return {day,coverageStatus:resolved.coverageStatus,rows:[],source:null,objectRequests:[]};
  if(!resolved.source)throw unavailable('歷史 PTT 月份來源未設定：'+day.slice(0,7));
  let lastError=null;
  for(let attempt=0;attempt<2;attempt++){
   try{
    if(attempt===1)resolved=await sourceForDay({day,catalogBase,legacyMonths,force:true});
    if(resolved.catalog&&!resolved.source)return {day,coverageStatus:resolved.coverageStatus,rows:[],source:null,objectRequests:[]};
    const source=resolved.source,manifest=await fetchManifest(source,attempt===1);
    const status=resolved.coverageStatus||coverageStatus(manifest,day);
    const plan=source.schema===DAILY_SCHEMA?manifest.objects:
      manifest.objects.filter(item=>{const r=rangeOf(item);return r&&intersects(r.startMs,r.endMs,rangeStart,rangeEnd)});
    const rows=[],requests=[];
    for(const item of plan){
     const pushes=await fetchObject(source,item);requests.push(source.base+'/'+item.key);
     for(const row of pushes){
      const occurred=Date.parse(String(row?.occurred_at||''));
      if(Number.isFinite(occurred)&&occurred>=rangeStart&&occurred<rangeEnd)rows.push(row);
     }
    }
    return {day,coverageStatus:status,rows:dedupeAndReject(rows),source,objectRequests:requests};
   }catch(error){
    lastError=error;
    if(attempt===0&&error?.archiveIntegrity){manifestCache.clear();catalogCache.clear();continue}
    break;
   }
  }
  throw lastError||unavailable('歷史 PTT '+day+' 無法讀取');
 }

 root.HoloViewerPttArchive=Object.freeze({resolveDaySlice});
})(globalThis);
