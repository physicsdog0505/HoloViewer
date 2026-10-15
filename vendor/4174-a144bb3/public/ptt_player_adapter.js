/* Portable PTT player adapter. Loads after ptt_timeline.js.
 * Host owns the existing YouTube player; this code never creates/replaces it.
 */
(function(root){
'use strict';
function attach(options){
  const core=root.HoloViewerPttTimeline;
  if(!core)throw new Error('PTT timeline core missing');
  const player=options.player;
  if(!player||typeof player.getCurrentTime!=='function')throw new Error('Existing YouTube player required');
  if(typeof options.render!=='function')throw new Error('PTT render callback required');
  const timeline=core.createTimeline(options.start,options.initialMessages||[]);
  const pollMs=Math.max(3000,Number(options.pollMs)||10000);
  let disposed=false, visible=-1, timer=null, polling=null, inFlight=false;
  let dataVersion=0, renderedVersion=-1, total=timeline.snapshot().length;
  function update(force){
    if(disposed)return;
    let seconds;
    try{seconds=Number(player.getCurrentTime());}catch(_error){return;}
    if(!Number.isFinite(seconds))return;
    const count=timeline.count(seconds);
    if(force||count!==visible||renderedVersion!==dataVersion){
      visible=count;renderedVersion=dataVersion;
      options.render(timeline.at(seconds),{visible:count,total:total,time:seconds});
    }
  }
  function report(state,message){
    if(typeof options.status==='function')options.status(state,message);
  }
  async function poll(){
    if(disposed||inFlight||!options.endpoint)return;
    if(root.document&&root.document.hidden)return;
    inFlight=true;
    try{
      const result=await core.fetchFeed(options.endpoint,options.fetcher);
      if(disposed)return;
      total=timeline.update(result);
      dataVersion++;
      update(false);
      report('ready','PTT 資料已更新');
    }catch(error){
      if(!disposed)report('error',String(error.message||error));
    }finally{inFlight=false;}
  }
  update(true);
  timer=root.setInterval(function(){update(false);},250);
  if(options.endpoint){
    poll();
    polling=root.setInterval(poll,pollMs);
  }else report('unconfigured','PTT 尚未設定可公開讀取的 HTTPS 資料來源');
  return Object.freeze({
    seek:()=>update(true),
    refresh:poll,
    snapshot:()=>timeline.snapshot(),
    ingest:function(rows){if(disposed)throw new Error('PTT adapter disposed');total=timeline.update(rows);dataVersion++;update(false);return total;},
    dispose:function(){disposed=true;root.clearInterval(timer);if(polling)root.clearInterval(polling);}
  });
}
root.HoloViewerPttPlayer=Object.freeze({attach});
})(typeof globalThis!=='undefined'?globalThis:this);
