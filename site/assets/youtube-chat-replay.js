(()=>{
'use strict';
function cc(args){let total=0;for(const a of args)total+=a.length;const out=new Uint8Array(total);let offset=0;for(const a of args){out.set(a,offset);offset+=a.length}return out}
function encv(n){n=BigInt(n);let s=0n;while(n>>7n){s=(s<<8n)|0x80n|(n&0x7fn);n>>=7n}return(s<<8n)|n}
function hextou8(data){const out=new Uint8Array(data.length/2);for(let i=0;i<out.length;i++)out[i]=parseInt(data.substr(i*2,2),16);return out}
function bitou8(n){let hex=BigInt(n).toString(16);hex=''.padStart(hex.length%2,'0')+hex;return hextou8(hex)}
function pbh(fid,type){return encv((BigInt(fid)<<3n)|BigInt(type))}
function ld(fid,payload){let body;if(typeof payload==='string')body=new TextEncoder().encode(payload);else if(Array.isArray(payload))body=cc(payload);else body=payload;return cc([bitou8(pbh(fid,2)),bitou8(encv(BigInt(body.byteLength))),body])}
function vt(fid,payload){return cc([bitou8(pbh(fid,0)),bitou8(payload)])}
function b64(data){return btoa(String.fromCharCode.apply(null,data))}
function cvToken(channelId,videoId){return ld(5,[ld(1,channelId),ld(2,videoId)])}
function hdt(channelId,videoId){return b64(cc([ld(1,cvToken(channelId,videoId)),ld(3,ld(48687757,ld(1,videoId))),vt(4,1)]))}
function replayContinuation(videoId,channelId,seekMs=0){return encodeURIComponent(b64(ld(156074452,[ld(3,hdt(channelId,videoId)),vt(8,1),ld(11,vt(2,Math.max(0,Math.round(Number(seekMs)||0)))),ld(14,vt(1,1)),vt(15,1)])))}
function validVideoId(value){return /^[A-Za-z0-9_-]{11}$/.test(String(value||''))}
function validChannelId(value){return /^UC[A-Za-z0-9_-]{20,}$/.test(String(value||''))}
function buildUrl({videoId,channelId='',mode,embedDomain=location.hostname,dark=true,seekSeconds=0}={}){
 const id=String(videoId||''),channel=String(channelId||''),domain=String(embedDomain||location.hostname);
 if(!validVideoId(id)||!domain)return '';
 const q=new URLSearchParams({v:id,embed_domain:domain,dark_theme:dark?'1':'0'});
 if(mode==='vod'){
  if(!validChannelId(channel))return '';
  const seekMs=Math.max(0,Math.round((Number(seekSeconds)||0)*1000));
  q.set('c',channel);
  q.set('continuation',replayContinuation(id,channel,seekMs));
  return 'https://www.youtube.com/live_chat_replay?'+q.toString();
 }
 if(mode==='live')return 'https://www.youtube.com/live_chat?'+q.toString();
 return '';
}
function sync(frame,seconds){
 const t=Number(seconds);
 if(!frame?.contentWindow||!Number.isFinite(t))return false;
 frame.contentWindow.postMessage({'yt-player-video-progress':Math.max(0,t)},'*');
 return true;
}
window.HoloViewerYouTubeChat={buildUrl,sync,replayContinuation};
})();