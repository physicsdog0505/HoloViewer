/* Direct 4174 custom-view controller extraction @ a144bb3 */
window.mount4174CustomView=function mount4174CustomView(){

const items=[];const list=document.getElementById('list');const input=document.getElementById('url');
const streamMetadata=new Map([...document.querySelectorAll('[data-live-pick]')].map(b=>[b.dataset.livePick,{channel:b.dataset.channel||b.dataset.livePick,title:b.dataset.title||'',avatar:b.dataset.avatar||''}]));
function streamLabel(id){const m=streamMetadata.get(id);return m?(m.channel+(m.title?' · '+m.title:'')):id;}
const primary=document.getElementById('primary'),audio=document.getElementById('audio'),count=document.getElementById('selectedCount');
let primaryId=null,audioId=null,dragId=null;
function moveStream(from,to){
  if(from===to||from<0||to<0||from>=items.length||to>=items.length)return;
  const [item]=items.splice(from,1);items.splice(to,0,item);render();
}
function render(){
  list.replaceChildren();count.textContent=String(items.length);
  if(primaryId!==null&&!items.includes(primaryId))primaryId=items[0]||null;
  if(audioId!==null&&!items.includes(audioId))audioId=items[0]||null;
  if(primaryId===null)primaryId=items[0]||null;
  if(audioId===null)audioId=items[0]||null;
  if(!items.length){const e=document.createElement('div');e.className='empty-selection';e.textContent='尚未加入影片';list.appendChild(e);}
  items.forEach((value,index)=>{
    const row=document.createElement('div');row.className='selected-item';row.draggable=true;row.dataset.video=value;
    if(value===primaryId)row.classList.add('is-primary');
    const grip=document.createElement('button');grip.type='button';grip.className='drag-handle';grip.textContent='⠿';grip.title='拖曳排序；也可使用 Alt 加上下方向鍵';grip.setAttribute('aria-label','拖曳或鍵盤排序 '+value);
    grip.onkeydown=e=>{if(e.altKey&&(e.key==='ArrowUp'||e.key==='ArrowDown')){e.preventDefault();moveStream(index,index+(e.key==='ArrowUp'?-1:1));}};
    const metadata=streamMetadata.get(value);
    const avatar=document.createElement('img');avatar.className='selected-avatar';avatar.alt='';avatar.loading='lazy';avatar.src=metadata?.avatar||'/favicon.ico';avatar.onerror=()=>{avatar.onerror=null;avatar.style.visibility='hidden';};
    const name=document.createElement('div');name.className='selected-name';
    const channel=document.createElement('span');channel.className='selected-channel';channel.textContent=(index+1)+' · '+(metadata?.channel||value);
    const title=document.createElement('span');title.className='selected-title';title.textContent=metadata?.title||'';name.title=streamLabel(value);name.append(channel,title);
    const choice=document.createElement('label');choice.className='primary-choice';
    const radio=document.createElement('input');radio.type='radio';radio.name='mainVideo';radio.value=value;radio.checked=value===primaryId;radio.setAttribute('aria-label','設為主視角 '+value);
    radio.onchange=()=>{primaryId=value;render();};
    const label=document.createElement('span');label.textContent=radio.checked?'主視角':'設為主視角';choice.append(radio,label);
    const actions=document.createElement('div');actions.className='item-actions';
    [['↑',-1],['↓',1]].forEach(([label,delta])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.title=delta<0?'往前':'往後';b.onclick=()=>moveStream(index,index+delta);actions.appendChild(b);});
    const rm=document.createElement('button');rm.type='button';rm.textContent='×';rm.title='移除';rm.onclick=()=>{items.splice(index,1);render();};actions.appendChild(rm);
    row.addEventListener('dragstart',e=>{dragId=value;row.classList.add('dragging');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',value);});
    row.addEventListener('dragover',e=>{e.preventDefault();row.classList.add('drag-over');});
    row.addEventListener('dragleave',()=>row.classList.remove('drag-over'));
    row.addEventListener('drop',e=>{e.preventDefault();row.classList.remove('drag-over');if(dragId!==null)moveStream(items.indexOf(dragId),items.indexOf(value));});
    row.addEventListener('dragend',()=>{dragId=null;list.querySelectorAll('.selected-item').forEach(r=>r.classList.remove('dragging','drag-over'));});
    row.append(grip,avatar,name,choice,actions);list.appendChild(row);
  });
  document.querySelectorAll('[data-live-pick]').forEach(button=>button.setAttribute('aria-pressed',String(items.includes(button.dataset.livePick))));
  const multiview=items.length>1;
  document.getElementById('layoutControl').hidden=!multiview;
  document.getElementById('layout').disabled=!multiview;
  if(!multiview)document.getElementById('layout').value='auto';
  primary.replaceChildren();audio.replaceChildren();
  items.forEach((value,index)=>{
    for(const select of [primary,audio]){const o=document.createElement('option');o.value=String(index);o.textContent=(index+1)+' · '+streamLabel(value);select.appendChild(o);}
  });
  primary.disabled=!items.length;audio.disabled=!items.length;
  primary.value=String(Math.max(0,items.indexOf(primaryId)));
  audio.value=String(Math.max(0,items.indexOf(audioId)));
}
function addStream(value){if(!value||items.includes(value))return;items.push(value);render();}
document.querySelectorAll('[data-live-pick]').forEach(button=>{
  button.addEventListener('click',event=>{if(event.target.closest('[data-youtube-href]'))return;const value=button.dataset.livePick;if(items.includes(value))items.splice(items.indexOf(value),1);else addStream(value);render();});
  button.addEventListener('keydown',event=>{if(event.target.closest('[data-youtube-href]'))return;if(event.key==='Enter'||event.key===' '){event.preventDefault();button.click();}});
});
document.querySelectorAll('[data-library-tab]').forEach(tab=>tab.addEventListener('click',()=>{
  const history=tab.dataset.libraryTab==='history';
  document.querySelectorAll('[data-library-tab]').forEach(b=>b.setAttribute('aria-selected',String(b===tab)));
  document.getElementById('liveLibrary').hidden=history;
  document.getElementById('historyLibrary').hidden=!history;
}));
document.getElementById('displayMode').onclick=()=>{
  const gallery=document.querySelector('.live-picker-list');if(!gallery)return;
  gallery.classList.toggle('compact');document.getElementById('displayMode').textContent=gallery.classList.contains('compact')?'詳細卡片':'精簡列表';
};
audio.addEventListener('change',()=>{audioId=items[Number(audio.value)]||null;});
document.getElementById('add').onclick=()=>{const value=input.value.trim();if(!value)return;addStream(value);input.value='';input.focus();};
input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();document.getElementById('add').click();}});
document.getElementById('start').onclick=()=>{
  if(!items.length){alert('請先加入至少一個影片。');return;}
  const q=new URLSearchParams();items.forEach(v=>q.append('stream',v));
  q.set('layout',items.length===1?'auto':document.getElementById('layout').value);
  q.set('ptt',document.getElementById('pttMode').value);
  q.set('primary',String(Math.max(0,items.indexOf(primaryId))));
  q.set('audio',String(Math.max(0,items.indexOf(audioId))));
  location.href='/custom-view/session?'+q.toString();
};
render();

};
