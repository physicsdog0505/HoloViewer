'use strict';
(function(global){
 const VALID_ID=/^[A-Za-z0-9_-]{11}$/;
 function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
 function retryDelaySeconds(payload){
  const raw=Number(payload?.retry_after_seconds);
  return Math.max(2,Math.min(60,Number.isFinite(raw)?raw:5));
 }
 async function readJson(response){
  try{return await response.json()}catch{return {}}
 }
 function baseOf(value){return String(value||'').replace(/\/$/,'')}
 async function fetchJson(apiBase,path,signal=null){
  const base=baseOf(apiBase);
  if(!base||!/^https:\/\//.test(base))return {status:0,payload:{error:'api_not_configured'}};
  if(signal?.aborted)return {status:0,payload:{error:'aborted'},aborted:true};
  try{
   const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'},...(signal?{signal}:{})});
   return {status:response.status,payload:await readJson(response)};
  }catch(error){
   if(signal?.aborted||error?.name==='AbortError')return {status:0,payload:{error:'aborted'},aborted:true};
   return {status:0,payload:{error:'transport_error'},transportError:true};
  }
 }
 async function historicalStaticRow(videoId,day,staticBase,signal=null){
  const month=String(day||'').slice(0,7);
  if(!VALID_ID.test(videoId)||!/^\d{4}-\d{2}$/.test(month))return null;
  const manifestResult=await fetchJson(staticBase,'/youtube/v1/manifest.json',signal);
  if(manifestResult.aborted||manifestResult.status!==200)return null;
  const manifest=manifestResult.payload||{};
  if(manifest.schema_version!==1||!Array.isArray(manifest.months))return null;
  const monthState=String(manifest.availability?.month_state?.[month]?.state||manifest.availability?.month_state?.[month]||'').toLowerCase();
  if(monthState&&monthState!=='published'&&monthState!=='available')return null;
  const entry=manifest.months.find(item=>item&&String(item.month||'')===month&&typeof item.path==='string');
  if(!entry||!String(entry.path).startsWith('youtube/v1/'))return null;
  const monthResult=await fetchJson(staticBase,'/'+String(entry.path).replace(/^\/+/,''),signal);
  if(monthResult.aborted||monthResult.status!==200)return null;
  const payload=monthResult.payload||{};
  if(payload.schema_version!==1||!Array.isArray(payload.videos))return null;
  const row=payload.videos.find(item=>String(item?.video_id||'')===videoId);
  const start=Date.parse(String(row?.actual_start||'')),end=Date.parse(String(row?.actual_end||''));
  if(!row||!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return null;
  return {...row,lifecycle_state:'ended',state:'ended'};
 }
 async function resolve(videoId,options={}){
  const id=String(videoId||'');
  if(!VALID_ID.test(id))return {status:'invalid',videoId:id,row:null,httpStatus:0};
  const apiBase=baseOf(options.apiBase||global.HOLOVIEWER_CONFIG?.apiBase||'');
  const youtubeStaticBase=baseOf(options.youtubeStaticBase||global.HOLOVIEWER_CONFIG?.youtubeStaticBase||'');
  const preferCatalog=options.preferCatalog!==false;
  const waitForRecovery=options.waitForRecovery!==false;
  const maxAttempts=Math.max(1,Math.min(12,Number(options.maxAttempts)||6));
  const signal=options.signal||null;
  if(signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};

  if(preferCatalog){
   const catalog=await fetchJson(apiBase,'/v1/catalog/videos/'+encodeURIComponent(id),signal);
   if(catalog.aborted||signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};
   if(catalog.status===200)return {status:'ready',videoId:id,row:catalog.payload,httpStatus:200,source:'catalog'};
  }

  for(let attempt=1;attempt<=maxAttempts;attempt++){
   const query=new URLSearchParams();
   if(/^\d{4}-\d{2}-\d{2}$/.test(String(options.pttDay||'')))query.set('ptt_day',String(options.pttDay));
   const suffix=query.toString()?'?'+query.toString():'';
   const result=await fetchJson(apiBase,'/v1/videos/'+encodeURIComponent(id)+'/metadata'+suffix,signal);
   if(result.aborted||signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};
   const payload=result.payload||{};
   if(result.transportError)return {status:'error',videoId:id,row:payload,httpStatus:0,attempt};
   if(result.status===200)return {status:'ready',videoId:id,row:payload,httpStatus:200,source:'metadata',attempt};
   const pending=result.status===202&&payload.status==='metadata_pending';
   const busy=result.status===429&&payload.error==='recovery_queue_busy';
   if((pending||busy)&&waitForRecovery&&attempt<maxAttempts){
    await sleep(retryDelaySeconds(payload)*1000);
    continue;
   }
   if(pending||busy)return {status:'pending',videoId:id,row:payload,httpStatus:result.status,attempt};
   if(result.status===404&&/^\d{4}-\d{2}-\d{2}$/.test(String(options.pttDay||''))&&youtubeStaticBase){
    const row=await historicalStaticRow(id,String(options.pttDay),youtubeStaticBase,signal);
    if(signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};
    if(row)return {status:'ready',videoId:id,row,httpStatus:200,source:'youtube-static',attempt};
   }
   if(result.status===404&&payload.error==='metadata_not_found_cached'){
    return {status:'not-found',videoId:id,row:payload,httpStatus:404,attempt};
   }
   return {status:'error',videoId:id,row:payload,httpStatus:result.status,attempt};
  }
  return {status:'pending',videoId:id,row:null,httpStatus:202,attempt:maxAttempts};
 }

 window.HoloViewerVideoMetadata=Object.freeze({resolve,retryDelaySeconds});
})(window);
