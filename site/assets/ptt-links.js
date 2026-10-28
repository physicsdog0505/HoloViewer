'use strict';

(()=>{
 const URL_RE=/https?:\/\/[^\s<>"']+/gi;
 const TRAILING=/[.,!?;:\)\]\}、。！？；：」』】]+$/;
 const IMAGE_EXT=/\.(?:avif|gif|jpe?g|png|webp)$/i;
 const IMAGE_HOSTS=new Set(['i.imgur.com','i.urusai.cc','i.meee.com.tw','dec.2chan.net']);
 const NON_IMAGE_HOSTS=new Set(['youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be']);
 const previewMedia=window.matchMedia('(hover:hover) and (pointer:fine)');
 let preview=null;
 let previewImage=null;
 let previewTimer=0;
 let previewLink=null;
 let pointerX=0;
 let pointerY=0;

 function splitTrailing(raw){
  const match=String(raw||'').match(TRAILING);
  if(!match)return [String(raw||''),''];
  return [String(raw||'').slice(0,-match[0].length),match[0]];
 }
 function parsedUrl(raw){
  try{
   const url=new URL(raw);
   if(url.protocol!=='http:'&&url.protocol!=='https:')return null;
   return url;
  }catch{return null}
 }
 function isImageUrl(raw){
  const url=parsedUrl(raw);
  if(!url||NON_IMAGE_HOSTS.has(url.hostname.toLowerCase()))return false;
  return IMAGE_EXT.test(url.pathname)||IMAGE_HOSTS.has(url.hostname.toLowerCase());
 }
 function ensurePreview(){
  if(preview)return preview;
  preview=document.createElement('div');
  preview.className='ptt-link-preview';
  preview.hidden=true;
  preview.setAttribute('aria-hidden','true');
  previewImage=document.createElement('img');
  previewImage.alt='';
  previewImage.decoding='async';
  previewImage.referrerPolicy='no-referrer';
  preview.append(previewImage);
  document.body.append(preview);
  return preview;
 }
 function positionPreview(){
  if(!preview||preview.hidden)return;
  const margin=14;
  const gap=14;
  const rect=preview.getBoundingClientRect();
  let left=pointerX+gap;
  let top=pointerY+gap;
  if(left+rect.width+margin>window.innerWidth)left=Math.max(margin,pointerX-rect.width-gap);
  if(top+rect.height+margin>window.innerHeight)top=Math.max(margin,pointerY-rect.height-gap);
  preview.style.left=Math.round(left)+'px';
  preview.style.top=Math.round(top)+'px';
 }
 function hidePreview(){
  clearTimeout(previewTimer);
  previewTimer=0;
  previewLink=null;
  if(preview){
   preview.hidden=true;
   previewImage.removeAttribute('src');
  }
 }
 function schedulePreview(link,event){
  if(!previewMedia.matches||link.dataset.previewFailed==='1')return;
  clearTimeout(previewTimer);
  previewLink=link;
  pointerX=event.clientX;pointerY=event.clientY;
  previewTimer=window.setTimeout(()=>{
   if(previewLink!==link)return;
   ensurePreview();
   previewImage.onload=()=>{if(previewLink===link){preview.hidden=false;positionPreview()}};
   previewImage.onerror=()=>{link.dataset.previewFailed='1';hidePreview()};
   previewImage.src=link.href;
  },250);
 }
 function makeLink(urlText){
  const link=document.createElement('a');
  link.className='ptt-content-link'+(isImageUrl(urlText)?' is-image':'');
  link.href=urlText;
  link.target='_blank';
  link.rel='noopener noreferrer';
  link.referrerPolicy='no-referrer';
  link.textContent=urlText;
  if(link.classList.contains('is-image')){
   link.addEventListener('pointerenter',event=>schedulePreview(link,event));
   link.addEventListener('pointermove',event=>{pointerX=event.clientX;pointerY=event.clientY;positionPreview()});
   link.addEventListener('pointerleave',hidePreview);
   link.addEventListener('blur',hidePreview);
  }
  return link;
 }
 function appendLinkedContent(container,value){
  const text=String(value??'');
  container.replaceChildren();
  let cursor=0;
  URL_RE.lastIndex=0;
  for(const match of text.matchAll(URL_RE)){
   const index=match.index??0;
   if(index>cursor)container.append(document.createTextNode(text.slice(cursor,index)));
   const [urlText,trailing]=splitTrailing(match[0]);
   const url=parsedUrl(urlText);
   if(url&&urlText){
    container.append(makeLink(url.href));
    if(trailing)container.append(document.createTextNode(trailing));
   }else{
    container.append(document.createTextNode(match[0]));
   }
   cursor=index+match[0].length;
  }
  if(cursor<text.length)container.append(document.createTextNode(text.slice(cursor)));
  return container;
 }

 window.HOLOVIEWER_PTT_LINKS=Object.freeze({appendLinkedContent,isImageUrl});
})();
