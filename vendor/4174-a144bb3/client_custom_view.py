"""Client custom-view builder backed by the shared viewing contract."""

from __future__ import annotations

from html import escape

from client_ui_shell import client_document
from client_home import HomeStream
from shared_viewing_core import (
    PlayerSource,
    SharedViewingSession,
    ViewingLayout,
    parse_youtube_video_id,
    render_shared_viewing_session,
)


CUSTOM_CSS = r"""
.client-main:has(.custom-layout){max-width: min(1920px,100%);width:100%;padding-right:clamp(20px,3vw,48px)}
.custom-layout{display:grid;grid-template-columns:minmax(0,7fr) minmax(290px,3fr);gap:22px;align-items:start}
.custom-main{display:grid;gap:16px}.search-box{display:flex;gap:10px;padding:12px;background:var(--surface);border:1px solid var(--line);border-radius:16px}
.search-box input{flex:1}.selection-panel{position:sticky;top:78px;padding:18px;border:1px solid var(--line);border-radius:18px;background:var(--surface);box-shadow:var(--shadow)}
.selection-panel h2{margin:5px 0 14px;font-size:20px}.selected-list{display:grid;gap:8px;max-height:360px;overflow:auto;padding-right:2px}
.selected-item{display:grid;grid-template-columns:24px 30px minmax(0,1fr) auto auto;gap:8px;align-items:center;padding:10px;border:1px solid var(--line);border-radius:12px;background:#fff}
.selected-index{width:26px;height:26px;border-radius:8px;background:var(--surface-2);display:grid;place-items:center;font-size:11px;font-weight:800;color:var(--muted)}
.selected-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.selected-avatar{width:30px;height:30px;border-radius:50%;object-fit:cover;background:var(--surface-2)}.selected-channel{display:block;font-size:12px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.selected-title{display:block;font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item-actions{display:flex;gap:5px}.item-actions button{border:0;background:var(--surface-2);color:var(--text);border-radius:8px;padding:6px 8px;cursor:pointer}
.empty-selection{padding:22px 8px;text-align:center;color:var(--muted);font-size:12px;border:1px dashed var(--line);border-radius:12px}
.custom-settings{display:grid;gap:12px;margin-top:16px;padding-top:16px;border-top:1px solid var(--line)}
.controls{display:grid;gap:10px}[hidden]{display:none!important}label{display:grid;gap:6px;font-size:12px;font-weight:700;color:#5e5a54}
.start-row{display:flex;justify-content:stretch;margin-top:16px}.start-row .primary-action{width:100%}
.live-picker{padding:14px;border:1px solid var(--line);border-radius:14px;background:var(--surface)}
.live-picker-list{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;max-height:720px;overflow-y:auto;margin-top:10px}
.live-picker-item{display:flex;flex-direction:column;align-items:stretch;gap:8px;min-width:0;text-align:left;border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:7px;cursor:pointer}
.live-picker-item:hover{background:var(--surface-2)}
.live-picker-item[aria-pressed="true"]{outline:2px solid #83aabe}
.live-picker-item img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px}
.live-picker-item span{min-width:0;font-size:12px;line-height:1.35;overflow-wrap:anywhere}
@media(max-width:680px){.live-picker-list{grid-template-columns:1fr}}@media(min-width:681px) and (max-width:1150px){.live-picker-list{grid-template-columns:repeat(2,minmax(0,1fr))}}
.library-tabs{display:flex;gap:8px;margin-bottom:8px}.library-tabs button{padding:9px 15px;border:1px solid var(--line);background:var(--surface);border-radius:10px;cursor:pointer;font-weight:700}.library-tabs button[aria-selected="true"]{background:var(--surface-2);border-color:#83aabe}.library-empty{padding:24px 14px;color:var(--muted);font-size:13px}.drag-handle{border:0;background:transparent;cursor:grab;color:var(--muted);font-size:21px;touch-action:none}.selected-item.dragging{opacity:.5}.selected-item.drag-over{outline:2px solid #83aabe}.primary-choice{display:flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}.primary-choice input{accent-color:#367c9f}.selected-item.is-primary{border-color:#83aabe}.primary-tag{font-size:10px;color:#367c9f;font-weight:800}.library-display{display:flex;gap:8px;align-items:center;justify-content:space-between;margin-top:10px}.library-display button{border:1px solid var(--line);background:var(--surface);border-radius:8px;padding:5px 9px;cursor:pointer}.live-picker-list.compact .live-picker-item{flex-direction:row}.live-picker-list.compact .live-picker-item img{width:92px}.builder-note{padding:14px 16px;border-radius:14px;background:#eef6f8;color:#4f6f7b;font-size:12px;line-height:1.6}
@media(max-width:900px){.custom-layout{grid-template-columns:1fr}.selection-panel{position:static}.search-box{display:grid;grid-template-columns:1fr}}
"""

CUSTOM_JS = r"""
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
"""


def _live_picker(streams: list[HomeStream]) -> str:
    if not streams:
        return '<p class="empty-note">目前沒有可用的直播，仍可貼上影片網址。</p>'
    cards = []
    for item in streams:
        video_id = escape(item.video_id, quote=True)
        cards.append(
            f'<div class="live-picker-item" role="button" tabindex="0" data-live-pick="{video_id}" '
            f'data-channel="{escape(item.channel_title or "Hololive", quote=True)}" '
            f'data-title="{escape(item.title, quote=True)}" '
            f'data-avatar="{escape(item.avatar_url, quote=True)}" aria-pressed="false">'
            f'<div style="position:relative"><img src="https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" alt="" loading="lazy">'
            f'<span class="youtube-source-link" role="link" tabindex="0" data-youtube-href="https://www.youtube.com/watch?v={video_id}">YouTube ↗</span></div>'
            f'<span><strong>{escape(item.channel_title or "Hololive")}</strong> · {escape(item.title)}</span></div>'
        )
    return '<div class="live-picker-list">' + ''.join(cards) + '</div>'


def build_custom_view_html(error: str = "", *, live_streams: list[HomeStream] | None = None) -> str:
    live_picker_html = _live_picker(live_streams or [])
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    content = f"""
<div class="page-head"><div><h1>自訂觀看</h1><p>自己挑任意直播組合，再交給系統排版。</p></div></div>
<div class="custom-layout">
  <section class="custom-main">
    <div class="search-box">
      <input id="url" aria-label="YouTube URL 或 Video ID" placeholder="貼上 YouTube URL 或 Video ID">
      <button id="add" class="subtle-action" type="button">加入網址</button>
    </div>
    {error_html}
    <div class="builder-note">可直接點選正在直播的影片，或貼上任意 YouTube 影片網址。跨日期組合不會猜測共用 PTT。</div>
    <div class="live-picker"><span class="eyebrow">影片庫 · 點選影片加入播放設定</span>
      <div class="library-tabs" role="tablist" aria-label="影片來源">
        <button type="button" role="tab" data-library-tab="live" aria-selected="true">直播中</button>
        <button type="button" role="tab" data-library-tab="history" aria-selected="false">歷史影片</button>
      </div>
      <div id="liveLibrary" role="tabpanel"><div class="library-display"><span class="empty-note">選擇想一起觀看的直播</span><button id="displayMode" type="button">精簡列表</button></div>{live_picker_html}</div>
      <div id="historyLibrary" role="tabpanel" hidden><p class="library-empty">歷史影片搜尋功能準備中。目前可直接貼上 YouTube 影片網址加入觀看清單。</p></div>
    </div>
    
  </section>
  <aside class="selection-panel">
    <span class="eyebrow">播放設定 · 拖曳調整順序</span>
    <h2>已選 <span id="selectedCount">0</span> 個直播</h2>
    <div id="list" class="selected-list"><div class="empty-selection">還沒有選擇直播。</div></div>
    <div class="custom-settings">
      <div class="controls">
        <label id="layoutControl" hidden>版面
          <select id="layout"><option value="auto">自動</option><option value="equal">平均排列</option><option value="primary">主視角</option></select>
        </label>
        <select id="primary" hidden aria-label="主要畫面索引"></select>
        <label>主要聲音<select id="audio"></select></label>
        <label>觀看版型<select id="pttMode"><option value="live">影片＋即時 PTT 專串</option><option value="video">純影片</option></select></label>
        <span class="empty-note">即時專串不顯示搜尋；歷史 VOD 專串需使用對應日期資料，避免誤連今天的推文。</span>
      </div>
    </div>
    <div class="start-row"><button id="start" class="primary-action" type="button">開始觀看</button></div>
  </aside>
</div>
"""
    return client_document(
        title="自訂觀看",
        active="custom",
        content=content,
        extra_css=CUSTOM_CSS,
        extra_script=CUSTOM_JS,
    )


def custom_view_session_from_query(
    streams: list[str],
    *,
    layout: str,
    primary_index: int,
    audio_master_index: int,
) -> SharedViewingSession:
    ids = [parse_youtube_video_id(value) for value in streams]
    if not ids or any(video_id is None for video_id in ids):
        raise ValueError("請提供有效的 YouTube 直播或影片連結。")
    try:
        mode = ViewingLayout(layout)
    except ValueError as exc:
        raise ValueError("不支援的觀看版面。") from exc
    if mode not in {ViewingLayout.AUTO, ViewingLayout.EQUAL, ViewingLayout.PRIMARY}:
        raise ValueError("自訂觀看只支援 auto / equal / primary 版面。")
    return SharedViewingSession(
        streams=tuple(PlayerSource(video_id or "") for video_id in ids),
        layout=mode,
        primary_index=primary_index,
        audio_master_index=audio_master_index,
        ptt_context_id=None,
    )


def build_custom_view_session_html(session: SharedViewingSession, *, show_live_ptt: bool = False, ptt_worker_config: dict | None = None, ptt_alignment_notice: str = "", verified_start_times: tuple[float, ...] = (), manual_start_times: tuple[float, ...] = (), collab_poll_url: str = "", collab_label: str = "", ptt_resolver_url: str = "", translation_a: tuple[dict, ...] = (), translation_b: tuple[dict, ...] = (), translation_eligible: bool = False, translation_video_id: str = "") -> str:
    """Render the normalized session through the shared player renderer."""
    return render_shared_viewing_session(session, show_live_ptt=show_live_ptt, ptt_worker_config=ptt_worker_config, ptt_alignment_notice=ptt_alignment_notice, verified_start_times=verified_start_times, manual_start_times=manual_start_times, collab_poll_url=collab_poll_url, collab_label=collab_label, ptt_resolver_url=ptt_resolver_url, translation_a=translation_a, translation_b=translation_b, translation_eligible=translation_eligible, translation_video_id=translation_video_id)
