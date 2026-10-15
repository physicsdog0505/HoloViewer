/* Public HoloViewer PR #19 Worker GET /v1/ptt adapter.
 * Contract source: physicsdog0505/HoloViewer@804a9e7 relay/worker.mjs.
 * Read-only; per-article cursors are committed only after complete pages.
 */
(function(root){
'use strict';
const AID=/^[A-Za-z0-9._-]{1,32}$/;
const PUSH_ID=/^ptt:v1:[0-9a-f]{64}$/;
const KINDS=new Set(['推','噓','嘘','→']);
function matchesArticleUrl(value,aid){
 try{
  const url=new URL(value);
  const parts=url.pathname.split('/');
  return url.protocol==='https:'&&
   (url.hostname==='ptt.cc'||url.hostname==='www.ptt.cc')&&
   !url.username&&!url.password&&
   parts.length===4&&parts[1]==='bbs'&&
   /^[A-Za-z0-9_-]+$/.test(parts[2])&&parts[3]===aid+'.html';
 }catch(_error){return false;}
}
function checkedResponse(body,aid,after){
 if(!body||body.schema_version!==1||!Array.isArray(body.pushes)||body.pushes.length>500||
  !Number.isSafeInteger(body.next_cursor)||body.next_cursor<after||
  typeof body.has_more!=='boolean'||typeof body.history_gap!=='boolean'||
  !Number.isSafeInteger(body.purged_through_cursor)||body.purged_through_cursor<0)
  throw new Error('Invalid Worker v1 response');
 let previous=after;
 const seen=new Set();
 const rows=body.pushes.map(function(p){
  if(!p||p.aid!==aid||!PUSH_ID.test(p.push_id)||seen.has(p.push_id)||
    !Number.isSafeInteger(p.cursor)||p.cursor<=previous||
    typeof p.occurred_at!=='string'||!p.occurred_at.endsWith('Z')||
    !Number.isFinite(Date.parse(p.occurred_at))||!KINDS.has(p.kind)||
    typeof p.author!=='string'||typeof p.content!=='string'||
    !Number.isSafeInteger(p.source_line)||p.source_line<1||
    (p.floor!==null&&(!Number.isSafeInteger(p.floor)||p.floor<1))||
    typeof p.article_url!=='string'||!matchesArticleUrl(p.article_url,aid))
    throw new Error('Worker AID, push, timestamp or cursor mismatch');
  seen.add(p.push_id);
  previous=p.cursor;
  return {key:p.push_id,aid:p.aid,cursor:p.cursor,
   timestamp:p.occurred_at,kind:p.kind,author:p.author,content:p.content,
   floor:p.floor,article_url:p.article_url};
 });
 if(body.next_cursor!==(rows.length?previous:after)||
    (body.has_more&&rows.length===0))throw new Error('Incomplete Worker page');
 return rows;
}
function create(options){
 if(!AID.test(options.aid||''))throw new Error('Explicit article AID required');
 const base=new URL(options.endpoint);
 if(base.protocol!=='https:'||base.username||base.password||
    !base.pathname.endsWith('/v1/ptt'))throw new Error('HTTPS Worker /v1/ptt required');
 if(typeof options.onRows!=='function')throw new Error('onRows required');
 const fetcher=options.fetcher||root.fetch.bind(root);
 const mode=options.mode===undefined?'history':options.mode;
 if(mode!=='history'&&mode!=='recent')throw new Error('Invalid Worker initialization mode');
 let cursor=0,stopped=false,abort=null,busy=false,initialized=false,gap=false;
 let coverage=mode==='recent'?'recent-only':'loading-history';
 let failures=0,nextAllowedAt=0;
 const wanted=options.limit===undefined?200:options.limit;
 if(!Number.isSafeInteger(wanted)||wanted<1)throw new Error('Invalid Worker page limit');
 const limit=Math.min(500,wanted);
 async function once(){
  if(stopped||busy||Date.now()<nextAllowedAt)return;
  busy=true;
  abort=new AbortController();
  try{
   // First sample newest retained tail. Explicit AID is mandatory.
   // Later reads drain each page, advancing only AFTER successful processing.
   let more=true,pages=0;
   while(more&&!stopped&&pages<25){
    const url=new URL(base.href);
    url.searchParams.set('aid',options.aid);
    url.searchParams.set('limit',String(limit));
    if(!initialized&&mode==='recent')url.searchParams.set('tail','1');
    else url.searchParams.set('after_cursor',String(cursor));
    const timeout=setTimeout(()=>abort.abort(),10000);
    let response,body;
    try{
      response=await fetcher(url.href,{method:'GET',credentials:'omit',cache:'no-store',signal:abort.signal});
      if(!response.ok)throw new Error('Worker HTTP '+response.status);
      body=await response.json();
    }finally{clearTimeout(timeout);}
    if(stopped)return;
    const rows=checkedResponse(body,options.aid,initialized?cursor:0);
    // In initial tail mode global cursors may start after zero.
    const mapped=rows.map(item=>({
      key:item.key,timestamp:item.timestamp,kind:item.kind,author:item.author,
      content:item.content,floor:item.floor,article_url:item.article_url,
      aid:item.aid,cursor:item.cursor
    }));
    await options.onRows(mapped,{history_gap:body.history_gap,
      purged_through_cursor:body.purged_through_cursor,initial:!initialized});
    if(stopped)return;
    cursor=body.next_cursor;initialized=true;
    gap=gap||body.history_gap;
    if(gap&&typeof options.onGap==='function')options.onGap(body.purged_through_cursor);
    more=body.has_more;
    if(mode==='history'&&!more)coverage=gap?'history-gap':'history-loaded';
    failures=0;nextAllowedAt=0;
    pages++;
   }
  }catch(error){
    if(!stopped){failures=Math.min(7,failures+1);
      nextAllowedAt=Date.now()+Math.min(120000,3000*Math.pow(2,failures-1));}
    throw error;
  }finally{busy=false;abort=null;}
 }
 return Object.freeze({run:once,stop:function(){stopped=true;if(abort)abort.abort();},
  cursor:function(){return cursor;},hasGap:function(){return gap;},coverage:function(){return coverage;}});
}
root.HoloViewerWorkerPtt=Object.freeze({create,checkedResponse});
})(typeof globalThis!=='undefined'?globalThis:this);
