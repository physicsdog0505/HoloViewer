"""Shared-time multi-stream playback with a synchronized PTT timeline."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json

from frontend_multistream import CollabStream
from frontend_feed_polling import FEED_POLLING_JS
from ptt_reader_components import decorate_ptt_reader_html, replay_timeline_messages


def _timeline_messages(pushes, session_start: datetime) -> list[dict]:
    """Convert PTT pushes to offsets on one real-world session timeline."""
    groups: dict[datetime, list] = defaultdict(list)
    for push in pushes:
        groups[push.occurred_at].append(push)

    messages: list[dict] = []
    for occurred_at in sorted(groups):
        group = sorted(
            groups[occurred_at],
            key=lambda push: (
                getattr(push, "aid", ""),
                getattr(push, "floor", None)
                if getattr(push, "floor", None) is not None
                else getattr(push, "source_line", 0),
            ),
        )
        minute_offset = (occurred_at - session_start).total_seconds()
        count = len(group)
        for index, push in enumerate(group):
            floor = getattr(push, "floor", None)
            messages.append(
                {
                    "key": f"{push.article_id}:{push.source_line}",
                    "kind": push.kind,
                    "author": push.author,
                    "content": push.content,
                    "clock": push.occurred_at.strftime("%H:%M"),
                    "offset": round(minute_offset + index * 60 / count, 3),
                    "url": push.article_url,
                    "floor": floor if floor is not None else "",
                }
            )
    return messages


def build_synced_multistream_html(
    streams: list[CollabStream],
    *,
    stream_starts: list[datetime],
    pushes=(),
    relative_offset_seconds: float = 0.0,
    audio_master: int = 0,
    archived: bool = True,
    live_feed_url: str | None = None,
    live_refresh_seconds: float = 3.0,
    stream_slots: tuple[str, ...] | list[str] | None = None,
    layout_capacity: int | None = None,
) -> str:
    """Build a two-, three-, or four-slot collab surface sharing one real-world clock."""
    if len(streams) not in (2, 3, 4) or len(stream_starts) != len(streams):
        raise ValueError("synchronization requires two, three, or four streams with matching starts")
    if not 0 <= audio_master < len(streams):
        raise ValueError("audio_master must reference an existing stream")
    if any(start.tzinfo is None for start in stream_starts):
        raise ValueError("stream starts must be timezone-aware")

    capacity = int(layout_capacity or len(streams))
    if capacity not in (2, 3, 4) or capacity < len(streams):
        raise ValueError("layout_capacity must be 2, 3, or 4 and fit all streams")
    slots = tuple(stream_slots) if stream_slots is not None else tuple("abcd"[: len(streams)])
    allowed_slots = tuple("abcd"[:capacity])
    if len(slots) != len(streams) or len(set(slots)) != len(slots):
        raise ValueError("stream_slots must uniquely match the stream count")
    if any(slot not in allowed_slots for slot in slots):
        raise ValueError("stream_slots must fit within the selected layout capacity")

    session_start = min(stream_starts)
    start_offsets = [(start - session_start).total_seconds() for start in stream_starts]
    payload = json.dumps(
        [
            {
                "videoId": stream.video_id,
                "label": stream.label or f"Stream {index + 1}",
                "volume": int(stream.volume),
                "syncOffsetMs": int(stream.sync_offset_ms),
                "startOffset": round(start_offsets[index], 3),
                "slot": slots[index],
            }
            for index, stream in enumerate(streams)
        ],
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e")
    messages = json.dumps(
        (replay_timeline_messages(_timeline_messages(pushes, session_start)) if archived else _timeline_messages(pushes, session_start)), ensure_ascii=False
    ).replace("<", "\\u003c").replace(">", "\\u003e")
    session_label = json.dumps(session_start.strftime("%Y/%m/%d %H:%M:%S"))
    session_start_iso = json.dumps(session_start.isoformat())
    feed_url = json.dumps(live_feed_url or "")
    refresh_ms = max(1000, int(float(live_refresh_seconds) * 1000))
    archived_js = "true" if archived else "false"
    correction = float(relative_offset_seconds)
    body_class = f"streams-{capacity} layout-equal"
    equal_label = "2×2" if capacity == 4 else "Equal"
    focus_buttons = "".join(
        f'<button class="view-button" data-layout="focus-{slot}">Focus {slot.upper()}</button>'
        for slot in slots
    )
    carousel_button = (
        '<button id="carousel" class="view-button">輪播 10s</button><label class="view-toggle" for="carousel-seconds">間隔 <input id="carousel-seconds" type="range" min="10" max="60" step="5" value="10"> <span id="carousel-seconds-label">10 秒</span></label>'
        if capacity in (3, 4)
        else ""
    )
    audio_follow_control = (
        '<label class="view-toggle"><input id="audio-follow-focus" type="checkbox"> 聲音跟隨 Focus</label>'
        if capacity in (3, 4)
        else ""
    )

    html = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; background: #090909; color: #eee;
  font-family: -apple-system, BlinkMacSystemFont, "Noto Sans TC", sans-serif; }}
#root {{ height: 100vh; display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 6px; }}
#viewbar {{ display: flex; align-items: center; gap: 6px; padding: 5px 8px; background:#111;
  border:1px solid #242424; font-size:12px; }}
.view-button {{ border:1px solid #444; background:#202020; color:#eee; border-radius:5px;
  padding:6px 9px; cursor:pointer; white-space:nowrap; }}
.view-button.active {{ background:#f1f1f1; color:#111; font-weight:700; }}
.view-toggle {{ display:flex; align-items:center; gap:4px; padding:0 4px; color:#ddd; white-space:nowrap; }}
#fullscreen {{ margin-left:auto; }}
#syncbar {{ display: grid; grid-template-columns: auto minmax(180px, 420px) auto 1fr; gap: 8px;
  align-items: center; padding: 5px 8px; background: #111; border: 1px solid #242424; font-size: 12px; }}
#offset {{ width: 100%; }} #offset-label {{ color: #ddd; min-width: 64px; }}
#status {{ color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
#stage {{ min-height:0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:6px; }}
body.streams-2 #stage {{ grid-template-rows:auto minmax(180px,1fr); }}
body.streams-3 #stage, body.streams-4 #stage {{ grid-template-rows:minmax(0,1fr) minmax(0,1fr) minmax(120px,.45fr); }}
.card {{ min-width: 0; min-height:0; background: #111; border: 1px solid #242424; overflow: hidden; }}
body.streams-3 .card, body.streams-4 .card {{ display:flex; flex-direction:column; }}
body.streams-2 .stream-0 {{ grid-column:1; grid-row:1; }}
body.streams-2 .stream-1 {{ grid-column:2; grid-row:1; }}
body.streams-3 .slot-a, body.streams-4 .slot-a {{ grid-column:1; grid-row:1; }}
body.streams-3 .slot-b, body.streams-4 .slot-b {{ grid-column:2; grid-row:1; }}
body.streams-3 .slot-c {{ grid-column:1 / 3; grid-row:2; }}
body.streams-4 .slot-c {{ grid-column:1; grid-row:2; }}
body.streams-4 .slot-d {{ grid-column:2; grid-row:2; }}
.video-wrap {{ position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; }}
body.streams-3 .video-wrap, body.streams-4 .video-wrap {{ flex:1; min-height:0; aspect-ratio:auto; }}
.player {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.controls {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center;
  padding: 5px 8px; }}
.label {{ font-size: 12px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.audio-row {{ display: flex; align-items: center; gap: 6px; margin-top: 3px; font-size: 11px; }}
.audio-row input {{ flex: 1; min-width: 70px; }}
.volume {{ color:#aaa; width:34px; text-align:right; }}
.master {{ border:1px solid #444; background:#202020; color:#eee; border-radius:5px;
  padding:6px 8px; cursor:pointer; white-space:nowrap; }}
.master.active {{ background:#f1f1f1; color:#111; font-weight:700; }}
#chat-panel {{ grid-column:1 / 3; min-height:0; display:flex; flex-direction:column;
  border:1px solid #242424; background:#0d0d0d; }}
body.streams-2 #chat-panel {{ grid-row:2; }}
body.streams-3 #chat-panel, body.streams-4 #chat-panel {{ grid-row:3; }}
#chat-head {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; padding:5px 8px; background:#151515;
  border-bottom:1px solid #242424; font-size:12px; }}
#chat {{ --chat-font-size:14px; min-height:0; flex:1; overflow-y:auto; padding:3px 7px 12px; }}
.chat-options {{ display:flex; align-items:center; flex-wrap:wrap; gap:8px; }}
.chat-font-control {{ display:flex; align-items:center; gap:5px; white-space:nowrap; }}
#chat-font-size {{ width:95px; accent-color:#7db2ff; }}
#chat-font-label {{ min-width:32px; color:#eee; }}
.row {{ display:grid; grid-template-columns:1.2em 6.4em 1fr; gap:5px; padding:3px 1px;
  border-bottom:1px solid #181818; font-family:Menlo, Monaco, monospace; font-size:var(--chat-font-size,14px); line-height:1.35; }}
.kind {{ font-weight:800; text-align:center; }} .push {{ color:#eee; }} .boo {{ color:#ff4b4b; }} .arrow {{ color:#ff3030; }}
.clock {{ color:#999; font-size:.78em; padding-top:.2em; white-space:nowrap; }}
.author {{ color:#ffff00; font-weight:700; margin-right:.4em; }} .content {{ color:#a9a900; white-space:pre-wrap; }}
.future {{ display:none; }} #waiting {{ color:#888; text-align:center; padding:18px 8px; font-size:12px; }}
body.streams-2.layout-focus-a #stage, body.streams-2.layout-focus-b #stage {{
  grid-template-columns:minmax(0,2.25fr) minmax(300px,.9fr); grid-template-rows:auto minmax(0,1fr);
}}
body.streams-2.layout-focus-a .stream-0, body.streams-2.layout-focus-b .stream-1 {{
  grid-column:1; grid-row:1 / 3; display:flex; flex-direction:column;
}}
body.streams-2.layout-focus-a .stream-1, body.streams-2.layout-focus-b .stream-0 {{ grid-column:2; grid-row:1; }}
body.streams-2.layout-focus-a #chat-panel, body.streams-2.layout-focus-b #chat-panel {{ grid-column:2; grid-row:2; }}
body.streams-2.layout-focus-a .stream-0 .video-wrap, body.streams-2.layout-focus-b .stream-1 .video-wrap {{
  flex:1; min-height:0; aspect-ratio:auto;
}}
body.immersive #viewbar, body.immersive .controls, body.immersive #syncbar {{ display:none; }}
body.immersive #root {{ grid-template-rows:minmax(0,1fr); gap:0; }}
body.immersive #stage {{ gap:4px; }}
body.immersive .card {{ border-color:#151515; }}
@media (max-width: 760px) {{
  #root {{ height:auto; grid-template-rows:auto auto auto; }}
  #stage, body.streams-2.layout-focus-a #stage, body.streams-2.layout-focus-b #stage {{
    grid-template-columns:1fr; grid-template-rows:none;
  }}
  .card, body.streams-2.layout-focus-a .card, body.streams-2.layout-focus-b .card {{
    grid-column:1 !important; grid-row:auto !important; display:block !important;
  }}
  #chat-panel, body.streams-2.layout-focus-a #chat-panel, body.streams-2.layout-focus-b #chat-panel {{
    grid-column:1; grid-row:auto;
  }}
  .video-wrap, body.streams-2.layout-focus-a .stream-0 .video-wrap,
  body.streams-2.layout-focus-b .stream-1 .video-wrap {{ aspect-ratio:16/9; }}
  #syncbar {{ grid-template-columns:auto 1fr auto; }} #status {{ grid-column:1/-1; }}
}}
</style></head><body class="{body_class}"><div id="root">
<div id="viewbar">
  <button class="view-button active" data-layout="equal">{equal_label}</button>{focus_buttons}{carousel_button}{audio_follow_control}
  <button id="fullscreen" class="view-button">沉浸全螢幕</button>
</div>
<div id="syncbar"><strong>同步校正 B 相對 A</strong><input id="offset" type="range" min="-10" max="10" step="0.1" value="{correction}">
<span id="offset-label">{correction:+.1f}s</span><span id="status">載入播放器…</span></div>
<div id="stage">
<section id="chat-panel"><div id="chat-head"><span id="count">PTT 推文 0 則</span><div class="chat-options"><label class="chat-font-control" for="chat-font-size">字體 <input id="chat-font-size" type="range" min="12" max="26" step="2" value="14" aria-label="PTT 推文字體大小"><span id="chat-font-label">14px</span></label><label><input id="follow" type="checkbox" checked> 自動跟隨</label></div></div>
<div id="chat"><div id="waiting">等待播放至第一則推文時間</div></div></section>
</div>
</div><script>
const streams = {payload};
const layoutCapacity = {capacity};
let messages = {messages};
const sessionStart = {session_label};
const sessionStartIso = {session_start_iso};
const archived = {archived_js};
const liveFeedUrl = {feed_url};
const liveRefreshMs = {refresh_ms};
let audioMaster = {audio_master};
let clockMaster = 0;
let correction = {correction};
let guardUntil = 0;
const players = Array(streams.length).fill(null);
const stage = document.getElementById('stage');
const statusBox = document.getElementById('status');
const chat = document.getElementById('chat');
const waiting = document.getElementById('waiting');
const count = document.getElementById('count');
const follow = document.getElementById('follow');
const chatPanel = document.getElementById('chat-panel');
const chatFontSize = document.getElementById('chat-font-size');
const chatFontLabel = document.getElementById('chat-font-label');
if (chatFontSize) chatFontSize.oninput = () => {{
  chat.style.setProperty('--chat-font-size', chatFontSize.value + 'px');
  chatFontLabel.textContent = chatFontSize.value + 'px';
}};
const focusSlots = streams.map(stream => stream.slot);
const carouselButton = document.getElementById('carousel');
const carouselSeconds = document.getElementById('carousel-seconds');
const carouselSecondsLabel = document.getElementById('carousel-seconds-label');
const audioFollowFocus = document.getElementById('audio-follow-focus');
let carouselTimer = null;
let carouselIntervalMs = 10000;
let carouselIndex = 0;
let currentLayout = 'equal';
let rows = [];
let shown = 0;

function clampVolume(value) {{ return Math.max(0, Math.min(100, Number(value) || 0)); }}
function fineOffset(index) {{ return (Number(streams[index].syncOffsetMs)||0)/1000 + (streams[index].slot === 'b' ? correction : 0); }}
function worldSeconds(index) {{
  const p = players[index];
  if (!p || typeof p.getCurrentTime !== 'function') return 0;
  return streams[index].startOffset + (p.getCurrentTime() || 0) - fineOffset(index);
}}
function targetSeconds(index, world) {{ return Math.max(0, world - streams[index].startOffset + fineOffset(index)); }}
function formatTime(seconds) {{
  seconds = Math.max(0, Math.floor(seconds || 0));
  const h=Math.floor(seconds/3600), m=Math.floor((seconds%3600)/60), s=seconds%60;
  return (h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0');
}}
function focusIndexForMode(mode) {{
  if (!mode || !mode.startsWith('focus-')) return -1;
  const slot = mode.slice(-1);
  return streams.findIndex(stream => stream.slot === slot);
}}
function resetSmallGroupGrid() {{
  if (layoutCapacity !== 3 && layoutCapacity !== 4) return;
  stage.style.gridTemplateColumns = '';
  stage.style.gridTemplateRows = '';
  document.querySelectorAll('.card').forEach(card => {{
    card.style.gridColumn = '';
    card.style.gridRow = '';
  }});
  chatPanel.style.gridColumn = '';
  chatPanel.style.gridRow = '';
}}
function applySmallGroupFocus(mode) {{
  if ((layoutCapacity !== 3 && layoutCapacity !== 4) || !mode.startsWith('focus-')) return;
  const focusIndex = focusIndexForMode(mode);
  if (focusIndex < 0) return;
  const cards = Array.from(document.querySelectorAll('.card'));
  const sideIndexes = Array.from({{length: streams.length}}, (_, index) => index)
    .filter(index => index !== focusIndex);
  const chatRow = sideIndexes.length + 1;
  stage.style.gridTemplateColumns = 'minmax(0,2.25fr) minmax(300px,.9fr)';
  stage.style.gridTemplateRows = `repeat(${{sideIndexes.length}},minmax(0,1fr)) minmax(120px,.9fr)`;
  cards[focusIndex].style.gridColumn = '1';
  cards[focusIndex].style.gridRow = `1 / ${{chatRow + 1}}`;
  sideIndexes.forEach((index, order) => {{
    cards[index].style.gridColumn = '2';
    cards[index].style.gridRow = String(order + 1);
  }});
  chatPanel.style.gridColumn = '2';
  chatPanel.style.gridRow = String(chatRow);
}}
function maybeFollowFocusAudio(mode) {{
  if (!audioFollowFocus || !audioFollowFocus.checked) return;
  const focusIndex = focusIndexForMode(mode);
  if (focusIndex < 0) return;
  audioMaster = focusIndex;
  applyAudioState();
}}
function stopCarousel() {{
  if (carouselTimer) clearInterval(carouselTimer);
  carouselTimer = null;
  if (carouselButton) {{
    carouselButton.classList.remove('active');
    carouselButton.textContent = '輪播 ' + (carouselIntervalMs/1000) + 's';
  }}
}}
function startCarouselTimer() {{
  if (carouselTimer) clearInterval(carouselTimer);
  carouselTimer = setInterval(() => {{
    carouselIndex = (carouselIndex + 1) % focusSlots.length;
    setLayout('focus-' + focusSlots[carouselIndex], true);
  }}, carouselIntervalMs);
}}
if (carouselSeconds) {{
  carouselSeconds.oninput = () => {{
    carouselIntervalMs = Number(carouselSeconds.value) * 1000;
    carouselSecondsLabel.textContent = carouselSeconds.value + ' 秒';
    if (carouselTimer) startCarouselTimer();
    else if (carouselButton) carouselButton.textContent = '輪播 ' + carouselSeconds.value + 's';
  }};
}}
function setLayout(mode, fromCarousel=false) {{
  if (!fromCarousel) stopCarousel();
  currentLayout = mode;
  document.body.classList.remove('layout-equal','layout-focus-a','layout-focus-b','layout-focus-c','layout-focus-d');
  document.body.classList.add('layout-'+mode);
  resetSmallGroupGrid();
  if ((layoutCapacity === 3 || layoutCapacity === 4) && mode.startsWith('focus-')) applySmallGroupFocus(mode);
  maybeFollowFocusAudio(mode);
  document.querySelectorAll('[data-layout]').forEach(button =>
    button.classList.toggle('active', button.dataset.layout === mode));
}}
document.querySelectorAll('[data-layout]').forEach(button => {{
  button.onclick = () => setLayout(button.dataset.layout);
}});
if (audioFollowFocus) {{
  audioFollowFocus.onchange = () => {{
    if (audioFollowFocus.checked) maybeFollowFocusAudio(currentLayout);
  }};
}}
if (carouselButton) {{
  carouselButton.onclick = () => {{
    if (carouselTimer) {{ stopCarousel(); return; }}
    carouselIndex = 0;
    if (audioFollowFocus) audioFollowFocus.checked = true;
    carouselButton.classList.add('active');
    carouselButton.textContent = '停止輪播';
    setLayout('focus-' + focusSlots[carouselIndex], true);
    startCarouselTimer();
  }};
}}
async function enterFullscreen() {{
  if (!document.documentElement.requestFullscreen) {{ statusBox.textContent='此瀏覽器環境不支援沉浸全螢幕'; return; }}
  try {{ await document.documentElement.requestFullscreen(); }}
  catch (error) {{ statusBox.textContent='瀏覽器拒絕全螢幕；可先點頁面後再試一次'; }}
}}
document.getElementById('fullscreen').onclick = enterFullscreen;
document.addEventListener('fullscreenchange', () => {{ document.body.classList.toggle('immersive', Boolean(document.fullscreenElement)); }});
function applyAudioState() {{
  players.forEach((player,index)=>{{ if(!player||typeof player.setVolume!=='function') return;
    player.setVolume(clampVolume(streams[index].volume)); if(index===audioMaster) player.unMute(); else player.mute(); }});
  document.querySelectorAll('.master').forEach((button,index)=>{{ const active=index===audioMaster;
    button.classList.toggle('active',active); button.textContent=active?'主聲源 🔊':'切換聲音'; }});
}}
function syncFollowers(master, play) {{
  if (!archived) {{
    guardUntil = Date.now()+800;
    players.forEach((p,i)=>{{ if(i!==master&&p) play?p.playVideo():p.pauseVideo(); }}); return;
  }}
  const world = worldSeconds(master); guardUntil = Date.now()+1000;
  players.forEach((p,i)=>{{ if(i===master||!p) return; const target=targetSeconds(i,world);
    if(Math.abs((p.getCurrentTime()||0)-target)>.35) p.seekTo(target,true); play?p.playVideo():p.pauseVideo(); }});
}}
function buildCard(stream,index) {{
  const card=document.createElement('section');
  card.className='card stream-'+index+' slot-'+stream.slot;
  card.dataset.streamSlot=stream.slot;
  card.innerHTML=`<div class="video-wrap"><div id="player-${{index}}" class="player"></div></div><div class="controls"><div><div class="label"></div><div class="audio-row"><span>音量</span><input class="slider" type="range" min="0" max="100" step="1"><span class="volume"></span></div></div><button class="master" type="button"></button></div>`;
  card.querySelector('.label').textContent=stream.label; const slider=card.querySelector('.slider'); const volume=card.querySelector('.volume');
  slider.value=stream.volume; volume.textContent=`${{stream.volume}}%`; slider.oninput=e=>{{stream.volume=clampVolume(e.target.value); volume.textContent=`${{stream.volume}}%`; if(players[index]) players[index].setVolume(stream.volume);}};
  card.querySelector('.master').onclick=()=>{{audioMaster=index;applyAudioState();}}; return card;
}}
streams.forEach((stream,index)=>stage.insertBefore(buildCard(stream,index), chatPanel));
function rowFor(message) {{
  const row=document.createElement('div'); row.className='row future';
  const kind=document.createElement('div'); kind.className='kind '+(message.kind==='推'?'push':message.kind==='嘘'||message.kind==='噓'?'boo':'arrow'); kind.textContent=message.kind;
  const clock=document.createElement('div'); clock.className='clock'; clock.textContent=message.floor?(message.clock+' · '+message.floor+'樓'):message.clock;
  const body=document.createElement('div'); const author=document.createElement('span'); author.className='author'; author.textContent=message.author+':'; const content=document.createElement('span'); content.className='content'; content.textContent=message.content;
  body.append(author,content); row.append(kind,clock,body); row.title='雙擊開啟 PTT 原文'; row.ondblclick=()=>window.open(message.url,'_blank','noopener'); return row;
}}
function upperBound(seconds) {{ let low=0,high=messages.length; while(low<high){{const mid=(low+high)>>1;if(messages[mid].offset<=seconds)low=mid+1;else high=mid;}}return low; }}
function updateChat(world) {{
  const next=pttReplayUpperBound(messages,world); if(next!==shown){{if(next>shown)for(let i=shown;i<next;i++)rows[i].classList.remove('future');else for(let i=next;i<shown;i++)rows[i].classList.add('future');shown=next;waiting.style.display=shown?'none':'block';count.textContent=`PTT 推文 ${{shown}} / ${{messages.length}} 則`;if(follow.checked&&shown)rows[shown-1].scrollIntoView({{block:'end'}});}}
}}
function installMessages(nextMessages) {{
  const previousScroll=chat.scrollTop; messages=Array.isArray(nextMessages)?nextMessages:[]; chat.innerHTML=''; chat.appendChild(waiting); rows=[]; shown=0;
  messages.forEach(m=>{{const row=rowFor(m);rows.push(row);chat.appendChild(row);}});
  const master=players[clockMaster]; updateChat(master?worldSeconds(clockMaster):0); if(!follow.checked) chat.scrollTop=previousScroll;
}}
installMessages(messages);
{FEED_POLLING_JS}
if(!archived && liveFeedUrl) startLivePushPolling(liveFeedUrl, sessionStartIso, liveRefreshMs, messages, installMessages);
document.getElementById('offset').oninput=e=>{{correction=Number(e.target.value)||0;document.getElementById('offset-label').textContent=(correction>=0?'+':'')+correction.toFixed(1)+'s';if(archived)syncFollowers(clockMaster,players[clockMaster]?.getPlayerState()===YT.PlayerState.PLAYING);}};
window.onYouTubeIframeAPIReady=function(){{let ready=0;streams.forEach((stream,index)=>{{players[index]=new YT.Player(`player-${{index}}`,{{videoId:stream.videoId,width:'100%',height:'100%',playerVars:{{playsinline:1,rel:0,controls:1}},events:{{onReady:()=>{{ready++;applyAudioState();if(ready===streams.length)statusBox.textContent=archived?'歷史連動已就緒 · 播放任一畫面即可同步':'即時連動已就緒 · PTT 每 '+Math.round(liveRefreshMs/1000)+' 秒更新';}},onStateChange:event=>{{if(Date.now()<guardUntil)return;if(event.data===YT.PlayerState.PLAYING){{clockMaster=index;syncFollowers(index,true);}}else if(event.data===YT.PlayerState.PAUSED){{clockMaster=index;syncFollowers(index,false);}}}}}}}});}});setInterval(()=>{{const master=players[clockMaster];if(!master)return;const world=worldSeconds(clockMaster);updateChat(world);if(archived&&master.getPlayerState()===YT.PlayerState.PLAYING){{players.forEach((p,i)=>{{if(i===clockMaster||!p)return;const target=targetSeconds(i,world);if(Math.abs((p.getCurrentTime()||0)-target)>0.8){{guardUntil=Date.now()+800;p.seekTo(target,true);}}}});}}statusBox.textContent=(archived?'共用時間 ':'即時 ')+formatTime(world)+' · 基準 '+streams[clockMaster].label+' · session '+sessionStart;}},500);}};
const api=document.createElement('script');api.src='https://www.youtube.com/iframe_api';document.head.appendChild(api);
</script></body></html>"""
    return decorate_ptt_reader_html(html, feed_id="chat", default_font=14)
