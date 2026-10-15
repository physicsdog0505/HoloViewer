"""Standalone Client PTT 今日專串 reader."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from frontend_chat import _message
from html import escape
from pathlib import Path

from client_runtime import client_runtime_root
from client_ui_shell import client_document
from frontend_chat import build_chat_html
from frontend_config import database_paths
from frontend_db import FrontendPush, merged_pushes_for_window
from frontend_time import TAIPEI


PTT_CSS = r"""
.ptt-shell{max-width:860px;margin:0 auto}
.ptt-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:12px}
.ptt-meta{color:var(--muted);font-size:12px}
.ptt-actions{display:flex;gap:8px;flex-wrap:wrap}
.ptt-reader{border:1px solid var(--line);border-radius:18px;overflow:hidden;background:#080808;box-shadow:var(--shadow)}
.ptt-reader iframe{display:block;width:100%;height:calc(100vh - 185px);min-height:560px;border:0}
.ptt-empty{padding:52px 24px;text-align:center;color:#8f9498;background:#101010;min-height:420px;display:grid;place-items:center}
@media(max-width:760px){.ptt-toolbar{align-items:flex-start;flex-direction:column}.ptt-reader iframe{height:calc(100vh - 205px);min-height:480px}}
"""


def load_today_pushes(
    selected: date | None = None,
    *,
    collector_path: str | Path | None = None,
    web_path: str | Path | None = None,
) -> tuple[date, list[FrontendPush]]:
    """Load one Taiwan calendar day through the existing read-only merge path."""

    selected_day = selected or datetime.now(TAIPEI).date()
    default_collector, default_web = database_paths(root=client_runtime_root())
    collector = Path(collector_path) if collector_path is not None else default_collector
    web = Path(web_path) if web_path is not None else default_web
    # A bounded day query avoids scanning and window-sorting every historical
    # push on each initial page request. Preserve Taiwan-date semantics at
    # the exclusive next-midnight boundary.
    start = datetime.combine(selected_day, datetime.min.time(), tzinfo=TAIPEI)
    end = start + timedelta(days=1)
    pushes = merged_pushes_for_window(collector, web, start, end)
    return selected_day, [push for push in pushes if push.occurred_at.astimezone(TAIPEI).date() == selected_day]



def today_pushes_payload(
    selected: date, pushes: list[FrontendPush], *, after_key: str = ""
) -> dict:
    """Return a bounded page after an exact push key, never silently skipping gaps."""
    rows = [_message(p) for p in pushes]
    if after_key:
        # Scan backwards because the live reader normally requests the newest row.
        index = next((i for i in range(len(rows) - 1, -1, -1)
                      if rows[i]["key"] == after_key), -1)
        if index < 0:
            return {
                "date": selected.isoformat(), "messages": [],
                "next_key": after_key, "has_more": False, "history_gap": True,
            }
        pending = rows[index + 1:]
    else:
        # Initial empty-reader bootstrap shows recent retained rows, not an
        # unbounded dump from the beginning of the Taiwan day.
        pending = rows[-300:]
    page = pending[:300]
    return {
        "date": selected.isoformat(), "messages": page,
        "next_key": page[-1]["key"] if page else after_key,
        "has_more": len(pending) > len(page), "history_gap": False,
    }


def build_ptt_today_focus_html(pushes: list[FrontendPush], selected: date, *, embedded: bool = False) -> str:
    """Render the existing safe PTT chat renderer as a full-viewport Focus page."""

    html = build_chat_html(
        pushes,
        font_size=16,
        auto_follow=True,
        animate_new=False,
        message_delay_ms=200,
        theme="ptt",
        storage_key=f"client-ptt-today-{selected.isoformat()}",
    )
    focus_css = """
#focus-exit{position:fixed;z-index:20;right:12px;top:10px;padding:6px 9px;border:1px solid #444;
border-radius:999px;background:rgba(20,20,20,.78);color:#aaa;text-decoration:none;font:11px -apple-system,BlinkMacSystemFont,"Noto Sans TC",sans-serif;
opacity:.45;transition:opacity .15s ease}
#focus-exit:hover,#focus-exit:focus-visible{opacity:1;color:#fff}
#chat{padding-top:34px}
"""
    floor_css = """
body.ptt-floor-hidden .row{grid-template-columns:1.3em 4.1em minmax(0,1fr)}
body.ptt-floor-hidden .floor{display:none}
#ptt-floor-toggle{position:fixed;z-index:21;right:88px;top:10px;padding:6px 8px;
background:rgba(20,20,20,.8);color:#ccc;border:1px solid #444;border-radius:9px;
font:11px -apple-system,BlinkMacSystemFont,"Noto Sans TC",sans-serif}
"""
    html = html.replace("</style>", focus_css + floor_css + "</style>", 1)
    controls = '' if embedded else '<label id="ptt-floor-toggle"><input id="ptt-show-floor" type="checkbox" checked> 樓數</label><a id="focus-exit" href="/ptt-today">退出專注</a>'
    html = html.replace(
        '<body><div id="chat">',
        '<body>' + controls + '<div id="chat">',
        1,
    )
    if embedded:
        html = html.replace(
            "</style>",
            "#chat{padding-top:0!important}.row{font-size:var(--embedded-ptt-font,16px)!important}</style>",
            1,
        )
        embedded_font_script = r"""
<script>
(function(){
 function applyFloor(show){
  document.body.classList.toggle('ptt-floor-hidden',!show);
  try{localStorage.setItem('holoviewer-ptt-show-floor',String(Boolean(show)));}catch(_){}
 }
 let initialFloor=true;
 try{initialFloor=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';}catch(_){}
 applyFloor(initialFloor);
 window.addEventListener('message',event=>{
  if(event.source!==window.parent)return;
  const data=event.data||{};
  if(data.type==='holoviewer:ptt-font-size'){
   const size=Math.max(12,Math.min(26,Number(data.size)||16));
   document.documentElement.style.setProperty('--embedded-ptt-font',size+'px');
  }else if(data.type==='holoviewer:ptt-show-floor'){
   applyFloor(Boolean(data.show));
  }
 });
})();
</script>
"""
        html = html.replace("</body>", embedded_font_script + "</body>", 1)
    # Refresh only the PTT reader's DOM: never reload the hosting YouTube player.
    # The endpoint uses the same read-only merged SQLite path as initial render.
    floor_script = r"""
<script>
(function(){
 const checkbox=document.getElementById('ptt-show-floor');
 if(!checkbox)return;
 let show=true;
 try{show=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';}catch(_){}
 checkbox.checked=show;
 document.body.classList.toggle('ptt-floor-hidden',!show);
 checkbox.addEventListener('change',()=>{
  document.body.classList.toggle('ptt-floor-hidden',!checkbox.checked);
  try{localStorage.setItem('holoviewer-ptt-show-floor',String(checkbox.checked));}catch(_){}
 });
})();
</script>
"""
    html = html.replace("</body>", floor_script + "</body>", 1)
    # Focus iframe follows the latest push by default, within its own scroll
    # container. Never scroll the enclosing multiview document or iframe.
    initial_bottom_script = r"""
<script>
(function(){
 const chat=document.getElementById('chat');
 if(!chat)return;
 let following=true,programmatic=false,settle=0;
 function atBottom(){return chat.scrollHeight-chat.scrollTop-chat.clientHeight<48;}
 function toLatest(force=false){
  if(!force&&!following)return;
  programmatic=true;
  chat.scrollTop=chat.scrollHeight;
  if(settle)clearTimeout(settle);
  settle=setTimeout(()=>{programmatic=false;},180);
 }
 window.__holoPTTFollowLatest={
  get following(){return following;},
  toLatest(){toLatest(true);},
  setFollowing(value){following=Boolean(value);if(following)toLatest(true);}
 };
 chat.addEventListener('wheel',event=>{if(event.deltaY<0)following=false;else if(event.deltaY>0&&atBottom())following=true;},{passive:true});
 chat.addEventListener('scroll',()=>{
  if(programmatic)return;
  if(atBottom())following=true;
  else following=false;
 },{passive:true});
 requestAnimationFrame(()=>requestAnimationFrame(()=>toLatest(true)));
 window.addEventListener('load',()=>toLatest(true),{once:true});
 window.addEventListener('pageshow',()=>toLatest(true));
 if(typeof ResizeObserver==='function'){
  const observer=new ResizeObserver(()=>toLatest());
  observer.observe(chat);
  if(chat.parentElement)observer.observe(chat.parentElement);
 }
 if(typeof MutationObserver==='function'){
  const observer=new MutationObserver(()=>toLatest());
  observer.observe(chat,{childList:true,subtree:true});
 }
})();
</script>
"""
    html = html.replace("</body>", initial_bottom_script + "</body>", 1)

    live_script = r"""
<script>
(function(){
 const seen=new Set(messages.map(m=>m.key));
 let cursor=messages.length?messages[messages.length-1].key:'';
 let gapWarningShown=false;
 let busy=false,closed=false;
 async function refreshPtt(){
  if(closed||busy||document.hidden)return;
  busy=true;
  try{
   const query=cursor?'?after='+encodeURIComponent(cursor):'';
   const response=await fetch('/api/ptt/today'+query,{cache:'no-store',credentials:'same-origin'});
   if(!response.ok)throw new Error('PTT HTTP '+response.status);
   const result=await response.json();
   if(!result||!Array.isArray(result.messages)||result.messages.length>300)
    throw new Error('PTT invalid response');
   if(result.date!==readerDate){
    // Switch only this reader, never the hosting YouTube player.
    if(window.parent!==window){
     window.parent.postMessage({type:'holoviewer-ptt-rollover',date:result.date},'*');
    }
    // This navigation stays in the PTT iframe even inside Custom Viewing.
    window.location.replace('/ptt-today?focus=1'+(new URLSearchParams(location.search).get('embed')==='1'?'&embed=1':''));
    closed=true;clearInterval(timer);
    return;
   }
   if(result.history_gap&&!gapWarningShown){
    gapWarningShown=true;
    const warning=document.createElement('div');
    warning.className='ptt-history-gap';
    warning.textContent='PTT 更新出現歷史缺口，請重新載入專串核對。';
    chat.prepend(warning);
   }
   if(result.history_gap)return;
   const followController=window.__holoPTTFollowLatest;
   const nearBottom=followController?followController.following:(chat.scrollHeight-chat.scrollTop-chat.clientHeight<48);
   const previousScroll=chat.scrollTop;
   const empty=chat.querySelector('#empty');
   let added=0;
   for(const m of result.messages){
    if(!m||typeof m.key!=='string'||seen.has(m.key))continue;
    if(typeof m.author!=='string'||typeof m.content!=='string'||typeof m.kind!=='string')continue;
    seen.add(m.key);
    messages.push(m);
    if(empty)empty.remove();
    chat.appendChild(makeRow(m,false));
    added++;
   }
   if(typeof result.next_key==='string'&&result.next_key)cursor=result.next_key;
   if(window.parent!==window){
    window.parent.postMessage({type:'holoviewer-ptt-count',date:readerDate,count:messages.length},'*');
   }
   if(added){
    if(autoFollow&&nearBottom){
     chat.scrollTop=chat.scrollHeight;
     followController?.toLatest();
     save(messages[messages.length-1]);
    }else chat.scrollTop=previousScroll;
   }
  }catch(_error){
   // Keep the last successfully rendered rows; retry next interval.
  }finally{busy=false;}
 }
 const timer=setInterval(refreshPtt,10000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshPtt();});
 window.addEventListener('pagehide',()=>{closed=true;clearInterval(timer);},{once:true});
})();
</script>
"""
    if selected == datetime.now(TAIPEI).date():
        live_script = live_script.replace(
            " const seen=new Set(",
            f" const readerDate='{selected.isoformat()}';\n const seen=new Set(",
            1,
        )
        html = html.replace("</body>", live_script + "</body>", 1)
    return html


def build_ptt_today_page_html(pushes: list[FrontendPush], selected: date) -> str:
    """Render normal Client chrome around the safe PTT-only reader."""

    chat_html = build_ptt_today_focus_html(pushes, selected)
    srcdoc = escape(chat_html, quote=True)
    # Keep reader mounted even when initially empty; later pushes must appear
    # without requiring host/player navigation.
    reader = f'<iframe title="PTT 今日專串" srcdoc="{srcdoc}"></iframe>'
    content = f"""
<div class="ptt-shell">
  <div class="page-head">
    <div><h1>PTT 今日專串</h1></div>
  </div>
  <div class="ptt-toolbar">
    <div class="ptt-meta" id="ptt-today-meta">{selected:%Y/%m/%d} · {len(pushes)} 則推文 · 純 PTT 閱讀</div>
    <div class="ptt-actions">
      <a class="subtle-action" href="/ptt-today" aria-label="重新整理今日專串">↻ 重新整理</a>
      <a class="subtle-action" href="/ptt-today?focus=1" aria-label="進入專注模式">⛶ 專注模式</a>
    </div>
  </div>
  <section class="ptt-reader">{reader}</section>
</div>
<script>
(function(){{
 const frame=document.querySelector('.ptt-reader iframe');
 const meta=document.getElementById('ptt-today-meta');
 let day='{selected.isoformat()}';
 window.addEventListener('message',event=>{{
  if(!frame||event.source!==frame.contentWindow||!event.data)return;
  const data=event.data;
  if(data.type==='holoviewer-ptt-rollover'&&/^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(data.date)&&data.date!==day){{
   day=data.date;
   if(meta)meta.textContent=day.replaceAll('-','/')+' · 取得新日期推文中 · 純 PTT 閱讀';
   frame.removeAttribute('srcdoc');
   frame.src='/ptt-today?focus=1';
  }}else if(data.type==='holoviewer-ptt-count'&&data.date===day&&Number.isSafeInteger(data.count)){{
   if(meta)meta.textContent=day.replaceAll('-','/')+' · '+data.count+' 則推文 · 純 PTT 閱讀';
  }}
 }});
}})();
</script>
"""
    return client_document(
        title="PTT 今日專串",
        active="ptt",
        content=content,
        extra_css=PTT_CSS,
        top_status=f"{len(pushes)} 則推文",
    )
