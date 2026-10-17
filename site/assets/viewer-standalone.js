'use strict';
const params=new URLSearchParams(location.search);
const ids=[...new Set(params.getAll('stream').filter(id=>/^[A-Za-z0-9_-]{11}$/.test(id)))].slice(0,3);
const grid=document.getElementById('grid');
if(!ids.length){
  const empty=document.createElement('div');
  empty.className='empty';
  empty.textContent='沒有可播放的 YouTube 影片。';
  grid.append(empty);
}else{
  grid.classList.add(ids.length===1?'one':ids.length===2?'two':'three');
  ids.forEach((id,index)=>{
    const shell=document.createElement('section');
    shell.className='player';
    const frame=document.createElement('iframe');
    const src=new URL('https://www.youtube-nocookie.com/embed/'+encodeURIComponent(id));
    src.searchParams.set('enablejsapi','1');
    if(/^https?:$/.test(location.protocol))src.searchParams.set('origin',location.origin);
    frame.src=src.toString();
    frame.title='YouTube player '+(index+1);
    frame.allow='accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share';
    frame.referrerPolicy='strict-origin-when-cross-origin';
    frame.allowFullscreen=true;
    shell.append(frame);
    grid.append(shell);
  });
}
