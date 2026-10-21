'use strict';
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.HoloViewerViewingShareState=Object.freeze(api);
})(typeof globalThis!=='undefined'?globalThis:null,function(){
 const ID=/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
 const TOKEN=/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

 function invalid(error){return {status:'INVALID',error,state:null}}
 function normalize(input){
  if(!input||!ID.test(String(input.sessionId||'')))return invalid('session_id invalid');
  const povIds=Array.isArray(input.povIds)?input.povIds.map(String):[];
  if(!povIds.length||povIds.some(id=>!ID.test(id))||new Set(povIds).size!==povIds.length)return invalid('pov_ids invalid');
  const primaryPovId=String(input.primaryPovId||'');
  if(!povIds.includes(primaryPovId))return invalid('primary_pov_id invalid');
  const masterTimeMs=Number(input.masterTimeMs);
  if(!Number.isInteger(masterTimeMs)||masterTimeMs<0)return invalid('master_time_ms invalid');
  const optionalToken=(value,name)=>{
   const text=value===undefined||value===null?'':String(value);
   if(text&&!TOKEN.test(text))throw new Error(name+' invalid');
   return text;
  };
  try{
   const revision=optionalToken(input.revision,'revision');
   const layout=optionalToken(input.layout,'layout');
   const mode=optionalToken(input.mode,'mode');
   const pttMode=optionalToken(input.pttMode,'ptt_mode');
   return {status:'READY',error:'',state:{
    sessionId:String(input.sessionId),revision,povIds,primaryPovId,masterTimeMs,layout,mode,pttMode
   }};
  }catch(error){return invalid(error.message)}
 }

 function serialize(input){
  const normalized=normalize(input);
  if(normalized.status!=='READY')throw new Error(normalized.error);
  const state=normalized.state;
  const params=new URLSearchParams();
  params.set('session',state.sessionId);
  if(state.revision)params.set('rev',state.revision);
  state.povIds.forEach(id=>params.append('pov',id));
  params.set('primary_pov',state.primaryPovId);
  params.set('t_ms',String(state.masterTimeMs));
  if(state.layout)params.set('layout',state.layout);
  if(state.mode)params.set('mode',state.mode);
  if(state.pttMode)params.set('ptt',state.pttMode);
  return params.toString();
 }

 function parse(value){
  let params;
  try{params=value instanceof URLSearchParams?value:new URLSearchParams(String(value||'').replace(/^\?/,''))}
  catch{return invalid('query invalid')}
  return normalize({
   sessionId:params.get('session')||'',
   revision:params.get('rev')||'',
   povIds:params.getAll('pov'),
   primaryPovId:params.get('primary_pov')||'',
   masterTimeMs:Number(params.get('t_ms')),
   layout:params.get('layout')||'',
   mode:params.get('mode')||'',
   pttMode:params.get('ptt')||'',
  });
 }

 return Object.freeze({normalize,serialize,parse});
});
