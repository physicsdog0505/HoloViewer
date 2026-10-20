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
 async function fetchJson(apiBase,path){
  const base=baseOf(apiBase);
  if(!base||!/^https:\/\//.test(base))return {status:0,payload:{error:'api_not_configured'}};
  const response=await fetch(base+path,{mode:'cors',credentials:'omit',headers:{Accept:'application/json'}});
  return {status:response.status,payload:await readJson(response)};
 }
 async function resolve(videoId,options={}){
  const id=String(videoId||'');
  if(!VALID_ID.test(id))return {status:'invalid',videoId:id,row:null,httpStatus:0};
  const apiBase=baseOf(options.apiBase||global.HOLOVIEWER_CONFIG?.apiBase||'');
  const preferCatalog=options.preferCatalog!==false;
  const waitForRecovery=options.waitForRecovery!==false;
  const maxAttempts=Math.max(1,Math.min(12,Number(options.maxAttempts)||6));
  const signal=options.signal||null;

  if(preferCatalog){
   const catalog=await fetchJson(apiBase,'/v1/catalog/videos/'+encodeURIComponent(id));
   if(signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};
   if(catalog.status===200)return {status:'ready',videoId:id,row:catalog.payload,httpStatus:200,source:'catalog'};
  }

  for(let attempt=1;attempt<=maxAttempts;attempt++){
   const query=new URLSearchParams();
   if(/^\d{4}-\d{2}-\d{2}$/.test(String(options.pttDay||'')))query.set('ptt_day',String(options.pttDay));
   const suffix=query.toString()?'?'+query.toString():'';
   const result=await fetchJson(apiBase,'/v1/videos/'+encodeURIComponent(id)+'/metadata'+suffix);
   if(signal?.aborted)return {status:'aborted',videoId:id,row:null,httpStatus:0};
   const payload=result.payload||{};
   if(result.status===200)return {status:'ready',videoId:id,row:payload,httpStatus:200,source:'metadata',attempt};
   const pending=result.status===202&&payload.status==='metadata_pending';
   const busy=result.status===429&&payload.error==='recovery_queue_busy';
   if((pending||busy)&&waitForRecovery&&attempt<maxAttempts){
    await sleep(retryDelaySeconds(payload)*1000);
    continue;
   }
   if(pending||busy)return {status:'pending',videoId:id,row:payload,httpStatus:result.status,attempt};
   if(result.status===404&&payload.error==='metadata_not_found_cached'){
    return {status:'not-found',videoId:id,row:payload,httpStatus:404,attempt};
   }
   return {status:'error',videoId:id,row:payload,httpStatus:result.status,attempt};
  }
  return {status:'pending',videoId:id,row:null,httpStatus:202,attempt:maxAttempts};
 }

 window.HoloViewerVideoMetadata=Object.freeze({resolve,retryDelaySeconds});
})(window);
