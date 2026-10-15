"""Shared viewing contracts for Client-facing player experiences.

This module is intentionally UI-framework agnostic.  It centralizes session input
normalization and the adapter into the already-verified Watchalong renderer so
Client Watchalong, 自訂觀看, and later 多人連動 can share one contract without
copying timing/player logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from html import escape
from typing import Sequence

from client_ui_shell import client_document
from frontend_time import youtube_video_id
from frontend_watchalong import build_watchalong_html


class ViewingLayout(str, Enum):
    COMPARE = "compare"
    FOCUS = "focus"
    AUTO = "auto"
    EQUAL = "equal"
    PRIMARY = "primary"


@dataclass(frozen=True, slots=True)
class PlayerSource:
    """One playable source in a shared viewing session."""

    video_id: str
    label: str = ""

    def __post_init__(self) -> None:
        if not self.video_id.strip():
            raise ValueError("video_id must not be empty")


@dataclass(frozen=True, slots=True)
class SharedViewingSession:
    """Generic multi-player state shared by custom and known-group viewing."""

    streams: tuple[PlayerSource, ...]
    layout: ViewingLayout = ViewingLayout.AUTO
    primary_index: int = 0
    audio_master_index: int = 0
    ptt_context_id: str | None = None

    def __post_init__(self) -> None:
        if not self.streams:
            raise ValueError("shared viewing session requires at least one stream")
        if not 0 <= self.primary_index < len(self.streams):
            raise ValueError("primary_index must reference an existing stream")
        if not 0 <= self.audio_master_index < len(self.streams):
            raise ValueError("audio_master_index must reference an existing stream")


@dataclass(frozen=True, slots=True)
class WatchalongSession:
    """Normalized input contract for one Watchalong session."""

    master: PlayerSource
    sources: tuple[PlayerSource, ...]
    episode_master_starts: tuple[float, ...] = ()
    initial_master_seconds: float = 0.0
    initial_source_seconds: float = 0.0
    initial_correction_seconds: float = 0.0
    archive_auto_lock: bool = False
    live_queue_standby: bool = False
    telemetry_endpoint: str = ""
    telemetry_token: str = ""
    telemetry_session_id: str = ""

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("Watchalong session requires at least one source")
        if self.initial_master_seconds < 0 or self.initial_source_seconds < 0:
            raise ValueError("initial player positions must be non-negative")
        if any(value < 0 for value in self.episode_master_starts):
            raise ValueError("episode master starts must be non-negative")


def parse_youtube_video_id(value: str) -> str | None:
    """Accept a normal YouTube URL or a bare YouTube video id without network I/O."""

    candidate = youtube_video_id(value)
    if candidate:
        return candidate
    stripped = str(value or "").strip()
    if 6 <= len(stripped) <= 20 and all(ch.isalnum() or ch in "_-" for ch in stripped):
        return stripped
    return None


def watchalong_session_from_inputs(
    master: str,
    sources: Sequence[str],
    *,
    episode_master_starts: Sequence[float] = (),
    archive_auto_lock: bool = False,
    live_queue_standby: bool = False,
    telemetry_endpoint: str = "",
    telemetry_token: str = "",
    telemetry_session_id: str = "",
) -> WatchalongSession:
    """Normalize user/client values into one reusable Watchalong contract."""

    master_id = parse_youtube_video_id(master)
    source_values = tuple(sources)
    source_ids = tuple(
        video_id
        for value in source_values
        if (video_id := parse_youtube_video_id(value)) is not None
    )
    if not master_id:
        raise ValueError("Hololive 主影片無法辨識，請確認 YouTube URL 或 Video ID。")
    if not source_ids:
        raise ValueError("同時視聽片源無法辨識，請提供有效的 YouTube URL 或 Video ID。")
    if len(source_ids) != len(source_values):
        raise ValueError("其中一個同時視聽片源無法辨識，請確認 YouTube URL 或 Video ID。")
    return WatchalongSession(
        master=PlayerSource(master_id, "Hololive"),
        sources=tuple(PlayerSource(video_id, f"Source {index + 1}") for index, video_id in enumerate(source_ids)),
        episode_master_starts=tuple(float(value) for value in episode_master_starts),
        archive_auto_lock=archive_auto_lock,
        live_queue_standby=live_queue_standby,
        telemetry_endpoint=telemetry_endpoint,
        telemetry_token=telemetry_token,
        telemetry_session_id=telemetry_session_id,
    )


def render_watchalong_session(session: WatchalongSession) -> str:
    """Render through the existing verified Watchalong implementation."""

    source_ids = [source.video_id for source in session.sources]
    html = build_watchalong_html(
        master_video_id=session.master.video_id,
        source_video_id=source_ids[0],
        source_video_ids=source_ids,
        episode_master_starts=session.episode_master_starts,
        initial_master_seconds=session.initial_master_seconds,
        initial_source_seconds=session.initial_source_seconds,
        initial_correction_seconds=session.initial_correction_seconds,
        archive_auto_lock=session.archive_auto_lock,
        live_queue_standby=session.live_queue_standby,
        telemetry_endpoint=session.telemetry_endpoint or None,
        telemetry_token=session.telemetry_token or None,
        telemetry_session_id=session.telemetry_session_id or None,
    )
    assert_watchalong_render_invariants(html)
    return html


def assert_watchalong_render_invariants(html: str) -> None:
    """Protect the master-clock contract at the shared Client seam."""

    if 'id="master-player"' not in html or 'id="source-player"' not in html:
        raise RuntimeError("Watchalong renderer is missing required player anchors")
    if "masterPlayer.seekTo" in html:
        raise RuntimeError("Watchalong renderer must never seek the master player")
    if "sourcePlayer.seekTo" not in html:
        raise RuntimeError("Watchalong renderer lost source-following seek behavior")




def _worker_ptt_player_script(config: dict, resolver_url: str = "") -> str:
    """Bind PTT to the current Primary without replacing mounted YouTube players."""
    safe = json.dumps(config, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    resolver = json.dumps(resolver_url, ensure_ascii=False)
    source = r"""
const pttWorkerConfig=__CONFIG__;
const pttResolverUrl=__RESOLVER__;
let pttPlayback=null,pttTransport=null,pttPollTimer=null,pttResolveToken=0;
const pttWorkerFeed=document.getElementById('ptt-worker-feed');
const pttWorkerStatus=document.getElementById('ptt-worker-status');
const pttWorkerFollow=document.getElementById('ptt-worker-follow');
const pttWorkerStyle=document.getElementById('ptt-worker-style');
const pttWorkerFloor=document.getElementById('ptt-worker-floor');
const pttWorkerFloorQuick=document.getElementById('ptt-worker-floor-quick');
const pttDynamicTitle=document.getElementById('ptt-dynamic-title');
const pttLiveFrame=document.getElementById('ptt-live-frame');
const pttUnavailable=document.getElementById('ptt-dynamic-unavailable');
const pttWorkerOptions=document.getElementById('ptt-worker-options');
const pttWorkerFollowLabel=document.getElementById('ptt-worker-follow-label');
function pttReadSetting(name,fallback){
 try{const x=localStorage.getItem(name);return x===null?fallback:x;}catch(_){return fallback;}
}
function pttSaveSetting(name,value){
 try{localStorage.setItem(name,value);}catch(_){}
}
function pttApplyReaderSettings(){
 if(!pttWorkerFeed)return;
 const style=pttWorkerStyle?pttWorkerStyle.value:'history';
 const floors=pttWorkerFloor?pttWorkerFloor.checked:(pttWorkerFloorQuick?pttWorkerFloorQuick.checked:true);
 if(pttWorkerFloor)pttWorkerFloor.checked=floors;
 if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=floors;
 pttWorkerFeed.classList.toggle('ptt-worker-original',style==='original');
 pttWorkerFeed.classList.toggle('ptt-worker-hide-floor',!floors);
 pttWorkerFeed.querySelectorAll('.ptt-worker-floor').forEach(el=>{el.hidden=!floors;});
 if(pttLiveFrame?.contentWindow){
  pttLiveFrame.contentWindow.postMessage({type:'holoviewer:ptt-show-floor',show:Boolean(floors)},location.origin);
 }
}
if(pttWorkerStyle){
 pttWorkerStyle.value=pttReadSetting('holoviewer-ptt-style','history')==='original'?'original':'history';
 pttWorkerStyle.addEventListener('change',()=>{
  pttSaveSetting('holoviewer-ptt-style',pttWorkerStyle.value);pttApplyReaderSettings();
 });
}
const savedFloorSetting=pttReadSetting('holoviewer-ptt-show-floor','true')!=='false';
if(pttWorkerFloor)pttWorkerFloor.checked=savedFloorSetting;
if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=savedFloorSetting;
function pttSetFloorVisibility(checked){
 if(pttWorkerFloor)pttWorkerFloor.checked=checked;
 if(pttWorkerFloorQuick)pttWorkerFloorQuick.checked=checked;
 pttSaveSetting('holoviewer-ptt-show-floor',String(checked));
 pttApplyReaderSettings();
}
pttWorkerFloor?.addEventListener('change',()=>pttSetFloorVisibility(pttWorkerFloor.checked));
pttWorkerFloorQuick?.addEventListener('change',()=>pttSetFloorVisibility(pttWorkerFloorQuick.checked));
pttApplyReaderSettings();
let pttPermanentWarning='';
function pttWarn(message){pttPermanentWarning=message;pttSetStatus('');}
function pttSetStatus(message){if(pttWorkerStatus)pttWorkerStatus.textContent=pttPermanentWarning?(pttPermanentWarning+' · '+message):message;}
function pttRender(rows,state){
 if(!pttWorkerFeed)return;
 const isNearBottom=pttWorkerFeed.scrollHeight-pttWorkerFeed.clientHeight-pttWorkerFeed.scrollTop<32;
 const oldNodes=Array.from(pttWorkerFeed.children);
 const oldScroll=pttWorkerFeed.scrollTop;
 const oldPositions=new Map(oldNodes.map(el=>[el.dataset.key,{top:el.offsetTop,height:el.offsetHeight}]));
 const existing=new Map(oldNodes.map(el=>[el.dataset.key,el]));
 const fragment=document.createDocumentFragment();
 rows.slice(-300).forEach(row=>{
  let el=existing.get(row.key);
  if(!el){
   el=document.createElement('div');el.className='ptt-worker-row';el.dataset.key=row.key;
   const kind=document.createElement('span');kind.className='ptt-worker-kind';kind.textContent=row.kind||'推';
   const clock=document.createElement('span');clock.className='ptt-worker-clock';clock.textContent=row.clock||'';
   const floor=document.createElement('span');floor.className='ptt-worker-floor';floor.textContent=row.floor?row.floor+'樓':'';
   const body=document.createElement('span');body.className='ptt-worker-body';
   const author=document.createElement('span');author.className='ptt-worker-author';author.textContent=row.author+': ';
   const content=document.createElement('span');content.className='ptt-worker-content';content.textContent=row.content;
   body.append(author,content);el.append(kind,clock,floor,body);
  }
  const floor=el.querySelector('.ptt-worker-floor');
  if(floor)floor.hidden=Boolean(pttWorkerFloor&&!pttWorkerFloor.checked);
  fragment.appendChild(el);
 });
 const firstVisible=oldNodes.find(el=>
  oldPositions.get(el.dataset.key).top+oldPositions.get(el.dataset.key).height>oldScroll)||oldNodes[0];
 const incomingKeys=new Set(rows.slice(-300).map(row=>row.key));
 const survivors=oldNodes.filter(el=>incomingKeys.has(el.dataset.key));
 const anchor=(firstVisible&&incomingKeys.has(firstVisible.dataset.key))
  ?firstVisible
  :survivors.find(el=>oldPositions.get(el.dataset.key).top>=oldScroll)||survivors[survivors.length-1];
 const anchorKey=anchor&&anchor.dataset.key;
 const anchorOffset=anchor?oldPositions.get(anchorKey).top-oldScroll:0;
 pttWorkerFeed.replaceChildren(fragment);
 if(pttWorkerFollow&&pttWorkerFollow.checked&&isNearBottom)pttWorkerFeed.scrollTop=pttWorkerFeed.scrollHeight;
 else {
  const restored=anchorKey&&Array.from(pttWorkerFeed.children).find(el=>el.dataset.key===anchorKey);
  pttWorkerFeed.scrollTop=restored?restored.offsetTop-anchorOffset:oldScroll;
 }
 pttSetStatus('同步推文 '+state.visible+' / '+state.total+' 則');
}
function disposePttBinding(){
 if(pttPollTimer){clearInterval(pttPollTimer);pttPollTimer=null;}
 if(pttTransport){pttTransport.stop();pttTransport=null;}
 if(pttPlayback){pttPlayback.dispose();pttPlayback=null;}
 pttPermanentWarning='';
}
function showArchivePtt(index,payload){
 disposePttBinding();
 if(!players[index]||!pttWorkerFeed)return;
 if(pttLiveFrame){pttLiveFrame.hidden=true;pttLiveFrame.removeAttribute('src');}
 if(pttUnavailable)pttUnavailable.hidden=true;
 pttWorkerFeed.hidden=false;
 if(pttWorkerOptions){pttWorkerOptions.hidden=false;pttWorkerOptions.classList.remove('live-ptt-controls');}
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=false;
 if(pttDynamicTitle)pttDynamicTitle.textContent='同時段歷史 PTT（未確認完整）';
 pttWorkerFeed.replaceChildren();
 pttPlayback=HoloViewerPttPlayer.attach({
  player:players[index],start:payload.start,render:pttRender,
  initialMessages:Array.isArray(payload.messages)?payload.messages:[],
  status:(state,msg)=>{if(state==='error')pttSetStatus(msg);}
 });
 pttApplyReaderSettings();
 pttSetStatus('跟隨主視角 · 同時段歷史推文');
}
function showLivePtt(){
 disposePttBinding();
 if(pttWorkerFeed)pttWorkerFeed.hidden=true;
 if(pttUnavailable)pttUnavailable.hidden=true;
 // Keep the font slider available after the live iframe replaces the archive feed.
 // Archive-only style/floor options are suppressed by the live-ptt-controls class.
 if(pttWorkerOptions){pttWorkerOptions.hidden=false;pttWorkerOptions.classList.add('live-ptt-controls');}
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=true;
 if(pttLiveFrame){
  const src=pttLiveFrame.dataset.src||'/ptt-today?focus=1&embed=1';
  if(pttLiveFrame.getAttribute('src')!==src)pttLiveFrame.setAttribute('src',src);
  pttLiveFrame.hidden=false;
 }
 if(pttDynamicTitle)pttDynamicTitle.textContent='PTT 今日專串';
 pttSetStatus('跟隨目前主視角 LIVE');
 pttApplyReaderSettings();
}
function showUnavailablePtt(){
 disposePttBinding();
 if(pttWorkerFeed)pttWorkerFeed.hidden=true;
 if(pttLiveFrame){pttLiveFrame.hidden=true;pttLiveFrame.removeAttribute('src');}
 if(pttWorkerOptions)pttWorkerOptions.hidden=true;
 if(pttWorkerFollowLabel)pttWorkerFollowLabel.hidden=true;
 if(pttUnavailable){
  pttUnavailable.hidden=false;
  pttUnavailable.textContent='目前主視角沒有可驗證的歷史 PTT 時間範圍；不會沿用上一支影片的推文。';
 }
 if(pttDynamicTitle)pttDynamicTitle.textContent='PTT 尚未對齊';
 pttSetStatus('');
}
async function refreshPrimaryPtt(index=primaryIndex){
 if(!pttResolverUrl)return;
 const stream=streams[index],player=players[index];
 if(!stream||!player)return;
 const token=++pttResolveToken;
 pttSetStatus('依主視角載入…');
 try{
  const join=pttResolverUrl.includes('?')?'&':'?';
  const response=await fetch(pttResolverUrl+join+'video_id='+encodeURIComponent(stream.videoId),{cache:'no-store',credentials:'same-origin'});
  if(!response.ok)throw new Error('PTT HTTP '+response.status);
  const payload=await response.json();
  if(token!==pttResolveToken||streams[index]?.videoId!==stream.videoId)return;
  if(payload?.mode==='archive')showArchivePtt(index,payload);
  else if(payload?.mode==='live')showLivePtt();
  else showUnavailablePtt();
 }catch(_error){
  if(token===pttResolveToken)showUnavailablePtt();
 }
}
function startPttBridge(index){
 if(pttResolverUrl){
  if(index===primaryIndex)refreshPrimaryPtt(index);
  return;
 }
 if(!pttWorkerFeed||pttPlayback||streams[index].videoId!==pttWorkerConfig.videoId)return;
 pttPlayback=HoloViewerPttPlayer.attach({
  player:players[index],start:pttWorkerConfig.start,render:pttRender,
  initialMessages:pttWorkerConfig.mode==='archive'?pttWorkerConfig.rows:[],
  status:(state,msg)=>{if(state==='error')pttSetStatus(msg);}
 });
 if(pttWorkerConfig.mode==='archive'){
  pttSetStatus('同時段歷史推文 · 來源 Coverage／Gap 未確認完整，非影片專屬留言');
  return;
 }
 pttTransport=HoloViewerWorkerPtt.create({
  aid:pttWorkerConfig.aid,endpoint:pttWorkerConfig.endpoint,mode:'history',
  onRows:rows=>pttPlayback.ingest(rows),
  onGap:cursor=>pttWarn('歷史資料存在缺口（purged cursor '+cursor+'）')
 });
 const refresh=()=>{
  const selected=players[index];
  if(selected&&typeof selected.getPlayerState==='function'&&typeof YT!=='undefined'&&YT.PlayerState&&selected.getPlayerState()===YT.PlayerState.ENDED){
    disposePttBinding();return;
  }
  return pttTransport.run().catch(error=>pttSetStatus('PTT 更新失敗：'+error.message));
 };
 refresh();pttPollTimer=setInterval(refresh,10000);
}
window.addEventListener('pagehide',disposePttBinding,{once:true});
"""
    return source.replace("__CONFIG__", safe).replace("__RESOLVER__", resolver)




def render_shared_viewing_session(session: SharedViewingSession, *, show_live_ptt: bool = False, ptt_worker_config: dict | None = None, ptt_alignment_notice: str = "", verified_start_times: Sequence[float] = (), manual_start_times: Sequence[float] = (), collab_poll_url: str = "", collab_label: str = "", ptt_resolver_url: str = "", translation_a: Sequence[dict] = (), translation_b: Sequence[dict] = (), translation_eligible: bool = False, translation_video_id: str = "") -> str:
    """Render a stable generic multi-player surface inside Client chrome.

    All YouTube player instances are created once. Layout, primary-view, volume and
    audio-master changes operate on existing DOM/player objects only.
    """

    if session.layout not in {ViewingLayout.AUTO, ViewingLayout.EQUAL, ViewingLayout.PRIMARY}:
        raise ValueError("generic shared viewing only supports auto / equal / primary layouts")

    collab_poll_json = json.dumps(collab_poll_url, ensure_ascii=False)
    collab_label_json = json.dumps(collab_label, ensure_ascii=False)
    ptt_resolver_json = json.dumps(ptt_resolver_url, ensure_ascii=False)
    verified_start_map_json = json.dumps(
        {
            stream.video_id: float(verified_start_times[index])
            for index, stream in enumerate(session.streams)
        }
        if len(verified_start_times) == len(session.streams)
        else {},
        ensure_ascii=False,
    )
    manual_start_map_json = json.dumps(
        {
            stream.video_id: float(manual_start_times[index])
            for index, stream in enumerate(session.streams)
        }
        if len(manual_start_times) == len(session.streams)
        else {},
        ensure_ascii=False,
    )
    translation_a_json = json.dumps(list(translation_a), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    translation_b_json = json.dumps(list(translation_b), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
    has_translation_tracks = bool(translation_a or translation_b)
    translation_hidden = "" if has_translation_tracks else " hidden"
    translation_prepare_hidden = " hidden"
    translation_initial_status = ""
    translation_video_json = json.dumps(translation_video_id)
    payload = json.dumps(
        [
            {
                "videoId": stream.video_id,
                "label": stream.label or f"Stream {index + 1}",
            }
            for index, stream in enumerate(session.streams)
        ],
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e")

    layout = session.layout.value
    ptt_panel = ('<aside class="ptt-live-panel" aria-label="PTT 今日專串"><div class="ptt-panel-heading"><span>PTT 今日專串<small>今日公開推文・尚未與影片時間軸連動</small></span><a href="/ptt-today" target="_blank" rel="noopener">獨立閱讀 ↗</a></div><iframe title="PTT 今日專串即時閱讀" src="/ptt-today?focus=1&embed=1" loading="lazy"></iframe></aside>' if show_live_ptt else "")
    if show_live_ptt and not ptt_worker_config and not ptt_alignment_notice:
        ptt_panel = ptt_panel.replace(
            '</div><iframe',
            '<span class="ptt-embed-controls"><label class="ptt-embed-floor"><input id="pttEmbedShowFloor" type="checkbox" checked> 樓</label><label class="ptt-embed-font">字體 <input id="pttFontSize" type="range" min="12" max="26" value="16" step="2" aria-label="調整推文字體大小"><output id="pttFontValue">16px</output></label></span></div><iframe',
            1,
        )
    if show_live_ptt and ptt_alignment_notice:
        ptt_panel = ('<aside class="ptt-live-panel" aria-label="PTT 對齊狀態">'
                     '<div class="ptt-panel-heading"><span>PTT 尚未對齊</span></div>'
                     '<div class="ptt-unavailable">' + escape(ptt_alignment_notice) + '</div></aside>')
    if show_live_ptt and ptt_worker_config:
        archive = ptt_worker_config.get("mode") == "archive"
        heading = ("同時段歷史 PTT（未確認完整）" if archive else "PTT 影片同步")
        ptt_panel = ('<aside class="ptt-live-panel" aria-label="影片同步 PTT 專串">'
                     f'<div class="ptt-panel-heading"><span>{heading}<small id="ptt-worker-status">等待資料來源…</small></span>'
                     '<span class="ptt-heading-controls"><label style="font-size:11px"><input id="ptt-worker-follow" type="checkbox" checked> 自動跟隨</label>'
                     '<label class="ptt-floor-quick" style="font-size:11px"><input id="ptt-worker-floor-quick" type="checkbox" checked> 樓</label></span></div>'
                     '<div class="ptt-worker-options"><label>字體 <input id="pttFontSize" type="range" min="12" max="26" value="14" step="2" aria-label="調整推文字體大小"><output id="pttFontValue">14px</output></label>'
                     '<label>配色 <select id="ptt-worker-style"><option value="history">歷史</option><option value="original">原本</option></select></label>'
                     '<label><input id="ptt-worker-floor" type="checkbox" checked> 顯示樓數</label></div>'
                     '<div id="ptt-worker-feed" role="log" aria-label="同步推文"></div></aside>')

    if show_live_ptt and ptt_resolver_url:
        # One stable panel can switch between today's live reader and an
        # archive timeline without ever replacing/reloading the YouTube player.
        ptt_panel = (
            '<aside class="ptt-live-panel" aria-label="Primary PTT">'
            '<div class="ptt-panel-heading"><span><span id="ptt-dynamic-title">PTT</span>'
            '<small id="ptt-worker-status">依主視角載入…</small></span>'
            '<span class="ptt-heading-controls">'
            '<label id="ptt-worker-follow-label" style="font-size:11px"><input id="ptt-worker-follow" type="checkbox" checked> 自動跟隨</label>'
            '<label id="ptt-floor-quick-label" class="ptt-floor-quick" style="font-size:11px"><input id="ptt-worker-floor-quick" type="checkbox" checked> 樓</label>'
            '</span></div>'
            '<div id="ptt-worker-options" class="ptt-worker-options">'
            '<label>字體 <input id="pttFontSize" type="range" min="12" max="26" value="14" step="2" aria-label="調整推文字體大小"><output id="pttFontValue">14px</output></label>'
            '<label>配色 <select id="ptt-worker-style"><option value="history">歷史</option><option value="original">原本</option></select></label>'
            '<label><input id="ptt-worker-floor" type="checkbox" checked> 顯示樓數</label></div>'
            '<iframe id="ptt-live-frame" title="PTT 今日專串即時閱讀" data-src="/ptt-today?focus=1&embed=1" loading="lazy" hidden></iframe>'
            '<div id="ptt-worker-feed" role="log" aria-label="同步推文" hidden></div>'
            '<div id="ptt-dynamic-unavailable" class="ptt-unavailable" hidden></div>'
            '</aside>'
        )
    css = r"""
.viewer-workspace{display:grid;gap:12px}
.player-toolbar{display:flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--line);border-radius:14px;background:var(--surface);overflow-x:auto}
.player-toolbar button{border:1px solid var(--line);background:var(--surface-2);color:var(--text);border-radius:9px;padding:7px 10px;cursor:pointer;white-space:nowrap}
.player-toolbar button.active{background:var(--text);color:#fff;border-color:var(--text)}
.player-status{margin-left:auto;color:var(--muted);font-size:12px;white-space:nowrap}
#stage{min-height:0;display:grid;gap:10px;grid-template-columns:repeat(var(--columns),minmax(0,1fr))}
.player-card{min-width:0;background:#111;border:1px solid #252525;border-radius:14px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 5px 18px rgba(0,0,0,.09)}
.video-wrap{position:relative;aspect-ratio:16/9;background:#000}.player{position:absolute;inset:0;width:100%;height:100%}
.player-controls{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:8px 9px;background:#151515;color:#eee}
.player-label{font-size:12px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.audio-row{display:flex;align-items:center;gap:6px;margin-top:5px;font-size:10px;color:#aaa}.audio-row input{flex:1;min-width:70px}
.player-actions{display:flex;gap:6px}.player-actions button,.player-actions .player-youtube-link{border:1px solid #3a3a3a;background:#202020;color:#eee;border-radius:7px;padding:6px 8px;cursor:pointer;white-space:nowrap;text-decoration:none;font-size:12px;display:inline-flex;align-items:center}
.player-actions .master{transition:background .14s ease,color .14s ease,border-color .14s ease,box-shadow .14s ease}
.player-actions .master.active{background:#7650cf;color:#fff;border-color:#8b6bdd;box-shadow:0 0 0 2px rgba(118,80,207,.22);font-weight:850}
body.layout-primary #stage{grid-template-columns:minmax(0,2.25fr) minmax(240px,.9fr);align-items:start}
body.layout-primary .player-card.primary{grid-column:1;grid-row:1 / span var(--side-count,1);align-self:start}
body.layout-primary .player-card:not(.primary){grid-column:2;align-self:start}
.custom-immersive-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.custom-immersive-controls button{border:1px solid var(--line);border-radius:9px;padding:7px 10px;background:var(--surface);cursor:pointer}
.custom-content-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,28%);gap:10px;align-items:start}
.custom-content-grid.video-only{display:block}
.viewer-workspace:has(.ptt-live-panel){width:100%}
body:has(.ptt-live-panel) .client-main{max-width:1560px}
.player-toolbar{flex-wrap:wrap;overflow:visible}
.player-toolbar [hidden],.player-actions [hidden]{display:none!important}
.custom-content-grid{grid-template-columns:minmax(0,1fr) minmax(240px,var(--ptt-width,28%));gap:8px}
.custom-content-grid:has(.ptt-live-panel) #stage{grid-template-columns:repeat(var(--columns),minmax(0,1fr))}
body.layout-primary .custom-content-grid:has(.ptt-live-panel) #stage{grid-template-columns:minmax(0,2.25fr) minmax(200px,.9fr)}
.ptt-live-panel{position:sticky;top:74px}
.ptt-panel-heading{gap:12px;line-height:1.4}.ptt-heading-controls{display:flex;align-items:center;gap:10px;margin-left:auto}.ptt-floor-quick{display:inline-flex;align-items:center;gap:4px;white-space:nowrap}
.ptt-panel-heading small{display:block;color:#a5aeb3;font-size:11px;font-weight:500;margin-top:3px}
.ptt-panel-heading a{white-space:nowrap}.ptt-embed-controls{display:inline-flex;align-items:center;gap:10px;margin-left:auto}.ptt-embed-floor,.ptt-embed-font{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:500;white-space:nowrap}.ptt-embed-font input{width:92px}.ptt-embed-font output{min-width:34px}
.translation-slot{font-size:12px;line-height:1.5}
body.custom-immersive .custom-content-grid{grid-template-columns:minmax(0,1fr) minmax(240px,var(--ptt-width,28%));align-items:start}
body.custom-immersive .ptt-live-panel{top:0}
body.custom-immersive .ptt-panel-heading,body.custom-immersive .ptt-worker-options{display:none!important}
body.custom-immersive .ptt-live-panel iframe{border:0!important}
body.custom-immersive .ptt-live-panel iframe[src*="focus=1"]{pointer-events:auto}
body.custom-immersive #ptt-worker-feed{height:100%;max-height:none;min-height:0;padding-top:4px}
body.custom-immersive .viewer-workspace{gap:6px}
body.custom-immersive .player-toolbar{padding:6px 10px}
@media(max-width:1100px){.custom-content-grid{grid-template-columns:minmax(0,1fr) minmax(240px,var(--ptt-width,28%))}}
@media(max-width:900px){.custom-content-grid,body.custom-immersive .custom-content-grid{grid-template-columns:1fr}.ptt-live-panel{position:static}.ptt-live-panel iframe{height:50vh;min-height:320px}}

.custom-player-column{min-width:0}
.ptt-live-panel{min-width:0;background:#101010;border-radius:12px;overflow:hidden;border:1px solid #303030;color:#eee}
.ptt-live-panel [hidden],body.custom-session-watching.custom-immersive .ptt-live-panel [hidden]{display:none!important}
.ptt-unavailable{padding:28px 18px;color:#aeb5b8;font-size:13px;line-height:1.6}
.ptt-panel-heading{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;font-size:13px;font-weight:700}
.ptt-panel-heading a{color:#b5d7e5;text-decoration:none;font-size:11px}
.ptt-live-panel iframe{width:100%;height:min(72vh,720px);min-height:320px;border:0;display:block}
#ptt-worker-feed{height:min(72vh,720px);min-height:320px;overflow:auto;padding:6px 10px;background:#0c0d0f;color:#eee;font-size:14px;line-height:1.45}
.ptt-worker-options{display:flex;gap:12px;align-items:center;padding:2px 12px 7px;color:#ccc;font-size:11px}
.ptt-worker-options label{display:inline-flex;gap:5px;align-items:center}
.ptt-worker-options.live-ptt-controls label:not(:first-child){display:none}
.ptt-worker-options select{max-width:85px;background:#222;color:#eee;border:1px solid #555;border-radius:4px}
.ptt-worker-row{display:grid;grid-template-columns:1.3em 4.1em 3.4em minmax(0,1fr);column-gap:6px;align-items:start;padding:4px 2px;border-bottom:1px solid #25282a;overflow-wrap:anywhere;font-size:var(--ptt-font-size,14px);line-height:1.45}
.ptt-worker-kind{text-align:center;font-weight:800;color:#f4f4f4}
.ptt-worker-clock{color:#dedede;font-size:.72em;white-space:nowrap;padding-top:.25em}
.ptt-worker-floor{color:#777;font-size:.72em;white-space:nowrap;padding-top:.25em}
.ptt-worker-body{min-width:0;white-space:pre-wrap;overflow-wrap:anywhere}
.ptt-worker-author{color:#ffff00;font-weight:650}
.ptt-worker-content{color:#a9a900}
#ptt-worker-feed.ptt-worker-original{background:#080808}
#ptt-worker-feed:not(.ptt-worker-original) .ptt-worker-author{color:#64ccea}
#ptt-worker-feed:not(.ptt-worker-original) .ptt-worker-content{color:#eee}
#ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-row{grid-template-columns:1.3em 4.1em minmax(0,1fr)}
#ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-floor{display:none}

.translation-slot{margin-top:6px;min-height:54px;padding:7px 10px;background:#0d0d0d;border:1px solid #303030;border-radius:10px;color:#eee;font-size:13px}.translation-track-controls{display:flex;gap:5px;justify-content:flex-end;margin-bottom:4px}.translation-track-controls button{border:1px solid #444;background:#1c1c1c;color:#bbb;border-radius:5px;padding:3px 7px;cursor:pointer}.translation-track-controls button.active{background:#eee;color:#111;font-weight:800}.translation-text{text-align:center;font-size:15px;line-height:1.45;min-height:1.5em}
body.custom-immersive .client-rail,body.custom-immersive .client-topbar,body.custom-immersive .viewer-head{display:none!important}
body.custom-immersive .client-main{margin-left:0!important;max-width:none!important;padding:10px!important}
body.custom-immersive .player-toolbar,body.custom-immersive .viewer-head,body.custom-immersive .client-rail,body.custom-immersive .client-topbar{display:none!important}
body.custom-immersive .watch-actions{display:none!important}
body.custom-immersive .client-main{padding:0!important;max-width:none!important}
body.custom-immersive .viewer-workspace{gap:0;background:#080808;min-height:100vh}
body.custom-immersive .custom-content-grid{gap:2px!important}
body.custom-immersive .player-card{border-radius:0;box-shadow:none}
body.custom-immersive .ptt-live-panel{position:static;border-radius:0;border:0}
/* A single archived stream needs a readable PTT rail in immersive mode.  Multi-view
   keeps the owner-accepted width above. */
body.custom-immersive:not(.single-ptt):has(#stage .player-card:only-child) .custom-content-grid:has(.ptt-live-panel){grid-template-columns:minmax(0,1fr) minmax(320px,30vw)!important}
body.custom-immersive:not(.single-ptt):has(#stage .player-card:only-child) .ptt-live-panel{height:100vh;max-height:100vh}
body.custom-immersive:not(.single-ptt):has(#stage .player-card:only-child) #ptt-worker-feed{height:100vh;max-height:100vh;min-height:0}
body.custom-immersive .translation-slot:not([hidden]){position:fixed;left:12px;bottom:10px;z-index:45;width:min(760px,calc(66vw - 24px));margin:0;background:rgba(13,13,13,.94);backdrop-filter:blur(8px)}
.ptt-font-label{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;white-space:nowrap}
.player-sync-label{display:flex;align-items:center;gap:5px;font-size:12px;color:var(--muted);white-space:nowrap}
.player-sync-label input{accent-color:#367c9f}
#videoHeight{width:110px}
#videoHeightValue{min-width:50px;font-variant-numeric:tabular-nums}
body.custom-immersive #videoHeightLabel{display:none}
.custom-player-column{--custom-video-height:1000px}
.custom-player-column .video-wrap{max-height:var(--custom-video-height)}
.custom-player-column .video-wrap iframe{max-height:var(--custom-video-height)}
.focus-choices{display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.focus-choices button{font-size:12px}
.focus-choices button.active{background:var(--text);color:#fff}
#focusCarouselInterval{width:85px;accent-color:#367c9f}
#focusCarouselIntervalOutput{min-width:38px}
body.layout-primary .player-card{min-width:0}
.ptt-font-label input{width:100px;accent-color:var(--text)}
.ptt-font-label output{min-width:34px;font-variant-numeric:tabular-nums}
body.custom-immersive .translation-slot[hidden]{display:none!important}
@media(max-width:900px){.custom-content-grid{grid-template-columns:1fr}.ptt-live-panel iframe{height:55vh;min-height:360px}}

/* Match the accepted 8501 two-view Focus composition: main A/B left,
   the other video upper-right, PTT immediately beneath it. */
@media(min-width:761px){
 body.layout-primary:has(.ptt-live-panel) .custom-content-grid{display:block}
 body.layout-primary:has(.ptt-live-panel) #stage{
  display:grid;grid-template-columns:minmax(0,2.25fr) minmax(260px,.9fr);
  grid-template-rows:auto auto minmax(240px,1fr);align-items:stretch;gap:6px;
  min-height:calc(100vh - 155px)
 }
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.primary{
  grid-column:1;grid-row:1 / 4;align-self:stretch;min-height:0
 }
 body.layout-primary:has(.ptt-live-panel) #stage .player-card:not(.primary){
  grid-column:2;min-height:0
 }
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.focus-hidden{display:none!important}
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.focus-side-1{grid-row:1}
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.focus-side-2{grid-row:2}
 body.layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel{
  grid-column:2;grid-row:3;min-height:0;position:static;display:flex;flex-direction:column
 }
 body.layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel iframe{
  flex:1;min-height:0;height:100%;width:100%
 }
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.primary .video-wrap{
  flex:1;min-height:0;aspect-ratio:auto;max-height:none
 }
 body.layout-primary:has(.ptt-live-panel) #stage .player-card.primary .video-wrap iframe{max-height:none}
 body.layout-primary:has(.ptt-live-panel) #stage .player-card:not(.primary) .video-wrap{max-height:none}
 body.layout-primary:has(.ptt-live-panel) .translation-slot[hidden]{display:none!important}
}
body.custom-immersive .client-rail,body.custom-immersive .client-sidebar,
body.custom-immersive .channel-rail,body.custom-immersive .avatar-rail,
body.custom-immersive .sidebar,body.custom-immersive .left-rail{display:none!important}
body.custom-immersive .client-main{width:100vw!important;max-width:100vw!important}
body.custom-immersive .viewer-workspace{width:100vw!important}
body.custom-immersive .player-card .player-controls{display:none!important}
body.custom-immersive .custom-content-grid:has(.ptt-live-panel){display:block}

/* Watching is the default: maximize the existing viewport, reserve a
   narrow left channel-switching rail instead of overlaying the video. */
body.custom-session-watching .client-main{
 margin-left:calc(var(--rail-collapsed,72px) + var(--watch-rail,64px))!important;
 width:calc(100vw - var(--rail-collapsed,72px) - var(--watch-rail,64px))!important;
 max-width:none!important;padding:4px 8px 8px!important
}
body.custom-session-watching .viewer-head{display:none}
body.custom-session-watching .viewer-workspace{gap:4px}
body.custom-session-watching .custom-content-grid{gap:5px}
body.custom-session-watching .player-toolbar{padding:4px 8px;gap:5px}
/* Keep the shared navigation rail: home/watchalong/custom/PTT remain reachable.
   The stream-avatar rail starts beneath the global navigation, as on other pages. */
body.custom-session-watching .client-topbar{display:none!important}
body.custom-session-watching .client-rail{display:block!important;z-index:90}
body.custom-session-watching .live-channel-rail{
 left:var(--rail-collapsed,72px);top:0;bottom:0;max-height:100dvh;width:64px;
 border-radius:0;z-index:70;padding-top:8px
}
body.custom-session-watching .live-channel-rail:hover,
body.custom-session-watching .live-channel-rail:focus-within{width:222px}
/* Expanded channel picker changes reserved space, never covers the video. */
body.custom-session-watching:has(.live-channel-rail:hover):not(.custom-immersive),
body.custom-session-watching:has(.live-channel-rail:focus-within):not(.custom-immersive){
 --watch-rail:222px
}
body.custom-session-watching:has(.live-channel-rail:hover) .client-main,
body.custom-session-watching:has(.live-channel-rail:focus-within) .client-main{
 margin-left:calc(var(--rail-collapsed,72px) + 222px)!important;
 width:calc(100vw - var(--rail-collapsed,72px) - 222px)!important;
 padding-left:8px!important;max-width:none!important
}
body.custom-session-watching .custom-player-column{--custom-video-height:1000px}
body.custom-session-watching .player-toolbar .ptt-width-label input{width:80px}
body.custom-session-watching .player-toolbar #status{display:none}
body.custom-session-watching .translation-slot[hidden]{display:none!important}

/* 8501 parity: watching is full-viewport without being fullscreen. */
body.custom-session-watching{--watch-rail:64px}
body.custom-session-watching .client-main{
 margin-left:calc(var(--rail-collapsed,72px) + var(--watch-rail))!important;
 width:calc(100vw - var(--rail-collapsed,72px) - var(--watch-rail))!important
}
body.custom-session-watching .custom-content-grid:has(#stage .ptt-live-panel){display:block}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel){display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,var(--ptt-width,28%));align-items:stretch}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel{height:calc(100dvh - 56px);display:flex;flex-direction:column;position:static}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel iframe{height:100%;min-height:0;flex:1}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel{height:100dvh}
body.custom-session-watching:not(.single-ptt) #stage{min-height:0}
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage{display:grid;gap:6px}
body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage,
body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage{
 grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:auto minmax(220px,1fr);
}
body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage .ptt-live-panel,
body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage .ptt-live-panel{
 grid-column:1 / -1;grid-row:2;min-height:220px;position:static
}
body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage{
 grid-template-columns:minmax(0,2.25fr) minmax(260px,.9fr);
 grid-template-rows:auto minmax(220px,1fr);min-height:calc(100vh - 85px);
}
body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel{
 grid-column:2;grid-row:2;position:static;min-height:220px
}
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-live-panel iframe{height:100%;min-height:220px}
body.custom-session-watching .player-toolbar{display:none}
body.custom-session-watching.settings-open .player-toolbar{display:flex}
body.custom-session-watching .watch-actions{display:flex;justify-content:flex-end;gap:6px;align-items:center;padding:3px 6px}
body.custom-session-watching .watch-actions button{font:inherit;border:1px solid var(--line);border-radius:7px;padding:5px 9px;background:var(--surface);color:var(--text);cursor:pointer}
body.custom-session-watching.custom-immersive{--watch-rail:0px}
body.custom-session-watching.custom-immersive .live-channel-rail,
body.custom-session-watching.custom-immersive .watch-actions,
body.custom-session-watching.custom-immersive .ptt-focus-toolbar,
body.custom-session-watching.custom-immersive .focus-toolbar,
body.custom-session-watching.custom-immersive .focus-exit,
body.custom-session-watching.custom-immersive [data-focus-exit],
body.custom-session-watching.custom-immersive .player-toolbar,
body.custom-session-watching.custom-immersive .immersive-ptt-width{display:none!important}
body.custom-session-watching.custom-immersive .client-main{
 margin-left:0!important;width:100vw!important;padding:0!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive #stage{min-height:100vh}
body.custom-session-watching.custom-immersive .player-controls{display:flex!important;padding:2px 6px}
body.custom-session-watching.custom-immersive .player-actions,
body.custom-session-watching.custom-immersive .player-label{display:none!important}
body.custom-session-watching.custom-immersive .audio-row{margin:0;width:180px}
body.custom-session-watching.custom-immersive .player-card{border:0;border-radius:0}
body.custom-session-watching.custom-immersive .video-wrap{max-height:none}
@media(max-width:760px){
 body.custom-session-watching:not(.single-ptt).layout-auto #stage,
 body.custom-session-watching:not(.single-ptt).layout-equal #stage,
 body.custom-session-watching:not(.single-ptt).layout-primary #stage{grid-template-columns:1fr!important;grid-template-rows:auto!important;min-height:0}
 body.custom-session-watching:not(.single-ptt) #stage .ptt-live-panel,
 body.custom-session-watching:not(.single-ptt) #stage .player-card{grid-column:1!important;grid-row:auto!important}
}

/* 8501 grid also keeps the feed below three/four equal streams and
   beneath the secondary video column in Focus A/B/C/D. */
@media(min-width:761px){
 body.custom-session-watching.layout-equal:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)),
 body.custom-session-watching.layout-auto:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)){
  grid-template-rows:auto auto minmax(0,1fr)
 }
 body.custom-session-watching.layout-equal:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)) .ptt-live-panel,
 body.custom-session-watching.layout-auto:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)) .ptt-live-panel{
  grid-column:1/-1;grid-row:3
 }
 body.custom-session-watching.layout-equal:has(.ptt-live-panel) #stage > .player-card:nth-child(3):nth-last-child(2){
  grid-column:1/-1
 }
 body.custom-session-watching.layout-primary:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)){
  grid-template-rows:repeat(var(--side-count),auto) minmax(0,1fr)
 }
 body.custom-session-watching.layout-primary:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)) .player-card.primary{
  grid-column:1;grid-row:1 / span calc(var(--side-count) + 1)
 }
 body.custom-session-watching.layout-primary:has(.ptt-live-panel) #stage:has(> .player-card:nth-child(3)) .ptt-live-panel{
  grid-column:2;grid-row:calc(var(--side-count) + 1)
 }
}
/* PTT must take the full remaining viewport height in both 8501 layouts. */
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage{
 height:calc(100dvh - 56px);
 grid-template-rows:minmax(0,auto) minmax(0,1fr);
 align-content:stretch;overflow:hidden
}
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-live-panel{
 height:100%;min-height:0;overflow:hidden;display:flex;flex-direction:column
}
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-panel-heading{flex:0 0 auto}
body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-live-panel iframe{
 height:100%;min-height:0;flex:1 1 auto
}
body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage{
 grid-template-rows:minmax(0,auto) minmax(0,1fr)
}
body.custom-session-watching:not(.single-ptt).custom-immersive:has(.ptt-live-panel) #stage{height:100dvh}
/* Focus 1+2 owns the final desktop geometry. Keep the whole stage inside the
   viewport (including player control bars), and let PTT consume only the
   remaining right-column height. */
@media(min-width:761px){
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage{
  height:calc(100dvh - 56px)!important;min-height:0!important;
  grid-template-columns:minmax(0,2.25fr) minmax(260px,.9fr)!important;
  grid-template-rows:minmax(0,auto) minmax(0,auto) minmax(0,1fr)!important;
  align-content:stretch;overflow:hidden
 }
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .player-card.primary{
  grid-column:1!important;grid-row:1 / 4!important;height:100%;min-height:0;overflow:hidden
 }
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .player-card.primary .video-wrap{
  flex:1 1 auto;min-height:0
 }
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .player-card.focus-side-1{grid-column:2;grid-row:1!important}
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .player-card.focus-side-2{grid-column:2;grid-row:2!important}
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel{
  grid-column:2!important;grid-row:3!important;height:100%;min-height:0!important
 }
}
.player-card.replacement-target .replacement-choice{background:#eef1f2;color:#111;font-weight:700}
body.custom-session-watching:not(.settings-open) .player-card .replacement-choice{opacity:.25}
body.custom-session-watching .player-card .replacement-choice:hover,
body.custom-session-watching .player-card .replacement-choice:focus-visible{opacity:1}
.global-volume-label,.immersive-global-volume{display:flex;align-items:center;gap:5px;font-size:12px;white-space:nowrap}
.global-volume-label input,.immersive-global-volume input{width:110px;accent-color:#5799cf}
.global-volume-label output,.immersive-global-volume output{min-width:34px;font-variant-numeric:tabular-nums}
.immersive-global-volume{display:none}
body.custom-session-watching.custom-immersive .immersive-global-volume{display:flex;position:fixed;bottom:12px;left:12px;z-index:120;color:#fff;padding:6px 10px;border-radius:7px;background:rgba(0,0,0,.7)}

/* Narrow viewing: retain two video controls in settings, not below videos.
   Give the PTT reader the leftover fixed viewport, and scroll only inside it. */
@media(max-width:760px){
 html:has(body.custom-session-watching),body.custom-session-watching{height:100%;overflow:hidden}
 body.custom-session-watching .client-main{height:100dvh;overflow:hidden}
 body.custom-session-watching .viewer-workspace{height:100%;min-height:0;display:flex;flex-direction:column}
 body.custom-session-watching .watch-actions{flex:0 0 auto}
 body.custom-session-watching:not(.single-ptt) .custom-content-grid,
 body.custom-session-watching:not(.single-ptt) .custom-player-column{min-height:0;flex:1;display:flex;flex-direction:column}
 body.custom-session-watching:not(.single-ptt) #stage,
 body.custom-session-watching:not(.single-ptt).layout-equal #stage,
 body.custom-session-watching:not(.single-ptt).layout-primary #stage{
  display:flex!important;flex-direction:column;flex:1;min-height:0;
  height:auto!important;gap:3px;overflow:hidden
 }
 body.custom-session-watching:not(.single-ptt) #stage .player-card{flex:0 0 auto;min-height:0}
 body.custom-session-watching:not(.single-ptt) #stage .player-card .player-controls{display:none!important}
 body.custom-session-watching:not(.single-ptt) #stage .video-wrap{aspect-ratio:16/9;max-height:none}
 body.custom-session-watching:not(.single-ptt) #stage .ptt-live-panel{
  display:flex!important;flex:1 1 auto;height:auto!important;min-height:0!important;
  width:100%;overflow:hidden;grid-column:auto!important;grid-row:auto!important
 }
 body.custom-session-watching:not(.single-ptt) #stage .ptt-panel-heading{display:none!important}
 body.custom-session-watching:not(.single-ptt) #stage .ptt-live-panel iframe{
  display:block;flex:1 1 auto;height:100%!important;min-height:0!important
 }
 body.custom-session-watching .watch-actions{padding:2px 4px}
 body.custom-session-watching .watch-actions .global-volume-label{margin-right:auto}
 body.custom-session-watching .watch-actions .global-volume-label input{width:95px}
}

/* Single-view acceptance: one full-width player alongside one narrow PTT
   column. Primary mode must NOT reserve a phantom second player column. */
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage{
 display:grid;grid-template-columns:minmax(0,1fr)!important;
 width:100%;min-width:0;height:auto;overflow:visible
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage .player-card{
 grid-column:1!important;grid-row:1!important;width:100%;min-width:0;
 align-self:start
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage .video-wrap{
 width:100%;aspect-ratio:16/9;max-height:none
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage .player-controls{
 display:none!important
}
/* Preserve the sole visible total volume in both normal/immersive view. */
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) #stage .player-controls{
 display:none!important
}
body.custom-session-watching .live-channel-rail:not(:hover):not(:focus-within){
 width:64px!important
}
body.custom-session-watching .live-channel-rail:not(:hover):not(:focus-within) .live-channel-label{
 display:none!important
}
body.custom-session-watching .live-channel-rail:not(:hover):not(:focus-within) .live-channel-rail-item strong{
 opacity:0!important
}

.watch-mode-switch{display:flex;align-items:center;gap:9px;min-height:36px}
.watch-mode-switch button{border:0;background:transparent;color:#817c86;cursor:pointer;font-size:12px;font-weight:750;white-space:nowrap;padding:5px 2px;transition:color .16s ease,font-weight .16s ease}
.watch-mode-switch button:hover{color:#56385f}
.watch-mode-switch button[aria-pressed="true"]{color:#61346e;font-weight:900}
.watch-mode-toggle{position:relative;width:46px;height:25px;border:0;border-radius:999px;background:#d8d4dc;box-shadow:inset 0 1px 3px rgba(34,24,39,.16);cursor:pointer;padding:0;transition:background .18s ease,box-shadow .18s ease}
.watch-mode-toggle::after{content:"";position:absolute;top:3px;left:3px;width:19px;height:19px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(34,24,39,.28);transition:transform .18s ease}
.watch-mode-toggle[aria-checked="true"]{background:#7650cf;box-shadow:inset 0 1px 3px rgba(52,31,99,.24)}
.watch-mode-toggle[aria-checked="true"]::after{transform:translateX(21px)}
.watch-mode-toggle:focus-visible{outline:2px solid #7650cf;outline-offset:2px}
@media(max-width:800px){.watch-mode-switch{gap:7px}}
.player-actions .replacement-choice{display:none!important}
.player-actions .remove-stream{background:#9f322e;color:white}
body.custom-session-watching.watch-grid .custom-content-grid:has(.ptt-live-panel){display:block!important}
/* Grid dimensions follow the actual number of occupied tiles (video + PTT),
   so a six-tile view is 3x2 rather than a visually undersized 3x3 layout. */
body.custom-session-watching.watch-grid #stage:has(.ptt-live-panel){
 display:grid!important;
 grid-template-columns:repeat(var(--tile-columns,2),minmax(0,1fr))!important;
 grid-template-rows:repeat(var(--tile-rows,2),max-content)!important;
 grid-auto-rows:max-content!important;
 height:auto!important;min-height:0!important;max-height:none!important;
 overflow:visible!important;align-items:start!important;align-content:start!important
}
body.custom-session-watching.watch-grid #stage .player-card,
body.custom-session-watching.watch-grid #stage .ptt-live-panel{
 grid-column:auto!important;grid-row:auto!important;min-width:0;min-height:0;align-self:start
}
body.custom-session-watching.watch-grid #stage .player-card.primary{grid-row:auto!important}
body.custom-session-watching.watch-grid #stage .ptt-live-panel{height:auto!important;min-height:0!important}
body.custom-session-watching.watch-grid #stage .ptt-live-panel iframe{height:calc(100% - 44px)!important;min-height:220px!important}
body.custom-session-watching.watch-grid .video-wrap{aspect-ratio:16/9!important;max-height:none}
@media(max-width:760px){
 body.custom-session-watching.watch-grid #stage:has(.ptt-live-panel){display:grid!important;grid-template-columns:minmax(0,1fr)!important;grid-template-rows:none!important;grid-auto-rows:max-content!important;height:auto!important;overflow:visible!important}
}

/* Fullscreen is a layout state, not a separate unmounted video experience. */
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid{height:auto!important;min-height:100dvh;overflow:visible!important}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel){display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,var(--ptt-width,28%));align-items:start}
body.custom-session-watching:not(.single-ptt).custom-immersive #stage .player-card .player-controls{display:none!important}
body.custom-session-watching:not(.single-ptt).custom-immersive.watch-grid .custom-content-grid:has(.ptt-live-panel){display:block!important;height:auto!important;overflow:visible!important}
body.custom-session-watching:not(.single-ptt).custom-immersive.watch-grid #stage,
body.custom-session-watching:not(.single-ptt).custom-immersive.watch-grid #stage:has(.ptt-live-panel){
 height:auto!important;max-height:none!important;min-height:0!important;
 overflow:visible!important;align-content:start!important;
 grid-template-rows:repeat(var(--tile-rows,2),max-content)!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive.watch-grid .custom-content-grid{display:block!important;height:auto!important;overflow:visible!important}
body.custom-session-watching:not(.single-ptt).custom-immersive.watch-grid .player-card{align-self:start}
body.custom-session-watching:not(.single-ptt).custom-immersive .immersive-global-volume{display:flex!important}
/* Two distinct left rails: site navigation, then live-channel avatars. */
body.custom-session-watching .client-rail{z-index:90}
body.custom-session-watching .live-channel-rail{z-index:70!important}
body.custom-session-watching:not(.single-ptt).custom-immersive .client-rail{display:none!important}
body.custom-session-watching:not(.single-ptt).custom-immersive .live-channel-rail{display:none!important}
/* Immersive is an explicit UI state: always hide both left rails and global nav. */
body.custom-session-watching:not(.single-ptt).custom-immersive .client-rail,
body.custom-session-watching:not(.single-ptt).custom-immersive .live-channel-rail,
body.custom-session-watching:not(.single-ptt).custom-immersive .client-topbar,
body.custom-session-watching:not(.single-ptt).custom-immersive #mobileNav{display:none!important}
body.custom-session-watching:not(.single-ptt).custom-immersive .client-main{
 margin-left:0!important;width:100vw!important;max-width:100vw!important;padding:0!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive .watch-actions{display:none!important}
body.custom-session-watching:not(.single-ptt).custom-immersive .immersive-global-volume{display:flex!important}

/* Authoritative responsive fit: custom viewing owns one browser viewport;
   scroll only inside the PTT reader, never on the outer document. */
html:has(body.custom-session-watching),
body.custom-session-watching{
 width:100%;height:100%;min-height:0;max-height:100dvh;
 overflow:hidden!important;overscroll-behavior:none
}
body.custom-session-watching .client-main{
 box-sizing:border-box;height:100dvh!important;min-height:0!important;max-height:100dvh!important;
 overflow:hidden!important;padding-top:4px!important;padding-bottom:4px!important
}
body.custom-session-watching .viewer-workspace{
 display:flex!important;flex-direction:column!important;gap:4px!important;
 width:100%;height:100%!important;min-width:0;min-height:0!important;
 max-height:100%!important;overflow:hidden!important
}
body.custom-session-watching .watch-actions{
 flex:0 0 auto;min-width:0;max-width:100%;min-height:40px;
 overflow:hidden;flex-wrap:nowrap
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid{
 flex:1 1 0!important;width:100%!important;height:auto!important;
 min-width:0!important;min-height:0!important;max-height:none!important;
 overflow:hidden!important;align-items:stretch!important;gap:5px!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:not(:has(.ptt-live-panel)){display:block!important}
body.custom-session-watching:not(.single-ptt) .custom-player-column{
 display:flex;flex-direction:column;min-width:0;min-height:0;height:100%;max-height:100%;overflow:hidden
}
body.custom-session-watching:not(.single-ptt) #stage{
 width:100%;height:100%!important;min-height:0!important;max-height:100%!important;
 overflow:hidden!important;align-content:stretch!important;grid-auto-rows:minmax(0,1fr)!important
}
body.custom-session-watching:not(.single-ptt) #stage .player-card{
 min-width:0;min-height:0!important;height:100%;max-height:100%;overflow:hidden
}
body.custom-session-watching:not(.single-ptt) #stage .video-wrap{
 flex:1 1 0;min-width:0;min-height:0!important;height:auto!important;max-height:none!important;
 aspect-ratio:auto!important;overflow:hidden
}
body.custom-session-watching:not(.single-ptt) #stage .video-wrap iframe,
body.custom-session-watching:not(.single-ptt) #stage .video-wrap .player{
 width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important
}
body.custom-session-watching:not(.single-ptt) .ptt-live-panel{
 display:flex!important;flex-direction:column!important;min-width:0!important;min-height:0!important;
 width:100%;height:100%!important;max-height:100%!important;overflow:hidden!important;position:static!important
}
body.custom-session-watching:not(.single-ptt) .ptt-live-panel iframe,
body.custom-session-watching #ptt-worker-feed{
 flex:1 1 0!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
 overflow:auto!important
}
body.custom-session-watching.watch-grid .custom-content-grid:has(.ptt-live-panel){
 display:block!important;height:auto!important;min-height:0!important;overflow:hidden!important
}
body.custom-session-watching.watch-grid #stage:has(.ptt-live-panel){
 display:grid!important;
 grid-template-columns:repeat(var(--tile-columns,2),minmax(0,1fr))!important;
 grid-template-rows:repeat(var(--tile-rows,2),minmax(0,1fr))!important;
 grid-auto-rows:minmax(0,1fr)!important;height:100%!important;min-height:0!important;
 max-height:100%!important;overflow:hidden!important;align-content:stretch!important
}
body.custom-session-watching.watch-grid #stage .player-card,
body.custom-session-watching.watch-grid #stage .ptt-live-panel{
 grid-column:auto!important;grid-row:auto!important;height:100%!important;
 min-height:0!important;max-height:100%!important;overflow:hidden!important
}
body.custom-session-watching.watch-grid #stage .ptt-live-panel iframe{
 flex:1 1 0!important;height:auto!important;min-height:0!important;max-height:none!important
}
/* Immersive keeps the exact same fit rules, without nav or settings taking space. */
body.custom-session-watching.custom-immersive .client-main{
 margin:0!important;width:100vw!important;height:100dvh!important;max-height:100dvh!important;padding:0!important
}
body.custom-session-watching.custom-immersive .viewer-workspace{
 height:100dvh!important;max-height:100dvh!important;gap:0!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid{
 height:100%!important;min-height:0!important;max-height:100%!important;overflow:hidden!important
}
body.custom-session-watching.custom-immersive.watch-grid #stage:has(.ptt-live-panel){
 height:100%!important;grid-template-rows:repeat(var(--tile-rows,2),minmax(0,1fr))!important;overflow:hidden!important
}
/* Definite flex/grid height chain: prevents the single-player stage collapsing
   to a one-pixel row when PTT is beside (not inside) the stage. */
body.custom-session-watching:not(.single-ptt) .custom-content-grid{
 height:0!important;flex:1 1 0!important;min-height:0!important;
 grid-template-rows:minmax(0,1fr)!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel){
 display:grid!important;grid-template-rows:minmax(0,1fr)!important;
 align-items:stretch!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .custom-player-column{
 height:100%!important;min-height:0!important;min-width:0!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage{
 height:100%!important;min-height:0!important;grid-template-rows:minmax(0,1fr)!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage .player-card{
 height:100%!important;min-height:0!important;align-self:stretch!important
}
@media(max-width:760px){
 body.custom-session-watching .watch-actions{overflow-x:auto;overflow-y:hidden}
 body.custom-session-watching:not(.single-ptt) .custom-content-grid{grid-template-columns:minmax(0,1fr)!important;grid-template-rows:minmax(0,1fr)!important}
 body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel{display:none!important}
}

/* Final layout arbitration: prevent legacy auto rows from collapsing the
   default one/two-player layout after viewport-fit constraints are applied. */
body.custom-session-watching:not(.single-ptt):not(.watch-grid):not(.layout-primary) #stage:has(.ptt-live-panel){
 display:grid!important;
 grid-template-columns:repeat(var(--tile-columns,2),minmax(0,1fr))!important;
 grid-template-rows:repeat(var(--tile-rows,2),minmax(0,1fr))!important;
 grid-auto-rows:minmax(0,1fr)!important;
 height:100%!important;min-height:0!important;max-height:100%!important;
 overflow:hidden!important;align-content:stretch!important
}
body.custom-session-watching:not(.single-ptt):not(.watch-grid):not(.layout-primary) #stage > .player-card{
 grid-column:auto!important;grid-row:1!important;height:100%!important;
 min-height:0!important;max-height:100%!important;align-self:stretch!important
}
body.custom-session-watching:not(.single-ptt):not(.watch-grid):not(.layout-primary) #stage > .ptt-live-panel{
 grid-column:1 / -1!important;grid-row:2!important;height:100%!important;
 min-height:0!important;max-height:100%!important;overflow:hidden!important
}
body.custom-session-watching:not(.single-ptt):not(.watch-grid):not(.layout-primary) #stage .ptt-live-panel iframe{
 height:auto!important;min-height:0!important;max-height:none!important;flex:1 1 0!important
}
/* Focus layout remains independent of the equal-grid preset: main stream spans
   the left side; secondary streams and PTT fill successive right-side rows. */
body.custom-session-watching:not(.single-ptt).layout-primary #stage:has(.ptt-live-panel){
 display:grid!important;grid-template-columns:minmax(0,2.25fr) minmax(200px,.9fr)!important;
 grid-template-rows:none!important;grid-auto-rows:minmax(0,1fr)!important;
 height:100%!important;min-height:0!important;max-height:100%!important;
 overflow:hidden!important;align-content:stretch!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .player-card.primary{
 grid-column:1!important;grid-row:1 / span calc(var(--side-count,1) + 1)!important;
 height:100%!important;min-height:0!important;max-height:100%!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .player-card:not(.primary){
 grid-column:2!important;grid-row:auto!important;height:100%!important;min-height:0!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .ptt-live-panel{
 grid-column:2!important;grid-row:auto!important;height:100%!important;min-height:0!important;max-height:100%!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage .ptt-live-panel iframe{
 height:auto!important;min-height:0!important;max-height:none!important;flex:1 1 0!important
}
/* Single player with PTT beside it: the player must have an actual fill height. */
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .custom-player-column,
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage{
 height:100%!important;min-height:0!important;max-height:100%!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage > .player-card{
 grid-column:1!important;grid-row:1!important;width:100%!important;height:100%!important;
 min-height:0!important;max-height:100%!important
}
/* Single-player live/VOD: PTT is a side rail, never a second stage row.
   Immersive removes chrome, so the video must grow to the full remaining viewport. */
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage:has(> .player-card:only-child){
 display:grid!important;grid-template-columns:minmax(0,1fr)!important;
 grid-template-rows:minmax(0,1fr)!important;height:100%!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage:has(> .player-card:only-child) > .player-card{
 grid-column:1!important;grid-row:1!important;height:100%!important;min-height:0!important
}
body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage:has(> .player-card:only-child) .video-wrap{
 flex:1 1 0!important;height:100%!important;min-height:0!important;max-height:none!important;aspect-ratio:auto!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel){
 display:grid!important;grid-template-columns:minmax(0,1fr) minmax(360px,34vw)!important;
 grid-template-rows:minmax(0,1fr)!important;height:100%!important;min-height:0!important
}
/* In immersive mode the grid already lives inside the definite 100dvh workspace.
   Children must fill that remaining grid track, not request another 100dvh and
   compete with the translation/player chrome. */
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) .custom-player-column,
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) #stage,
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) #stage > .player-card,
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel{
 height:100%!important;max-height:100%!important;min-height:0!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) #stage > .player-card .video-wrap{
 flex:1 1 0!important;height:auto!important;min-height:0!important;max-height:none!important;aspect-ratio:auto!important
}
body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid:has(> .ptt-live-panel) #ptt-worker-feed{
 flex:1 1 0!important;height:auto!important;min-height:0!important;max-height:none!important
}
body.custom-session-watching.watch-grid #stage:has(.ptt-live-panel){
 grid-template-columns:repeat(var(--tile-columns,2),minmax(0,1fr))!important;
 grid-template-rows:repeat(var(--tile-rows,2),minmax(0,1fr))!important;
 grid-auto-rows:minmax(0,1fr)!important
}
body.custom-session-watching.watch-grid #stage > .player-card,
body.custom-session-watching.watch-grid #stage > .ptt-live-panel{
 grid-column:auto!important;grid-row:auto!important
}
body.custom-session-watching.watch-grid #stage .video-wrap{
 aspect-ratio:auto!important;flex:1 1 0;min-height:0!important
}
/* Re-assert Focus after the equal-grid tile auto-placement overrides. */
body.custom-session-watching:not(.single-ptt).layout-primary #stage:has(.ptt-live-panel){
 grid-template-columns:minmax(0,2.25fr) minmax(200px,.9fr)!important;
 grid-template-rows:none!important;grid-auto-rows:minmax(0,1fr)!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .player-card.primary{
 grid-column:1!important;grid-row:1 / span calc(var(--side-count,1) + 1)!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .player-card:not(.primary){
 grid-column:2!important;grid-row:auto!important
}
body.custom-session-watching:not(.single-ptt).layout-primary #stage > .ptt-live-panel{
 grid-column:2!important;grid-row:auto!important
}
.ptt-unavailable{padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:#fff8e8;color:#715f31;font-size:12px}
@media(max-width:760px){
  #stage,body.layout-primary #stage{grid-template-columns:1fr!important}
  body.layout-primary .player-card.primary,body.layout-primary .player-card:not(.primary){grid-column:1;grid-row:auto}
  .player-status{display:none}.player-controls{grid-template-columns:1fr}.player-actions{justify-content:flex-start}
}
 /* Narrow screens: stack each live stream vertically, with PTT as the next tile. */
 @media(max-width:760px){
  body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel){
   display:grid!important;grid-template-columns:minmax(0,1fr)!important;
   grid-template-rows:minmax(0,1fr) minmax(0,1fr)!important
  }
  body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .custom-player-column{height:100%!important;min-height:0!important}
  body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) .ptt-live-panel{
   display:flex!important;grid-column:1!important;grid-row:2!important;
   height:100%!important;min-height:0!important;max-height:100%!important
  }
  body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(> .ptt-live-panel) #stage{
   display:grid!important;grid-template-columns:minmax(0,1fr)!important;
   grid-template-rows:minmax(0,1fr)!important;height:100%!important;
   min-height:0!important;overflow:hidden!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage{
   display:grid!important;grid-template-columns:minmax(0,1fr)!important;
   grid-template-rows:repeat(var(--tile-count,3),minmax(0,1fr))!important;
   grid-auto-rows:minmax(0,1fr)!important;height:100%!important;
   min-height:0!important;max-height:100%!important;overflow:hidden!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage > .player-card,
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage > .ptt-live-panel{
   grid-column:1!important;grid-row:auto!important;
   height:100%!important;min-height:0!important;max-height:100%!important;
   width:100%!important;overflow:hidden!important;align-self:stretch!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .video-wrap{
   height:auto!important;min-height:0!important;max-height:none!important;
   aspect-ratio:auto!important;flex:1 1 0!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .video-wrap iframe,
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .video-wrap .player{
   height:100%!important;width:100%!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-live-panel{
   display:flex!important;flex-direction:column!important;min-height:0!important
  }
  body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage .ptt-live-panel iframe{
   flex:1 1 0!important;height:auto!important;min-height:0!important;max-height:none!important
  }
}
/* Highest-specificity responsive override: legacy .layout-auto/.layout-equal
   desktop selectors otherwise win over the earlier narrow-screen rules. */
@media(max-width:1024px){
 /* Use the full post-rail width. At tablet/portrait sizes a desktop PTT column
    must not reserve 220px beside a narrow player column. */
 body.custom-session-watching:not(.single-ptt) .client-main{
  box-sizing:border-box!important;
  width:calc(100vw - var(--rail-collapsed,72px) - var(--watch-rail,64px))!important;
  max-width:none!important;min-width:0!important
 }
 body.custom-session-watching:not(.single-ptt) .custom-content-grid:has(#stage .ptt-live-panel){
  display:block!important;width:100%!important;min-width:0!important
 }
 body.custom-session-watching:not(.single-ptt) .custom-player-column{
  width:100%!important;max-width:100%!important;min-width:0!important
 }
 body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage,
 body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage,
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage,
 body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage{
  display:grid!important;grid-template-columns:minmax(0,1fr)!important;
  grid-template-rows:repeat(var(--tile-count,3),minmax(0,1fr))!important;
  grid-auto-rows:minmax(0,1fr)!important;height:100%!important;
  min-height:0!important;max-height:100%!important;overflow:hidden!important
 }
 body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage > .player-card,
 body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage > .player-card,
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage > .player-card,
 body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage > .player-card,
 body.custom-session-watching:not(.single-ptt):has(.ptt-live-panel) #stage > .ptt-live-panel{
  grid-column:1!important;grid-row:auto!important;width:100%!important;
  height:100%!important;min-height:0!important;max-height:100%!important;
  align-self:stretch!important;overflow:hidden!important
 }
 body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage .video-wrap,
 body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage .video-wrap,
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .video-wrap{
  aspect-ratio:auto!important;max-height:none!important;min-height:0!important;flex:1 1 0!important
 }
 body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage .ptt-live-panel,
 body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage .ptt-live-panel,
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel{
  grid-column:1!important;grid-row:auto!important;display:flex!important;
  flex-direction:column!important;height:100%!important;min-height:0!important;max-height:100%!important
 }
 body.custom-session-watching:not(.single-ptt).layout-auto:has(.ptt-live-panel) #stage .ptt-live-panel iframe,
 body.custom-session-watching:not(.single-ptt).layout-equal:has(.ptt-live-panel) #stage .ptt-live-panel iframe,
 body.custom-session-watching:not(.single-ptt).layout-primary:has(.ptt-live-panel) #stage .ptt-live-panel iframe{
  flex:1 1 0!important;height:auto!important;min-height:0!important;max-height:none!important
 }
}

/* Narrow RWD: exactly two videos stack at full width rather than squeezing
   the secondary player into the desktop Focus column. Let the page scroll so
   both 16:9 players retain their natural width and height. */
@media(max-width:1024px){
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) .custom-content-grid{
  display:grid!important;grid-template-columns:minmax(0,1fr)!important;grid-template-rows:auto auto!important;
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  overflow:visible!important;gap:6px!important
 }
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) .custom-player-column,
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) #stage,
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) #stage > .player-card{
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important
 }
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) #stage .video-wrap{
  width:100%!important;height:auto!important;aspect-ratio:16/9!important;max-height:none!important
 }
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) .ptt-live-panel{
  display:flex!important;flex-direction:column!important;position:static!important;
  width:100%!important;height:55vh!important;min-height:320px!important;max-height:none!important;overflow:hidden!important
 }
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) .ptt-live-panel iframe,
 body.custom-session-watching:not(.single-ptt):has(#stage > .player-card:only-child):has(.ptt-live-panel) #ptt-worker-feed{
  flex:1 1 0!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important
 }
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .client-rail,
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .live-channel-rail{
  display:none!important
 }
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .client-topbar{
  display:flex!important;margin:0!important;width:100%!important;height:52px;padding:0 12px
 }
 html:has(body.custom-session-watching #stage > .player-card:nth-child(2)):not(:has(body.custom-session-watching #stage > .player-card:nth-child(3))),
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))){
  width:100%!important;height:auto!important;min-height:100%!important;max-height:none!important;
  overflow-x:hidden!important;overflow-y:auto!important
 }
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .client-main{
  box-sizing:border-box;margin:0!important;width:100vw!important;height:auto!important;
  min-height:0!important;max-height:none!important;padding:4px!important;overflow:visible!important
 }
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .viewer-workspace{
  height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important
 }
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .custom-content-grid,
 body.custom-session-watching:has(#stage > .player-card:nth-child(2)):not(:has(#stage > .player-card:nth-child(3))) .custom-player-column{
  display:block!important;flex:none!important;width:100%!important;height:auto!important;
  min-height:0!important;max-height:none!important;overflow:visible!important
 }
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))){
  display:grid!important;grid-template-columns:minmax(0,1fr)!important;
  grid-template-rows:none!important;grid-auto-rows:auto!important;
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  overflow:visible!important;align-content:start!important;gap:8px!important
 }
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))) > .player-card{
  grid-column:1!important;grid-row:auto!important;width:100%!important;height:auto!important;
  min-width:0!important;min-height:0!important;max-height:none!important;align-self:start!important
 }
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))) > .player-card .video-wrap{
  flex:none!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  aspect-ratio:16/9!important
 }
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))) > .player-card .video-wrap iframe,
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))) > .player-card .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important
 }
 body.custom-session-watching #stage:has(> .player-card:nth-child(2)):not(:has(> .player-card:nth-child(3))) > .ptt-live-panel{
  grid-column:1!important;grid-row:auto!important;width:100%!important;height:60vh!important;
  min-height:340px!important;max-height:none!important;overflow:hidden!important
 }
}


/* 4174 final single-player + PTT arbitration.
   This is the sole desktop authority for single Live/VOD + PTT.  Normal mode
   is width-driven 16:9 and never inherits a viewport/percentage height chain;
   immersive mode alone owns the definite 100dvh chain. */
@media(min-width:1025px){
 html:has(body.custom-session-watching.single-ptt:not(.custom-immersive)){
  height:auto!important;min-height:100%!important;max-height:none!important;overflow-y:auto!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive){
  height:auto!important;min-height:100vh!important;max-height:none!important;overflow-y:auto!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .client-main,
 body.custom-session-watching.single-ptt:not(.custom-immersive) .viewer-workspace{
  height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .custom-content-grid{
  display:grid!important;grid-template-columns:minmax(0,1fr) minmax(320px,var(--ptt-width,28%))!important;
  grid-template-rows:auto!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  flex:none!important;align-items:start!important;overflow:visible!important;gap:6px!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .custom-player-column,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card{
  display:block!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  align-self:start!important;overflow:visible!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap{
  display:block!important;position:relative!important;flex:none!important;
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;aspect-ratio:16/9!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;max-width:100%!important;max-height:100%!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .ptt-live-panel{
  position:static!important;display:flex!important;flex-direction:column!important;align-self:start!important;
  width:100%!important;height:calc(100dvh - 48px)!important;min-height:320px!important;max-height:none!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .ptt-live-panel iframe,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #ptt-worker-feed{
  flex:1 1 auto!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:auto!important
 }

 body.custom-session-watching.single-ptt.custom-immersive .client-main,
 body.custom-session-watching.single-ptt.custom-immersive .viewer-workspace,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid{
  height:100dvh!important;min-height:0!important;max-height:100dvh!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid{
  display:grid!important;grid-template-columns:minmax(0,1fr) minmax(320px,var(--ptt-width,28%))!important;
  grid-template-rows:minmax(0,1fr)!important;align-items:stretch!important;gap:2px!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column,
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage > .player-card,
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel{
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;max-height:100%!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage > .player-card{
  display:flex!important;flex-direction:column!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap{
  position:relative!important;flex:0 1 auto!important;width:min(100%,calc(100dvh * 16 / 9))!important;
  height:auto!important;min-height:0!important;max-height:100%!important;aspect-ratio:16/9!important;align-self:center!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel{
  display:flex!important;flex-direction:column!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed:not([hidden]){
  flex:1 1 0!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:auto!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-worker-clock{display:block!important}
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed:not(.ptt-worker-hide-floor) .ptt-worker-floor{display:block!important}
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed .ptt-worker-row{
  grid-template-columns:1.3em 4.1em 3.4em minmax(0,1fr)!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-row{
  grid-template-columns:1.3em 4.1em minmax(0,1fr)!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-floor{display:none!important}
}
/* Single-player viewport ownership: the shared shell normally caps
   .client-main to --content + rail.  Watching must not inherit that desktop
   document width; otherwise the video/PTT pair is centered inside grey gutters. */
@media(min-width:1025px){
 body.custom-session-watching.single-ptt .client-main{
  box-sizing:border-box!important;max-width:none!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .client-main,
 body.custom-session-watching.single-ptt.custom-immersive .viewer-workspace,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid{
  left:0!important;right:0!important;margin-left:0!important;margin-right:0!important;
  width:100%!important;max-width:none!important
 }
}

/* Final immersive single-player authority.
   Immersive is true browser fullscreen: no app/navigation rails survive, and
   the player column fills the available height while preserving 16:9. */
@media(min-width:1025px){
 html:has(body.custom-session-watching.single-ptt.custom-immersive),
 body.custom-session-watching.single-ptt.custom-immersive{
  width:100vw!important;height:100dvh!important;min-height:100dvh!important;max-height:100dvh!important;
  margin:0!important;padding:0!important;overflow:hidden!important;background:#080808!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .client-rail,
 body.custom-session-watching.single-ptt.custom-immersive .live-channel-rail,
 body.custom-session-watching.single-ptt.custom-immersive .client-sidebar,
 body.custom-session-watching.single-ptt.custom-immersive .channel-rail,
 body.custom-session-watching.single-ptt.custom-immersive .avatar-rail,
 body.custom-session-watching.single-ptt.custom-immersive .sidebar,
 body.custom-session-watching.single-ptt.custom-immersive .left-rail,
 body.custom-session-watching.single-ptt.custom-immersive .client-topbar,
 body.custom-session-watching.single-ptt.custom-immersive #mobileNav{
  display:none!important;width:0!important;min-width:0!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .client-main{
  position:fixed!important;inset:0!important;margin:0!important;padding:0!important;
  width:100vw!important;height:100dvh!important;max-width:none!important;max-height:100dvh!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .viewer-workspace,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid{
  width:100vw!important;height:100dvh!important;max-width:none!important;max-height:100dvh!important;
  margin:0!important;padding:0!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid{
  /* Anchor the actual video/PTT surface to the viewport itself.  This bypasses
     every centered/max-width shell ancestor; 72/28 then matches the familiar
     YouTube video + chat geometry instead of applying inside a narrow island. */
  position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:0!important;z-index:80!important;
  display:grid!important;
  grid-template-columns:minmax(0,min(calc(100dvh * 16 / 9),calc(100vw - 320px))) minmax(320px,1fr)!important;
  grid-template-rows:minmax(0,1fr)!important;
  box-sizing:border-box!important;width:100vw!important;height:100dvh!important;max-width:100vw!important;max-height:100dvh!important;
  margin:0!important;padding:0!important;gap:2px!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column,
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card{
  display:flex!important;flex-direction:column!important;width:100%!important;height:100%!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:100%!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap{
  position:absolute!important;inset:0 0 0 0!important;
  display:block!important;flex:none!important;
  width:100%!important;height:100%!important;min-height:0!important;max-height:100%!important;
  margin:0!important;padding:0!important;aspect-ratio:16/9!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card{
  position:relative!important;padding:0!important;margin:0!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card>.player-meta,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card>.player-controls{
  position:absolute!important;left:0!important;right:0!important;bottom:0!important;z-index:4!important;
  margin:0!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
  max-width:none!important;max-height:none!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card>.player-controls{
  flex:0 0 auto!important
 }
}

/* Final desktop single + PTT immersive authority.
   The fullscreen surface is only two boxes: video and PTT.  The player fills
   the video box; no centering/aspect-ratio wrapper is allowed to create
   top/bottom gutters. */
@media(min-width:1025px){
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid:fullscreen{
  position:fixed!important;inset:0!important;z-index:80!important;
  display:grid!important;
  /* A YouTube iframe must itself be 16:9.  Stretching a narrower iframe to
     100dvh only makes YouTube letterbox inside it (the two black bars the
     acceptance screenshot exposed).  Give the player exactly the width that
     corresponds to the fullscreen height; PTT receives the remainder. */
  /* Keep the 16:9 player flush left.  Reserve a real PTT rail instead of
     letting the player consume the entire viewport when 100dvh*16/9 is wider
     than the available video column. */
  grid-template-columns:minmax(0,min(calc(100dvh * 16 / 9),calc(100vw - 320px))) minmax(320px,1fr)!important;
  grid-template-rows:100dvh!important;
  width:100vw!important;height:100dvh!important;min-width:100vw!important;min-height:100dvh!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  gap:2px!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column,
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card{
  position:relative!important;display:block!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  aspect-ratio:auto!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100%!important;min-width:100%!important;min-height:100%!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;border:0!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel{
  position:relative!important;inset:auto!important;display:flex!important;flex-direction:column!important;
  width:100%!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;border-radius:0!important;
  overflow:hidden!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching.single-ptt.custom-immersive #ptt-worker-feed:not([hidden]){
  width:100%!important;height:100%!important;min-height:0!important;max-height:none!important
 }
}

/* Single immersive DOM authority: CSS immersive remains valid even when
   browser fullscreen is not active. Keep the PTT node visible beside one player. */
@media(min-width:901px){
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child){
  position:fixed!important;inset:0!important;z-index:80!important;display:grid!important;
  grid-template-columns:minmax(0,min(calc(100dvh * 16 / 9),calc(100vw - 320px))) minmax(320px,1fr)!important;
  grid-template-rows:100dvh!important;width:100vw!important;height:100dvh!important;
  min-width:100vw!important;min-height:100dvh!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;gap:2px!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child) #stage,
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child) #stage>.player-card{
  position:relative!important;display:block!important;width:100%!important;height:100%!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;overflow:hidden!important
 }
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child) .video-wrap{
  position:absolute!important;inset:0!important;display:block!important;width:100%!important;height:100%!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;aspect-ratio:auto!important
 }
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child) .video-wrap iframe,
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child) .video-wrap .player{
  position:absolute!important;inset:0!important;display:block!important;width:100%!important;height:100%!important;
  max-width:none!important;max-height:none!important
 }
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child)>.ptt-live-panel{
  position:relative!important;inset:auto!important;display:flex!important;visibility:visible!important;
  flex-direction:column!important;width:100%!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;opacity:1!important;
  overflow:hidden!important;border:0!important;border-radius:0!important
 }
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child)>.ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching.custom-immersive .custom-content-grid:has(> .ptt-live-panel):has(#stage > .player-card:only-child)>.ptt-live-panel #ptt-worker-feed:not([hidden]){
  display:block!important;visibility:visible!important;flex:1 1 0!important;width:100%!important;height:100%!important;
  min-height:0!important;max-height:none!important;opacity:1!important;overflow:auto!important
 }
}

/* 4174 single immersive viewport model.
   Keep the YouTube surface at a real 16:9 viewport-sized box so the iframe
   never invents top/bottom letterboxing.  PTT is a persistent right overlay:
   this is the only geometry that can maximize a 16:9 video vertically while
   keeping a useful chat rail on a normal desktop viewport. */
@media(min-width:1025px){
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid:fullscreen{
  position:fixed!important;inset:0!important;display:block!important;
  width:100vw!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column{
  position:absolute!important;inset:0!important;display:flex!important;
  align-items:center!important;justify-content:flex-start!important;
  width:100vw!important;height:100dvh!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card{
  position:relative!important;display:block!important;
  width:min(100vw,calc(100dvh * 16 / 9))!important;
  height:min(100dvh,calc(100vw * 9 / 16))!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  aspect-ratio:16/9!important;border:0!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card>.player-controls{
  display:none!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel{
  position:absolute!important;top:0!important;right:0!important;bottom:0!important;z-index:90!important;
  display:flex!important;visibility:visible!important;flex-direction:column!important;
  width:clamp(320px,22vw,420px)!important;height:100dvh!important;
  min-width:320px!important;min-height:0!important;max-width:420px!important;max-height:none!important;
  margin:0!important;padding:0!important;opacity:1!important;overflow:hidden!important;
  border:0!important;border-left:1px solid #252525!important;border-radius:0!important;
  background:var(--surface,#111)!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel #ptt-worker-feed:not([hidden]){
  display:block!important;visibility:visible!important;flex:1 1 0!important;
  width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;
  opacity:1!important;overflow:auto!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel [hidden]{
  display:none!important;visibility:hidden!important
 }
 /* The previous rule sized #stage to a 16:9 box, then absolutely filled it.
    On a 16:9 desktop viewport that should reach the bottom, but legacy stage/card
    sizing can still win through intrinsic grid height. Make the immersive video
    box itself own the full viewport height; its width follows 16:9. */
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card{
  position:absolute!important;top:0!important;left:0!important;bottom:0!important;
  width:min(100vw,calc(100dvh * 16 / 9))!important;height:100dvh!important;
  min-width:0!important;min-height:100dvh!important;max-width:none!important;max-height:100dvh!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
  min-width:100%!important;min-height:100%!important;max-width:none!important;max-height:none!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .translation-slot{display:none!important}
}

/* 4174 immersive acceptance override.
   The fullscreen element is .custom-content-grid itself. Rules that only hide
   rails through body descendants cannot affect shell siblings outside that
   fullscreen subtree. Hide those siblings whenever the document owns a
   fullscreen custom-view surface, and make the video surface consume the
   viewport below/behind no legacy player controls. */
html:has(.custom-content-grid:fullscreen) .client-rail,
html:has(.custom-content-grid:fullscreen) .live-channel-rail,
html:has(.custom-content-grid:fullscreen) .client-sidebar,
html:has(.custom-content-grid:fullscreen) .channel-rail,
html:has(.custom-content-grid:fullscreen) .avatar-rail,
html:has(.custom-content-grid:fullscreen) .sidebar,
html:has(.custom-content-grid:fullscreen) .left-rail,
html:has(.custom-content-grid:fullscreen) .client-topbar,
html:has(.custom-content-grid:fullscreen) #mobileNav{
 display:none!important;visibility:hidden!important;width:0!important;min-width:0!important
}
@media(min-width:1025px){
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid:fullscreen{
  position:fixed!important;inset:0!important;display:grid!important;
  grid-template-columns:minmax(0,1fr) clamp(320px,24vw,420px)!important;
  grid-template-rows:100dvh!important;width:100vw!important;height:100dvh!important;
  margin:0!important;padding:0!important;gap:0!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column{
  position:relative!important;inset:auto!important;display:block!important;
  width:100%!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  margin:0!important;padding:0!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100dvh!important;min-width:100%!important;min-height:100dvh!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  border:0!important;aspect-ratio:auto!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card>.player-controls{
  display:none!important;visibility:hidden!important;height:0!important;min-height:0!important;
  margin:0!important;padding:0!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel{
  position:relative!important;inset:auto!important;grid-column:2!important;grid-row:1!important;
  display:flex!important;visibility:visible!important;flex-direction:column!important;
  width:100%!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  opacity:1!important;overflow:hidden!important;border-radius:0!important
 }
}

/* 4174 single immersive tuning surface.
   Keep the shell out of immersive geometry.  The two owner-facing knobs are
   --immersive-ptt-width and --immersive-player-max-width; they can be edited
   live in DevTools on .custom-content-grid while we tune acceptance. */
@media(min-width:1025px){
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid,
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid:fullscreen{
  --immersive-ptt-width:clamp(320px,24vw,420px);
  --immersive-player-max-width:none;
  position:fixed!important;inset:0!important;
  display:grid!important;
  grid-template-columns:minmax(0,1fr) var(--immersive-ptt-width)!important;
  grid-template-rows:100%!important;
  width:100vw!important;height:100dvh!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;gap:0!important;
  overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-player-column{
  position:relative!important;inset:auto!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:var(--immersive-player-max-width)!important;
  margin:0!important;padding:0!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching.single-ptt.custom-immersive #stage,
 body.custom-session-watching.single-ptt.custom-immersive #stage>.player-card,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt.custom-immersive #stage .video-wrap .player{
  position:absolute!important;inset:0!important;
  display:block!important;width:100%!important;height:100%!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;padding:0!important;border:0!important;aspect-ratio:auto!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .custom-content-grid>.ptt-live-panel{
  position:relative!important;inset:auto!important;grid-column:2!important;grid-row:1!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important
 }
}

/* Absolute final PTT child authority for single immersive.
   Only the active live/archive surface may participate in layout; hidden
   siblings must consume zero space. */
@media(min-width:901px){
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel{
  display:flex!important;flex-direction:column!important;background:#080808!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel > iframe:not([hidden]),
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel > #ptt-worker-feed:not([hidden]){
  position:relative!important;inset:auto!important;display:block!important;visibility:visible!important;
  flex:1 1 0!important;width:100%!important;height:100%!important;min-height:0!important;max-height:none!important;
  margin:0!important;padding:0!important;opacity:1!important;overflow:auto!important
 }
 body.custom-session-watching.single-ptt.custom-immersive .ptt-live-panel > [hidden]{
  display:none!important;visibility:hidden!important;flex:0 0 0!important;
  width:0!important;height:0!important;min-width:0!important;min-height:0!important;
  margin:0!important;padding:0!important;border:0!important;overflow:hidden!important
 }
}

/* Final narrow single-player authority.  The desktop arbitration above is
   intentionally min-width:1025px; without this block old generic RWD rules
   can reintroduce fill-height/aspect-ratio:auto behavior on tablets/phones. */
@media(max-width:1024px){
 html:has(body.custom-session-watching.single-ptt){
  height:auto!important;min-height:100%!important;max-height:none!important;overflow-x:hidden!important;overflow-y:auto!important
 }
 body.custom-session-watching.single-ptt{
  width:100%!important;height:auto!important;min-height:100vh!important;max-height:none!important;
  overflow-x:hidden!important;overflow-y:auto!important
 }
 body.custom-session-watching.single-ptt .client-main{
  box-sizing:border-box!important;width:100%!important;height:auto!important;min-height:0!important;
  max-height:none!important;margin:0!important;padding:4px!important;overflow:visible!important
 }
 body.custom-session-watching.single-ptt .viewer-workspace,
 body.custom-session-watching.single-ptt .custom-player-column,
 body.custom-session-watching.single-ptt #stage,
 body.custom-session-watching.single-ptt #stage > .player-card{
  display:block!important;width:100%!important;height:auto!important;min-height:0!important;
  max-height:none!important;overflow:visible!important
 }
 body.custom-session-watching.single-ptt .custom-content-grid{
  display:grid!important;grid-template-columns:minmax(0,1fr)!important;grid-template-rows:auto auto!important;
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;
  flex:none!important;align-items:start!important;overflow:visible!important;gap:6px!important
 }
 body.custom-session-watching.single-ptt #stage .video-wrap{
  display:block!important;position:relative!important;flex:none!important;width:100%!important;height:auto!important;
  min-height:0!important;max-height:none!important;aspect-ratio:16/9!important
 }
 body.custom-session-watching.single-ptt #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt #stage .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
  max-width:100%!important;max-height:100%!important
 }
 body.custom-session-watching.single-ptt .ptt-live-panel{
  display:flex!important;flex-direction:column!important;position:static!important;grid-column:1!important;grid-row:2!important;
  width:100%!important;height:55vh!important;min-height:320px!important;max-height:none!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt .ptt-live-panel iframe,
 body.custom-session-watching.single-ptt #ptt-worker-feed{
  flex:1 1 auto!important;width:100%!important;height:auto!important;min-height:0!important;max-height:none!important;overflow:auto!important
 }
 body.custom-session-watching.single-ptt #ptt-worker-feed .ptt-worker-row{
  grid-template-columns:1.3em 4.1em 3.4em minmax(0,1fr)!important
 }
 body.custom-session-watching.single-ptt #ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-row{
  grid-template-columns:1.3em 4.1em minmax(0,1fr)!important
 }
 body.custom-session-watching.single-ptt #ptt-worker-feed.ptt-worker-hide-floor .ptt-worker-floor{display:none!important}
}



/* Final multi-view immersive authority.
   Multi-view PTT is mounted inside #stage. In immersive mode the stage owns
   the whole viewport; every player tile and the PTT tile receives a definite
   grid area instead of inheriting the earlier auto/max-content rows that can
   collapse the YouTube iframes to nearly zero height. */
@media(min-width:761px){
 body.custom-session-watching:not(.single-ptt).custom-immersive .custom-content-grid{
  position:fixed!important;inset:0!important;display:block!important;
  width:100vw!important;height:100dvh!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive .custom-player-column{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  overflow:hidden!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage{
  position:absolute!important;inset:0!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;padding:0!important;
  gap:4px!important;overflow:hidden!important;align-items:stretch!important;align-content:stretch!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-auto #stage,
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-equal #stage{
  display:grid!important;
  grid-template-columns:repeat(var(--tile-columns,2),minmax(0,1fr))!important;
  grid-template-rows:repeat(var(--tile-rows,2),minmax(0,1fr))!important;
  grid-auto-rows:minmax(0,1fr)!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage{
  display:grid!important;
  grid-template-columns:minmax(0,2.25fr) minmax(260px,.9fr)!important;
  grid-template-rows:repeat(3,minmax(0,1fr))!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)){
  /* Keep the side player on one unchanged Focus slot; PTT spans two slots. */
  grid-template-rows:repeat(3,minmax(0,1fr))!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .player-card.primary{
  grid-row:1 / 4!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .ptt-live-panel{
  grid-row:2 / 4!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage .player-card.primary{
  grid-column:1!important;grid-row:1 / 4!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage .player-card.focus-side-1{
  grid-column:2!important;grid-row:1!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage .player-card.focus-side-2{
  grid-column:2!important;grid-row:2!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage .player-card.focus-hidden{
  display:none!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive.layout-primary #stage .ptt-live-panel{
  grid-column:2!important;grid-row:3!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .player-card,
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .ptt-live-panel{
  position:relative!important;width:100%!important;height:100%!important;
  min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;
  margin:0!important;overflow:hidden!important;align-self:stretch!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .player-card{
  display:flex!important;flex-direction:column!important;background:#000!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .video-wrap{
  position:relative!important;display:block!important;flex:1 1 0!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;margin:0!important;
  aspect-ratio:auto!important;overflow:hidden!important;background:#000!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .video-wrap .player,
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .video-wrap iframe{
  position:absolute!important;inset:0!important;display:block!important;
  width:100%!important;height:100%!important;min-width:0!important;min-height:0!important;
  max-width:none!important;max-height:none!important;border:0!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .player-controls{
  display:none!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .ptt-live-panel{
  display:flex!important;flex-direction:column!important;border-radius:0!important
 }
 /* Only the active PTT surface may take space. The inactive iframe/feed
    has a hidden attribute; never override it with display:block!important. */
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage #ptt-worker-feed:not([hidden]){
  display:block!important;flex:1 1 0!important;width:100%!important;height:100%!important;
  min-height:0!important;max-height:none!important;overflow:auto!important
 }
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage .ptt-live-panel iframe[hidden],
 body.custom-session-watching:not(.single-ptt).custom-immersive #stage #ptt-worker-feed[hidden]{
  display:none!important;flex:0 0 0!important;height:0!important;min-height:0!important
 }
}

/* A two-player Focus stage has one side video, not two. Collapse the unused
   second side-video row and place PTT directly beneath the actual side video.
   Keep the three-player layout and immersive geometry unchanged. */
@media(min-width:761px){
 body.custom-session-watching:not(.single-ptt):not(.custom-immersive).layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)){
  grid-template-rows:minmax(0,46fr) minmax(0,54fr)!important;
  grid-auto-rows:minmax(0,1fr)!important
 }
 body.custom-session-watching:not(.single-ptt):not(.custom-immersive).layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .player-card.primary{
  grid-row:1 / 3!important
 }
 body.custom-session-watching:not(.single-ptt):not(.custom-immersive).layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .player-card.focus-side-1{
  grid-column:2!important;grid-row:1!important;
  min-height:0!important;height:100%!important
 }
 body.custom-session-watching:not(.single-ptt):not(.custom-immersive).layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .player-card.focus-side-1 .video-wrap{
  flex:1 1 0!important;min-height:0!important;height:100%!important;
  max-height:none!important;aspect-ratio:auto!important
 }
 body.custom-session-watching:not(.single-ptt):not(.custom-immersive).layout-primary #stage:has(> .player-card:nth-child(2):nth-last-child(2)) > .ptt-live-panel{
  grid-column:2!important;grid-row:2!important
 }
}


/* Single LIVE/VOD normal mode: only the outer card owns the rounded frame.
   Clip the YouTube iframe at that same frame so square iframe corners cannot
   protrude behind the rounded controls/card. Immersive remains square. */
body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card{
 border-radius:14px!important;overflow:hidden!important
}
body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card .video-wrap{
 overflow:hidden!important;border-radius:13px 13px 0 0!important
}
body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card .video-wrap iframe,
body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card .video-wrap .player{
 border-radius:13px 13px 0 0!important
}

/* Single LIVE/VOD narrow viewport: restore the page scroll chain; the old
   @media(max-width:760px) fixed viewport / hidden overflow cropped both the
   player and PTT. This only governs the one-player normal viewing page. */
@media(max-width:1024px){
 html:has(body.custom-session-watching.single-ptt:not(.custom-immersive)),
 body.custom-session-watching.single-ptt:not(.custom-immersive){
  height:auto!important;min-height:100%!important;max-height:none!important;
  overflow-x:hidden!important;overflow-y:auto!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .client-main,
 body.custom-session-watching.single-ptt:not(.custom-immersive) .viewer-workspace{
  height:auto!important;min-height:0!important;max-height:none!important;
  overflow:visible!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .custom-content-grid{
  display:grid!important;grid-template-columns:minmax(0,1fr)!important;
  grid-template-rows:auto auto!important;width:100%!important;height:auto!important;
  min-height:0!important;max-height:none!important;align-items:start!important;
  overflow:visible!important;gap:6px!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .custom-player-column,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage{
  display:block!important;width:100%!important;height:auto!important;
  min-height:0!important;max-height:none!important;overflow:visible!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage > .player-card{
  display:flex!important;flex-direction:column!important;
  width:100%!important;height:auto!important;min-height:0!important;max-height:none!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap{
  display:block!important;position:relative!important;flex:none!important;
  width:100%!important;height:auto!important;min-height:0!important;
  max-height:none!important;aspect-ratio:16/9!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap iframe,
 body.custom-session-watching.single-ptt:not(.custom-immersive) #stage .video-wrap .player{
  position:absolute!important;inset:0!important;width:100%!important;height:100%!important;
  max-width:100%!important;max-height:100%!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .ptt-live-panel{
  display:flex!important;flex-direction:column!important;position:static!important;
  grid-column:1!important;grid-row:2!important;
  width:100%!important;height:clamp(320px,65dvh,720px)!important;
  min-height:320px!important;max-height:none!important;overflow:hidden!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .ptt-live-panel iframe:not([hidden]),
 body.custom-session-watching.single-ptt:not(.custom-immersive) #ptt-worker-feed:not([hidden]){
  display:block!important;flex:1 1 0!important;width:100%!important;height:auto!important;
  min-height:0!important;max-height:none!important;overflow:auto!important
 }
}


/* At phone widths the desktop navigation rail was forcibly re-shown by the
   watch page, and its fixed left margin squeezed/cropped the player and controls.
   Restore the shared Client mobile navigation and use the entire viewport. */
@media(max-width:760px){
 body.custom-session-watching.single-ptt:not(.custom-immersive) .client-rail,
 body.custom-session-watching.single-ptt:not(.custom-immersive) .live-channel-rail{
  display:none!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .client-topbar{
  display:flex!important;position:relative!important;top:auto!important;
  margin:0!important;width:100%!important;height:52px!important;
  min-height:52px!important;padding:0 12px!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .mobile-nav-button{
  display:block!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .client-main{
  box-sizing:border-box!important;margin:0!important;
  width:100%!important;max-width:none!important;
  padding:4px 8px 24px!important
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .watch-actions{
  display:flex!important;flex-wrap:nowrap!important;
  overflow-x:auto!important;overflow-y:hidden!important;
  max-width:100%!important;min-width:0!important;
  scrollbar-width:thin
 }
 body.custom-session-watching.single-ptt:not(.custom-immersive) .watch-actions > *{
  flex-shrink:0!important
 }
}

"""

    content = """
<div class="viewer-workspace">
  <div class="viewer-head">
    <h1>自訂觀看</h1>
    <a class="subtle-action" href="/custom-view">調整觀看清單</a>
  </div>
  <div class="watch-actions"><div class="watch-mode-switch" role="group" aria-label="觀看模式"><button type="button" id="watchSingleMode" aria-pressed="true">單人</button><button type="button" id="watchModeToggle" class="watch-mode-toggle" role="switch" aria-checked="false" aria-label="切換單人／多人模式"></button><button type="button" id="watchMultiMode" aria-pressed="false">多人</button></div><label class="global-volume-label">總音量 <input id="globalVolume" type="range" min="0" max="100" value="100" aria-label="所有視角總音量"><output id="globalVolumeValue">100%%</output></label><button type="button" id="watchSettings" aria-expanded="false">設定</button><button type="button" id="watchImmersive">沉浸模式</button></div><label class="immersive-global-volume">總音量 <input id="immersiveGlobalVolume" type="range" min="0" max="100" value="100" aria-label="沉浸模式總音量"><output id="immersiveGlobalVolumeValue">100%%</output></label><div class="player-toolbar">
    <div class="custom-immersive-controls"><button type="button" id="customImmerse" aria-pressed="false">沉浸模式</button></div>
    <label class="player-sync-label" id="videoHeightLabel">播放器高度上限 <input id="videoHeight" type="range" min="360" max="1000" step="40" value="1000"><output id="videoHeightValue">1000px</output></label>
    <button data-layout="auto">自動</button>
    <button data-layout="equal">平均排列</button>
    <button data-layout="primary">主視角</button>
    <span id="focusChoices" class="focus-choices" aria-label="切換主視角"></span>
    <button type="button" id="focusCarousel">輪播 10s</button>
    <label class="player-sync-label" id="focusCarouselIntervalLabel">間隔 <input id="focusCarouselInterval" type="range" min="10" max="60" step="5" value="10"><output id="focusCarouselIntervalOutput">10 秒</output></label>
    <label class="player-sync-label" id="audioFollowLabel"><input id="audioFollowFocus" type="checkbox"> 聲音跟隨主視角</label>
    <label class="player-sync-label" id="playerSyncLabel"><input id="syncPlayback" type="checkbox"> 連動播放／暫停</label>
    <label class="player-sync-label" id="manualTimelineLabel" hidden><input id="manualTimelineAlign" type="checkbox"> 依開播時間自動對齊</label>
    <button type="button" id="playAll" disabled>全部播放</button>
    <button type="button" id="pauseAll" disabled>全部暫停</button>
    <span id="status" class="player-status">載入播放器…</span>
  </div>
  <div class="custom-content-grid%s"><div class="custom-player-column"><main id="stage"></main><div class="translation-slot" id="translationSlot" aria-label="VOD 翻譯字幕"{translation_hidden}><div class="translation-track-controls"><button type="button" id="translationA">A方案</button><button type="button" id="translationB">B方案</button></div><div id="translationStatus" class="note">{translation_initial_status}</div><div id="translationText" class="translation-text"></div></div></div>%s</div>
</div>
"""

    content = content % (" video-only" if not show_live_ptt else "", ptt_panel)
    content = content.replace("{translation_hidden}", translation_hidden)
    content = content.replace("{translation_prepare_hidden}", translation_prepare_hidden)
    content = content.replace("{translation_initial_status}", escape(translation_initial_status))
    script = f"""
const streams={payload};
const singlePttKind={json.dumps("vod" if show_live_ptt and ptt_worker_config and ptt_worker_config.get("mode") == "archive" else ("live" if show_live_ptt else ""))};
function syncSessionCardinalityClasses(){{
 const single=streams.length===1;
 document.body.classList.toggle('single-ptt',single&&Boolean(singlePttKind));
 document.body.classList.toggle('single-live',single&&singlePttKind==='live');
 document.body.classList.toggle('single-vod',single&&singlePttKind==='vod');
}}
syncSessionCardinalityClasses();
const translationTracks={{A:{translation_a_json},B:{translation_b_json}}};
let activeTranslationTrack=translationTracks.A.length?'A':(translationTracks.B.length?'B':'');
const translationSlot=document.getElementById('translationSlot');
const translationText=document.getElementById('translationText');
const translationA=document.getElementById('translationA');
const translationB=document.getElementById('translationB');
const translationStatus=document.getElementById('translationStatus');
function setTranslationTrack(name){{
 if(!translationTracks[name]?.length)return;
 activeTranslationTrack=name;
 translationA?.classList.toggle('active',name==='A');
 translationB?.classList.toggle('active',name==='B');
}}
if(translationSlot&&(translationTracks.A.length||translationTracks.B.length)){{
 translationSlot.hidden=false;
 if(translationA)translationA.hidden=!translationTracks.A.length;
 if(translationB)translationB.hidden=!translationTracks.B.length;
 translationA?.addEventListener('click',()=>setTranslationTrack('A'));
 translationB?.addEventListener('click',()=>setTranslationTrack('B'));
 setTranslationTrack(activeTranslationTrack);
}}
function refreshTranslationText(){{
 if(!translationText||!activeTranslationTrack||players.length!==1)return;
 const player=players[0];
 if(!player||typeof player.getCurrentTime!=='function')return;
 const now=Number(player.getCurrentTime());
 const cue=translationTracks[activeTranslationTrack].find(row=>now>=Number(row.start)&&now<Number(row.end));
 translationText.textContent=cue?.translated||'';
}}
setInterval(refreshTranslationText,250);
let watchMode=streams.length>1?"multi":"single";
// No product-imposed stream cap: stop adding only for duplicates or browser/API failures.
const liveRailItems=Array.from(document.querySelectorAll('.live-channel-rail-item[data-live-video-id]'));
streams.forEach(stream=>{{
 const match=liveRailItems.find(item=>item.dataset.liveVideoId===stream.videoId);
 stream.channelId=match?.dataset.channelId||'';
}});
function refreshRailVisibility(){{
 const selectedIds=new Set(streams.map(stream=>stream.videoId));
 const selectedChannels=new Set(streams.map(stream=>stream.channelId).filter(Boolean));
 liveRailItems.forEach(item=>{{
  item.hidden=watchMode==='multi'&&(selectedIds.has(item.dataset.liveVideoId)||(item.dataset.channelId&&selectedChannels.has(item.dataset.channelId)));
 }});
}}
const verifiedTimelineStarts={verified_start_map_json};
const manualTimelineStarts={manual_start_map_json};
const manualTimelineAlign=document.getElementById('manualTimelineAlign');
const manualTimelineLabel=document.getElementById('manualTimelineLabel');
let manualTimelineEnabled=false;
function timelineValue(map,index){{
 const value=Number(map[streams[index]?.videoId]);
 return Number.isFinite(value)?value:NaN;
}}
function verifiedTimelineComplete(){{
 return streams.length>1&&streams.every((_,index)=>Number.isFinite(timelineValue(verifiedTimelineStarts,index)));
}}
function manualTimelineEligible(){{
 return streams.length>1&&streams.every((_,index)=>Number.isFinite(timelineValue(manualTimelineStarts,index)));
}}
function timelineStartFor(index){{
 const verified=timelineValue(verifiedTimelineStarts,index);
 if(Number.isFinite(verified))return verified;
 if(manualTimelineEnabled){{
  const manual=timelineValue(manualTimelineStarts,index);
  if(Number.isFinite(manual))return manual;
 }}
 return NaN;
}}
function recomputeVerifiedTimeline(){{
 const verifiedComplete=verifiedTimelineComplete();
 const manualEligible=manualTimelineEligible();
 if(manualTimelineLabel)manualTimelineLabel.hidden=verifiedComplete||!manualEligible;
 if(manualTimelineAlign&&(verifiedComplete||!manualEligible)){{
  manualTimelineAlign.checked=false;
  manualTimelineEnabled=false;
 }}
 manualTimelineEnabled=Boolean(!verifiedComplete&&manualEligible&&manualTimelineAlign?.checked);
 hasVerifiedTimeline=verifiedComplete||manualTimelineEnabled;
 return hasVerifiedTimeline;
}}
let hasVerifiedTimeline=false;
recomputeVerifiedTimeline();
const immerse=document.getElementById('customImmerse');
const watchSettings=document.getElementById('watchSettings');
const watchImmersive=document.getElementById('watchImmersive');
watchSettings?.addEventListener('click',()=>{{
 const open=document.body.classList.toggle('settings-open');
 watchSettings.setAttribute('aria-expanded',String(open));
}});
watchImmersive?.addEventListener('click',()=>immerse?.click());
const pttFontSize=document.getElementById('pttFontSize');
const pttFontValue=document.getElementById('pttFontValue');
const pttEmbedShowFloor=document.getElementById('pttEmbedShowFloor');
const hasPtt=Boolean(document.querySelector('.ptt-live-panel'));
function pttFrame(){{return document.querySelector('.ptt-live-panel iframe');}}
function setPttFontSize(value){{const size=Math.max(12,Math.min(26,Number(value)||14));document.documentElement.style.setProperty('--ptt-font-size',size+'px');if(pttFontSize)pttFontSize.value=String(size);if(pttFontValue)pttFontValue.textContent=size+'px';const frame=pttFrame();if(frame?.contentWindow)frame.contentWindow.postMessage({{type:'holoviewer:ptt-font-size',size}},location.origin);}}
function setEmbeddedPttFloor(show){{if(pttEmbedShowFloor)pttEmbedShowFloor.checked=Boolean(show);try{{localStorage.setItem('holoviewer-ptt-show-floor',String(Boolean(show)));}}catch(_e){{}}const frame=pttFrame();if(frame?.contentWindow)frame.contentWindow.postMessage({{type:'holoviewer:ptt-show-floor',show:Boolean(show)}},location.origin);}}
if(pttFontSize){{setPttFontSize(pttFontSize.value);pttFontSize.addEventListener('input',()=>setPttFontSize(pttFontSize.value));}}
if(pttEmbedShowFloor){{let show=true;try{{show=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';}}catch(_e){{}}pttEmbedShowFloor.checked=show;pttEmbedShowFloor.addEventListener('change',()=>setEmbeddedPttFloor(pttEmbedShowFloor.checked));}}
const pttEmbeddedFrame=pttFrame();pttEmbeddedFrame?.addEventListener('load',()=>{{if(pttFontSize)setPttFontSize(pttFontSize.value);if(pttEmbedShowFloor)setEmbeddedPttFloor(pttEmbedShowFloor.checked);}});
let immersiveEnabled=false;
function repinWorkerPttAfterLayout(){{
 const feed=document.getElementById('ptt-worker-feed');
 const follow=document.getElementById('ptt-worker-follow');
 if(!feed||!follow?.checked)return;
 requestAnimationFrame(()=>requestAnimationFrame(()=>{{feed.scrollTop=feed.scrollHeight;}}));
 setTimeout(()=>{{feed.scrollTop=feed.scrollHeight;}},250);
}}
function forceSingleImmersiveGeometry(active){{
 if(!contentGrid||!pttPanel)return;
 const rail=document.querySelector('.live-channel-rail');
 const stageNode=document.getElementById('stage');
 const card=stageNode?.querySelector('.player-card');
 const wrap=card?.querySelector('.video-wrap');
 const controls=card?.querySelector('.player-controls');
 const playerNode=wrap?.querySelector('.player');
 const iframe=wrap?.querySelector('iframe');
 const nodes=[contentGrid,document.querySelector('.custom-player-column'),stageNode,card,wrap,playerNode,iframe,pttPanel,controls,rail].filter(Boolean);
 if(!active||streams.length!==1){{
  nodes.forEach(node=>{{
   const saved=node.dataset.immersiveStyle;
   if(saved!==undefined){{node.setAttribute('style',saved);delete node.dataset.immersiveStyle;}}
  }});
  return;
 }}
 nodes.forEach(node=>{{if(node.dataset.immersiveStyle===undefined)node.dataset.immersiveStyle=node.getAttribute('style')||'';}});
 if(rail)rail.style.setProperty('display','none','important');
 Object.assign(contentGrid.style,{{position:'fixed',inset:'0',width:'100vw',height:'100dvh',margin:'0',padding:'0',overflow:'hidden',background:'#000',zIndex:'2147483000'}});
 contentGrid.style.setProperty('display','grid','important');
 contentGrid.style.setProperty('grid-template-columns','minmax(0,1fr) clamp(320px,24vw,420px)','important');
 contentGrid.style.setProperty('grid-template-rows','100dvh','important');
 const playerColumn=document.querySelector('.custom-player-column');
 if(playerColumn)Object.assign(playerColumn.style,{{position:'relative',width:'100%',height:'100dvh',margin:'0',padding:'0',overflow:'hidden',background:'#000'}});
 [stageNode,card,wrap,playerNode,iframe].filter(Boolean).forEach(node=>{{
  Object.assign(node.style,{{position:'absolute',inset:'0',display:'block',width:'100%',height:'100dvh',minWidth:'0',minHeight:'100dvh',maxWidth:'none',maxHeight:'none',margin:'0',padding:'0',border:'0'}});
  node.style.setProperty('aspect-ratio','auto','important');
 }});
 if(controls)controls.style.setProperty('display','none','important');
 Object.assign(pttPanel.style,{{position:'relative',inset:'auto',display:'flex',width:'100%',height:'100dvh',minWidth:'0',minHeight:'0',maxWidth:'none',maxHeight:'none',margin:'0',padding:'0',overflow:'hidden'}});
 pttPanel.style.setProperty('grid-column','2','important');
 pttPanel.style.setProperty('grid-row','1','important');
}}
function forceMultiImmersiveGeometry(active){{
 if(!contentGrid||!pttPanel||streams.length<2)return;
 const playerColumn=document.querySelector('.custom-player-column');
 const stageNode=document.getElementById('stage');
 const cards=Array.from(stageNode?.querySelectorAll('.player-card')||[]);
 const wraps=cards.map(card=>card.querySelector('.video-wrap')).filter(Boolean);
 const playersNodes=wraps.flatMap(wrap=>Array.from(wrap.querySelectorAll('.player,iframe')));
 const controls=cards.map(card=>card.querySelector('.player-controls')).filter(Boolean);
 const nodes=[contentGrid,playerColumn,stageNode,pttPanel,...cards,...wraps,...playersNodes,...controls].filter(Boolean);
 if(!active){{
  nodes.forEach(node=>{{
   const saved=node.dataset.multiImmersiveStyle;
   if(saved!==undefined){{node.setAttribute('style',saved);delete node.dataset.multiImmersiveStyle;}}
  }});
  return;
 }}
 nodes.forEach(node=>{{if(node.dataset.multiImmersiveStyle===undefined)node.dataset.multiImmersiveStyle=node.getAttribute('style')||'';}});
 contentGrid.style.setProperty('position','fixed','important');
 contentGrid.style.setProperty('inset','0','important');
 contentGrid.style.setProperty('display','block','important');
 contentGrid.style.setProperty('width','100vw','important');
 contentGrid.style.setProperty('height','100dvh','important');
 contentGrid.style.setProperty('margin','0','important');
 contentGrid.style.setProperty('padding','0','important');
 contentGrid.style.setProperty('overflow','hidden','important');
 contentGrid.style.setProperty('background','#000','important');
 contentGrid.style.setProperty('z-index','2147483000','important');
 if(playerColumn){{
  playerColumn.style.setProperty('position','absolute','important');
  playerColumn.style.setProperty('inset','0','important');
  playerColumn.style.setProperty('display','block','important');
  playerColumn.style.setProperty('width','100%','important');
  playerColumn.style.setProperty('height','100%','important');
  playerColumn.style.setProperty('overflow','hidden','important');
 }}
 if(stageNode){{
  stageNode.style.setProperty('position','absolute','important');
  stageNode.style.setProperty('inset','0','important');
  stageNode.style.setProperty('display','grid','important');
  stageNode.style.setProperty('width','100%','important');
  stageNode.style.setProperty('height','100%','important');
  stageNode.style.setProperty('min-height','0','important');
  stageNode.style.setProperty('max-height','none','important');
  stageNode.style.setProperty('gap','4px','important');
  stageNode.style.setProperty('overflow','hidden','important');
 }}
 if(layout==='primary'){{
  stageNode?.style.setProperty('grid-template-columns','minmax(0,2.25fr) minmax(260px,.9fr)','important');
  stageNode?.style.setProperty('grid-template-rows','repeat(3,minmax(0,1fr))','important');
 }}else{{
  const tileCount=cards.length+(pttPanel?1:0);
  const cols=tileCount<=1?1:tileCount<=4?2:tileCount<=9?3:4;
  const rows=Math.max(1,Math.ceil(tileCount/cols));
  stageNode?.style.setProperty('grid-template-columns','repeat('+cols+',minmax(0,1fr))','important');
  stageNode?.style.setProperty('grid-template-rows','repeat('+rows+',minmax(0,1fr))','important');
 }}
 cards.forEach((card,index)=>{{
  card.style.setProperty('position','relative','important');
  card.style.setProperty('display',(layout==='primary'&&card.classList.contains('focus-hidden'))?'none':'flex','important');
  card.style.setProperty('flex-direction','column','important');
  card.style.setProperty('width','100%','important');
  card.style.setProperty('height','100%','important');
  card.style.setProperty('min-width','0','important');
  card.style.setProperty('min-height','0','important');
  card.style.setProperty('max-width','none','important');
  card.style.setProperty('max-height','none','important');
  card.style.setProperty('overflow','hidden','important');
  if(layout==='primary'){{
   if(card.classList.contains('primary')){{card.style.setProperty('grid-column','1','important');card.style.setProperty('grid-row','1 / 4','important');}}
   else if(card.classList.contains('focus-side-1')){{card.style.setProperty('grid-column','2','important');card.style.setProperty('grid-row','1','important');}}
   else if(card.classList.contains('focus-side-2')){{card.style.setProperty('grid-column','2','important');card.style.setProperty('grid-row','2','important');}}
  }}else{{
   card.style.setProperty('grid-column','auto','important');card.style.setProperty('grid-row','auto','important');
  }}
 }});
 wraps.forEach(wrap=>{{
  wrap.style.setProperty('position','relative','important');
  wrap.style.setProperty('display','block','important');
  wrap.style.setProperty('flex','1 1 0','important');
  wrap.style.setProperty('width','100%','important');
  wrap.style.setProperty('height','100%','important');
  wrap.style.setProperty('min-width','0','important');
  wrap.style.setProperty('min-height','0','important');
  wrap.style.setProperty('max-width','none','important');
  wrap.style.setProperty('max-height','none','important');
  wrap.style.setProperty('aspect-ratio','auto','important');
  wrap.style.setProperty('overflow','hidden','important');
 }});
 playersNodes.forEach(node=>{{
  node.style.setProperty('position','absolute','important');
  node.style.setProperty('inset','0','important');
  node.style.setProperty('display','block','important');
  node.style.setProperty('width','100%','important');
  node.style.setProperty('height','100%','important');
  node.style.setProperty('min-width','0','important');
  node.style.setProperty('min-height','0','important');
  node.style.setProperty('max-width','none','important');
  node.style.setProperty('max-height','none','important');
 }});
 controls.forEach(node=>node.style.setProperty('display','none','important'));
 pttPanel.style.setProperty('position','relative','important');
 pttPanel.style.setProperty('display','flex','important');
 pttPanel.style.setProperty('flex-direction','column','important');
 pttPanel.style.setProperty('width','100%','important');
 pttPanel.style.setProperty('height','100%','important');
 pttPanel.style.setProperty('min-width','0','important');
 pttPanel.style.setProperty('min-height','0','important');
 pttPanel.style.setProperty('max-width','none','important');
 pttPanel.style.setProperty('max-height','none','important');
 pttPanel.style.setProperty('overflow','hidden','important');
 if(layout==='primary'){{pttPanel.style.setProperty('grid-column','2','important');pttPanel.style.setProperty('grid-row',streams.length===2?'2 / 4':'3','important');}}
 else{{pttPanel.style.setProperty('grid-column','auto','important');pttPanel.style.setProperty('grid-row','auto','important');}}
 const pttContent=pttPanel.querySelector('iframe:not([hidden]),#ptt-worker-feed:not([hidden])');
 if(pttContent){{
  pttContent.style.setProperty('display','block','important');
  pttContent.style.setProperty('flex','1 1 0','important');
  pttContent.style.setProperty('width','100%','important');
  pttContent.style.setProperty('height','100%','important');
  pttContent.style.setProperty('min-height','0','important');
  pttContent.style.setProperty('max-height','none','important');
 }}
}}

function applyImmersiveState(active){{
 immersiveEnabled=Boolean(active);
 document.body.classList.toggle('custom-immersive',immersiveEnabled);
 mountImmersiveSurface(immersiveEnabled);
 forceSingleImmersiveGeometry(immersiveEnabled);
 forceMultiImmersiveGeometry(immersiveEnabled);
 repinWorkerPttAfterLayout();
 immerse?.setAttribute('aria-pressed',String(immersiveEnabled));
 if(watchImmersive)watchImmersive.textContent=immersiveEnabled?'退出沉浸模式':'沉浸模式';
 if(immerse)immerse.textContent=immersiveEnabled?'退出沉浸模式':'沉浸模式';
}}
immerse?.addEventListener('click',async()=>{{
 const next=!immersiveEnabled;
 applyImmersiveState(next);
 try{{
  if(next&&!document.fullscreenElement){{
   // Fullscreen the viewing surface itself, not the document: it enters the
   // browser top layer and cannot inherit the Client shell's max-width/rails.
   const surface=pttPanel&&contentGrid?contentGrid:document.documentElement;
   await surface.requestFullscreen();
  }}
  else if(!next&&document.fullscreenElement)await document.exitFullscreen();
 }}catch(_e){{
  // Keep the CSS immersive state even when browser fullscreen is unavailable.
  statusBox.textContent=next?'已進入沉浸介面（瀏覽器未提供全螢幕）':'已退出沉浸介面';
 }}
}});
document.addEventListener('fullscreenchange',()=>{{
 // Escape exits immersive if fullscreen was actually active. CSS-only immersive
 // remains valid when the browser refuses requestFullscreen().
 if(!document.fullscreenElement&&immersiveEnabled&&document.visibilityState==='visible'){{
  applyImmersiveState(false);
 }}else if(document.fullscreenElement){{
  applyImmersiveState(true);
 }}
}});

function refreshMultiControls(){{const active=streams.length>1;document.querySelectorAll('[data-layout]').forEach(button=>button.hidden=!active);for(const id of ['playerSyncLabel','focusChoices','focusCarousel','focusCarouselIntervalLabel','audioFollowLabel','playAll','pauseAll']){{const el=document.getElementById(id);if(el)el.hidden=!active;}}}}
refreshMultiControls();
let layout={json.dumps(layout)}==='auto'&&streams.length===2?'equal':{json.dumps(layout)}, primaryIndex={session.primary_index}, audioMaster={session.audio_master_index};
const videoHeight=document.getElementById('videoHeight');
const videoHeightValue=document.getElementById('videoHeightValue');
videoHeight?.addEventListener('input',()=>{{
 const height=Math.max(360,Math.min(1000,Number(videoHeight.value)||1000));
 document.querySelector('.custom-player-column')?.style.setProperty('--custom-video-height',height+'px');
 if(videoHeightValue)videoHeightValue.textContent=height+'px';
}});
/* Clicking a catalog-confirmed live avatar immediately replaces only the
   selected slot. Do not reconstruct other YouTube players or guess offsets. */
document.querySelectorAll('.live-channel-rail-item[data-live-video-id]').forEach(link=>{{
 link.addEventListener('click',event=>{{
  const next=link.dataset.liveVideoId;
  if(!/^[A-Za-z0-9_-]{{11}}$/.test(next))return;
  event.preventDefault();
  const title=link.querySelector('strong')?.textContent||next;
  if(watchMode==='multi'){{
    if(streams.some(stream=>stream.videoId===next))return;

    appendWatchStream(next,title,link.dataset.channelId||'');
    return;
  }}
  const index=streams.length===1?0:replacementTarget;
  const player=players[index];
  if(!player||typeof player.loadVideoById!=='function')return;
  if(streams[index].videoId===next)return;
  syncEchoes.clear();pendingArchiveFollowers.clear();
  // Re-evaluate provenance after a source change. A verified collab timeline
  // survives only while every current stream still belongs to that event.
  // A new live source invalidates archive Seek, but 8501-style multi-live
  // play/pause linking remains on after user-selected channel replacement.
  if(syncPlayback)syncPlayback.checked=streams.length>1;
  streams[index].videoId=next;
  streams[index].channelId=link.dataset.channelId||'';
  recomputeVerifiedTimeline();
  persistWatchState();
  player.loadVideoById(next);
  if(index===primaryIndex&&typeof refreshPrimaryPtt==='function')setTimeout(()=>refreshPrimaryPtt(index),0);
  refreshRailVisibility();
  const activeCard=document.querySelector('.player-card[data-index="'+index+'"]');
  const label=activeCard?.querySelector('.player-label');
  if(label)label.textContent=title;
  const youtubeLink=activeCard?.querySelector('.player-youtube-link');
  if(youtubeLink)youtubeLink.href='https://www.youtube.com/watch?v='+encodeURIComponent(next);
  statusBox.textContent='已切換視角 '+String.fromCharCode(65+index)+'：'+title;
 }});
}});
const syncPlayback=document.getElementById('syncPlayback');
/* Multi-view is linked by default, but never auto-started. Verified archive
   collabs need the same default so the first user Play drives absolute-time
   follower seeks; manual multi-view keeps play/pause linking without guessed offsets. */
if(syncPlayback&&streams.length>1)syncPlayback.checked=true;
const playAll=document.getElementById('playAll'),pauseAll=document.getElementById('pauseAll');
const focusChoices=document.getElementById('focusChoices');
const focusCarousel=document.getElementById('focusCarousel');
const focusCarouselInterval=document.getElementById('focusCarouselInterval');
const focusCarouselIntervalOutput=document.getElementById('focusCarouselIntervalOutput');
const audioFollowFocus=document.getElementById('audioFollowFocus');
let focusTimer=null,focusCarouselMs=10000;
let syncMaster=primaryIndex;
const syncEchoes=new Map();
const pendingArchiveFollowers=new Set();
let nextPlayerSlotId=0;
const players=Array(streams.length).fill(null),stage=document.getElementById('stage'),statusBox=document.getElementById('status');
let replacementTarget=0;
const watchSingleMode=document.getElementById('watchSingleMode'),watchMultiMode=document.getElementById('watchMultiMode'),watchModeToggle=document.getElementById('watchModeToggle');
function refreshWatchMode(){{
 const single=watchMode==='single';
 watchSingleMode?.setAttribute('aria-pressed',String(single));
 watchMultiMode?.setAttribute('aria-pressed',String(!single));
 watchModeToggle?.setAttribute('aria-checked',String(!single));
 document.body.classList.toggle('watch-multi',!single);
 refreshRailVisibility();
}}
watchSingleMode?.addEventListener('click',()=>{{watchMode='single';refreshWatchMode();statusBox.textContent='已切換至單人模式：點頭像替換直播';}});
watchMultiMode?.addEventListener('click',()=>{{watchMode='multi';refreshWatchMode();statusBox.textContent='已切換至多人模式：點頭像新增視角';}});
watchModeToggle?.addEventListener('click',()=>{{watchMode=watchMode==='single'?'multi':'single';refreshWatchMode();statusBox.textContent=watchMode==='single'?'已切換至單人模式：點頭像替換直播':'已切換至多人模式：點頭像新增視角';}});
refreshWatchMode();
function setReplacementTarget(index){{
 if(index<0||index>=streams.length)return;
 replacementTarget=index;
 document.querySelectorAll('.player-card').forEach((card,i)=>{{
  card.classList.toggle('replacement-target',i===index);
  const button=card.querySelector('.replacement-choice');
  if(button)button.setAttribute('aria-pressed',String(i===index));
 }});
}}

function clampVolume(v){{return Math.max(0,Math.min(100,Number(v)||0));}}
function columnsFor(count){{if(count<=1)return 1;if(count<=4)return 2;if(count<=9)return 3;return 4;}}
function persistWatchState(){{
 try{{
  const url=new URL(window.location.href);
  url.searchParams.delete('stream');
  streams.forEach(stream=>url.searchParams.append('stream',stream.videoId));
  window.history.replaceState(null,'',url.pathname+'?'+url.searchParams.toString()+url.hash);
 }}catch(_error){{}}
}}
function applyLayout(){{
  const tileCount=stage.children.length;
  const tileColumns=tileCount<=1?1:tileCount<=4?2:tileCount<=9?3:tileCount<=16?4:5;
  const tileRows=Math.max(1,Math.ceil(tileCount/tileColumns));
  document.documentElement.style.setProperty('--tile-count',String(tileCount));
  document.documentElement.style.setProperty('--tile-columns',String(tileColumns));
  document.documentElement.style.setProperty('--tile-rows',String(tileRows));
  document.body.classList.toggle('watch-grid',streams.length>=3);
  document.body.classList.toggle('layout-auto',layout==='auto');
  document.body.classList.toggle('layout-equal',layout==='equal');
  document.body.classList.toggle('layout-primary',layout==='primary');
  document.documentElement.style.setProperty('--columns',String(streams.length===1?1:(layout==='primary'?2:columnsFor(streams.length))));
  document.documentElement.style.setProperty('--side-count',String(Math.max(1,streams.length-1)));
  const focusSideIndices=[];
  if(layout==='primary'&&streams.length>1){{
   for(let offset=1;offset<streams.length&&focusSideIndices.length<2;offset++){{
    focusSideIndices.push((primaryIndex+offset)%streams.length);
   }}
  }}
  document.querySelectorAll('.player-card').forEach((card,index)=>{{
   card.classList.toggle('primary',index===primaryIndex);
   const sidePosition=focusSideIndices.indexOf(index);
   card.classList.toggle('focus-hidden',layout==='primary'&&index!==primaryIndex&&sidePosition<0);
   card.classList.toggle('focus-side-1',layout==='primary'&&sidePosition===0);
   card.classList.toggle('focus-side-2',layout==='primary'&&sidePosition===1);
  }});
  placePttForLayout();
  document.querySelectorAll('[data-layout]').forEach(button=>button.classList.toggle('active',button.dataset.layout===layout));
  focusChoices?.querySelectorAll('[data-focus-index]').forEach(button=>button.classList.toggle('active',layout==='primary'&&Number(button.dataset.focusIndex)===primaryIndex));
  document.querySelectorAll('.player-card').forEach((card,index)=>{{
   const focus=card.querySelector('.focus');
   if(focus)focus.hidden=streams.length===1||(layout==='primary'&&index===primaryIndex);
  }});
  if(immersiveEnabled&&streams.length>1)forceMultiImmersiveGeometry(true);
}}
const globalVolume=document.getElementById('globalVolume');
const globalVolumeValue=document.getElementById('globalVolumeValue');
const immersiveGlobalVolume=document.getElementById('immersiveGlobalVolume');
const immersiveGlobalVolumeValue=document.getElementById('immersiveGlobalVolumeValue');
let masterVolume=100;
function setGlobalVolume(value){{
 masterVolume=clampVolume(value);
 if(globalVolume)globalVolume.value=String(masterVolume);
 if(immersiveGlobalVolume)immersiveGlobalVolume.value=String(masterVolume);
 if(globalVolumeValue)globalVolumeValue.textContent=masterVolume+'%';
 if(immersiveGlobalVolumeValue)immersiveGlobalVolumeValue.textContent=masterVolume+'%';
 applyAudio();
}}
globalVolume?.addEventListener('input',()=>setGlobalVolume(globalVolume.value));
immersiveGlobalVolume?.addEventListener('input',()=>setGlobalVolume(immersiveGlobalVolume.value));
function effectiveVolume(index){{
 const slider=document.querySelector('.player-card[data-index="'+index+'"] .slider');
 return Math.round(masterVolume*clampVolume(slider?slider.value:100)/100);
}}
function applyAudio(){{
  players.forEach((player,index)=>{{
    if(!player||typeof player.setVolume!=='function')return;
    player.setVolume(effectiveVolume(index));
    if(index===audioMaster)player.unMute();else player.mute();
  }});
  document.querySelectorAll('.master').forEach((button,index)=>{{
    const active=index===audioMaster;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));button.textContent=active?'主聲源':'設為聲源';
  }});
}}
function setPrimary(index,fromCarousel=false){{
 if(index<0||index>=streams.length)return;
 if(!fromCarousel)stopFocusCarousel();
 primaryIndex=index;setReplacementTarget(index);layout='primary';applyLayout();
 if(audioFollowFocus?.checked){{audioMaster=index;applyAudio();}}
 if(typeof refreshPrimaryPtt==='function')refreshPrimaryPtt(index);
}}
function stopFocusCarousel(){{
 if(focusTimer!==null)clearInterval(focusTimer);
 focusTimer=null;
 if(focusCarousel){{focusCarousel.classList.remove('active');focusCarousel.textContent='輪播 '+(focusCarouselMs/1000)+'s';}}
}}
function startFocusCarousel(){{
 if(focusTimer!==null)clearInterval(focusTimer);
 focusTimer=setInterval(()=>setPrimary((primaryIndex+1)%streams.length,true),focusCarouselMs);
}}
if(streams.length>1){{
 streams.forEach((stream,index)=>{{
  const button=document.createElement('button');
  button.type='button';button.dataset.focusIndex=String(index);
  button.textContent='Focus '+String.fromCharCode(65+index);
  button.title=stream.label||('Stream '+(index+1));
  button.onclick=()=>setPrimary(index);
  focusChoices?.appendChild(button);
 }});
}}
focusCarousel?.addEventListener('click',()=>{{
 if(focusTimer!==null){{stopFocusCarousel();return;}}
 if(audioFollowFocus)audioFollowFocus.checked=true;
 setPrimary(primaryIndex,true);
 focusCarousel.classList.add('active');
 focusCarousel.textContent='停止輪播';
 startFocusCarousel();
}});
focusCarouselInterval?.addEventListener('input',()=>{{
 focusCarouselMs=Math.max(10000,Math.min(60000,Number(focusCarouselInterval.value)*1000||10000));
 focusCarouselIntervalOutput.textContent=focusCarouselInterval.value+' 秒';
 if(focusTimer!==null)startFocusCarousel();
 else focusCarousel.textContent='輪播 '+focusCarouselInterval.value+'s';
}});
audioFollowFocus?.addEventListener('change',()=>{{
 if(audioFollowFocus.checked&&layout==='primary'){{audioMaster=primaryIndex;applyAudio();}}
}});
document.addEventListener('visibilitychange',()=>{{if(document.hidden)stopFocusCarousel();}});
window.addEventListener('pagehide',stopFocusCarousel,{{once:true}});
function timelineSeconds(index){{
 const player=players[index];
 return player&&typeof player.getCurrentTime==='function'
  ?Math.max(0,Number(player.getCurrentTime())||0):0;
}}
function alignFollower(index,master){{
 if(!hasVerifiedTimeline||index===master)return true;
 const player=players[index],source=players[master];
 if(!player||!source||typeof player.seekTo!=='function')return false;
 const expected=timelineStartFor(master)+timelineSeconds(master)-timelineStartFor(index);
 if(expected<0)return false;
 // YouTube can silently clamp seeks past the VOD end. Never chase that
 // unreachable position every 500ms. Treat it as standby until the
 // master returns to a playable instant within this source.
 const duration=typeof player.getDuration==='function'?Number(player.getDuration()):NaN;
 if(Number.isFinite(duration)&&duration>0&&expected>=duration)return false;
 if(Math.abs(timelineSeconds(index)-expected)>.8)player.seekTo(expected,true);
 return true;
}}
function syncFollowers(master,playing){{
  if(!syncPlayback?.checked)return;
  syncMaster=master;
  players.forEach((player,index)=>{{
    if(index===master||!player)return;
    const canPlay=alignFollower(index,master);
    if(playing&&!canPlay){{
      pendingArchiveFollowers.add(index);
      if(typeof player.pauseVideo==='function'){{
        syncEchoes.set(index,{{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000}});
        player.pauseVideo();
      }}
      return;
    }}
    pendingArchiveFollowers.delete(index);
    const expected=playing?YT.PlayerState.PLAYING:YT.PlayerState.PAUSED;
    if(typeof player.getPlayerState==='function'&&player.getPlayerState()===expected)return;
    syncEchoes.set(index,{{expected,expires:Date.now()+2000}});
    if(playing&&typeof player.playVideo==='function')player.playVideo();
    else if(!playing&&typeof player.pauseVideo==='function')player.pauseVideo();
    else syncEchoes.delete(index);
  }});
}}
function handlePlayerState(index,event){{
 if(!syncPlayback?.checked||!window.YT?.PlayerState)return;
 const echo=syncEchoes.get(index);
 if(echo){{
  if(Date.now()>echo.expires)syncEchoes.delete(index);
  else if(event.data===echo.expected){{
   syncEchoes.delete(index);
   return;
  }}
  // BUFFERING / CUED can precede the induced PLAYING event.
  // Keep the expected echo until it matches; a real PAUSED/PLAYING
  // user action with a different state still propagates.
 }}
 if(event.data===YT.PlayerState.PLAYING)syncFollowers(index,true);
 else if(event.data===YT.PlayerState.PAUSED)syncFollowers(index,false);
}}
syncPlayback?.addEventListener('change',()=>{{
 syncEchoes.clear();
 if(!syncPlayback.checked)pendingArchiveFollowers.clear();
 statusBox.textContent=syncPlayback.checked?'已啟用連動：操作任一播放器可一起播放／暫停':'獨立播放：播放器互不影響';
 if(!syncPlayback.checked)return;
 const master=players[syncMaster];
 if(!master||typeof master.getPlayerState!=='function')return;
 const state=master.getPlayerState();
 if(state===YT.PlayerState.PLAYING)syncFollowers(syncMaster,true);
 else if(state===YT.PlayerState.PAUSED)syncFollowers(syncMaster,false);
}});
manualTimelineAlign?.addEventListener('change',()=>{{
 syncEchoes.clear();pendingArchiveFollowers.clear();
 manualTimelineEnabled=Boolean(manualTimelineAlign.checked);
 recomputeVerifiedTimeline();
 if(manualTimelineAlign.checked&&!hasVerifiedTimeline){{
  manualTimelineAlign.checked=false;
  manualTimelineEnabled=false;
  statusBox.textContent='目前影片缺少可用的實際開播時間，無法自動對齊';
  return;
 }}
 if(manualTimelineAlign.checked){{
  if(syncPlayback)syncPlayback.checked=true;
  syncMaster=primaryIndex;
  const master=players[syncMaster];
  const state=master&&typeof master.getPlayerState==='function'?master.getPlayerState():null;
  if(state===YT.PlayerState.PLAYING)syncFollowers(syncMaster,true);
  else if(state===YT.PlayerState.PAUSED)syncFollowers(syncMaster,false);
  else players.forEach((_,index)=>{{if(index!==syncMaster)alignFollower(index,syncMaster);}});
  statusBox.textContent='已啟用依實際開播時間自動對齊';
 }}else{{
  recomputeVerifiedTimeline();
  statusBox.textContent='已關閉時間軸自動對齊；仍可保留連動播放／暫停';
 }}
}});
function controlAllPlayback(playing){{
 syncEchoes.clear();
 if(!playing)pendingArchiveFollowers.clear();
 syncMaster=primaryIndex;
 // Explicit archive group-play is consent to keep the verified timeline in sync.
 if(playing&&hasVerifiedTimeline&&syncPlayback)syncPlayback.checked=true;
 players.forEach((player,index)=>{{
  if(!player)return;
  if(playing&&hasVerifiedTimeline&&index!==syncMaster&&!alignFollower(index,syncMaster)){{
   pendingArchiveFollowers.add(index);
   if(typeof player.pauseVideo==='function'){{
    syncEchoes.set(index,{{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000}});
    player.pauseVideo();
   }}
   return;
  }}
  const expected=playing?YT.PlayerState.PLAYING:YT.PlayerState.PAUSED;
  if(typeof player.getPlayerState==='function'&&player.getPlayerState()===expected)return;
  syncEchoes.set(index,{{expected,expires:Date.now()+2000}});
  if(playing&&typeof player.playVideo==='function')player.playVideo();
  else if(!playing&&typeof player.pauseVideo==='function')player.pauseVideo();
  else syncEchoes.delete(index);
 }});
 statusBox.textContent=playing?'正在播放全部視角':'已暫停全部視角';
}}
// Explicit group controls remain permitted; never infer archive offsets.
playAll?.addEventListener('click',()=>controlAllPlayback(true));
setInterval(()=>{{
 if(!hasVerifiedTimeline||!syncPlayback?.checked)return;
 const master=players[syncMaster];
 if(!master||typeof master.getPlayerState!=='function')return;
 const state=master.getPlayerState();
 if(state!==YT.PlayerState.PLAYING&&state!==YT.PlayerState.PAUSED)return;
 players.forEach((_,index)=>{{
  if(index===syncMaster)return;
  const ready=alignFollower(index,syncMaster);
  if(!ready){{
   pendingArchiveFollowers.add(index);
   const follower=players[index];
   if(follower&&typeof follower.pauseVideo==='function'&&
      typeof follower.getPlayerState==='function'&&
      follower.getPlayerState()!==YT.PlayerState.PAUSED){{
    syncEchoes.set(index,{{expected:YT.PlayerState.PAUSED,expires:Date.now()+2000}});
    follower.pauseVideo();
   }}
   return;
  }}
  if(ready&&pendingArchiveFollowers.has(index)){{
   pendingArchiveFollowers.delete(index);
   const follower=players[index];
   if(state===YT.PlayerState.PLAYING&&follower&&typeof follower.playVideo==='function'){{
    syncEchoes.set(index,{{expected:YT.PlayerState.PLAYING,expires:Date.now()+2000}});
    follower.playVideo();
   }}
  }}
 }});
}},500);
pauseAll?.addEventListener('click',()=>controlAllPlayback(false));
function buildCard(stream,index){{
  const card=document.createElement('section');card.className='player-card';card.dataset.index=String(index);card.dataset.slotId=String(nextPlayerSlotId++);
  card.innerHTML='<div class="video-wrap"><div id="player-'+card.dataset.slotId+'" class="player"></div></div><div class="player-controls"><div><div class="player-label"></div><div class="audio-row"><span>音量</span><input class="slider" type="range" min="0" max="100" step="1" value="100"></div></div><div class="player-actions"><a class="player-youtube-link" target="_blank" rel="noopener noreferrer">YouTube ↗</a><button class="master" type="button"></button><button class="replacement-choice" type="button" aria-pressed="false">換台目標</button><button class="focus" type="button">設為主要</button></div></div>';
  const youtubeLink=card.querySelector('.player-youtube-link');youtubeLink.href='https://www.youtube.com/watch?v='+encodeURIComponent(stream.videoId);
  card.querySelector('.player-label').textContent=stream.label;
  card.querySelector('.slider').oninput=()=>{{const current=Number(card.dataset.index);const player=players[current];if(player&&typeof player.setVolume==='function')player.setVolume(effectiveVolume(current));}};
  card.querySelector('.master').onclick=()=>{{audioMaster=Number(card.dataset.index);applyAudio();}};
  card.querySelector('.replacement-choice').onclick=()=>setReplacementTarget(Number(card.dataset.index));
  card.querySelector('.focus').onclick=()=>setPrimary(Number(card.dataset.index));
  if(streams.length===1)card.querySelector('.focus').hidden=true;
  const remove=document.createElement('button');remove.type='button';remove.className='remove-stream';remove.textContent='🗑';remove.title='移除這個直播';remove.setAttribute('aria-label','移除 '+stream.label);remove.onclick=()=>removeWatchStream(Number(card.dataset.index));
  card.querySelector('.player-actions').appendChild(remove);
  return card;
}}
streams.forEach((stream,index)=>stage.appendChild(buildCard(stream,index)));
function refreshWatchCards(){{
 stage.querySelectorAll('.player-card').forEach((card,index)=>{{card.dataset.index=String(index);card.querySelector('.focus').hidden=streams.length===1;}});
}}
function removeWatchStream(index){{
 if(streams.length<=1){{statusBox.textContent='至少保留一個直播';return;}}
 const player=players[index];if(player&&typeof player.destroy==='function')player.destroy();
 const card=stage.querySelector('.player-card[data-index="'+index+'"]');card?.remove();
 streams.splice(index,1);players.splice(index,1);syncEchoes.clear();pendingArchiveFollowers.clear();
 if(primaryIndex===index)primaryIndex=Math.min(index,streams.length-1);
 else if(primaryIndex>index)primaryIndex--;
 if(audioMaster===index)audioMaster=primaryIndex;else if(audioMaster>index)audioMaster--;
 if(replacementTarget>=streams.length)replacementTarget=0;
 // Rebuild only the lightweight focus buttons, never the surviving YouTube players.
 focusChoices?.replaceChildren();streams.forEach((stream,i)=>{{const b=document.createElement('button');b.type='button';b.dataset.focusIndex=String(i);b.textContent='Focus '+String.fromCharCode(65+i);b.onclick=()=>setPrimary(i);focusChoices?.appendChild(b);}});
 recomputeVerifiedTimeline();
 syncSessionCardinalityClasses();if(immersiveEnabled)forceSingleImmersiveGeometry(streams.length===1);refreshWatchCards();refreshMultiControls();applyLayout();refreshRailVisibility();setReplacementTarget(Math.min(replacementTarget,streams.length-1));applyAudio();persistWatchState();if(typeof refreshPrimaryPtt==='function')refreshPrimaryPtt(primaryIndex);statusBox.textContent='已移除視角';
}}
function appendWatchStream(videoId,label,channelId=''){{
 const index=streams.length,stream={{videoId,label,channelId}};streams.push(stream);players.push(null);
 const card=buildCard(stream,index);stage.appendChild(card);syncEchoes.clear();pendingArchiveFollowers.clear();recomputeVerifiedTimeline();
 const b=document.createElement('button');b.type='button';b.dataset.focusIndex=String(index);b.textContent='Focus '+String.fromCharCode(65+index);b.onclick=()=>setPrimary(index);focusChoices?.appendChild(b);
 syncSessionCardinalityClasses();if(immersiveEnabled)forceSingleImmersiveGeometry(false);refreshWatchCards();refreshMultiControls();applyLayout();refreshRailVisibility();persistWatchState();
 if(window.YT?.Player){{mountWatchPlayer(index);}}
 if(syncPlayback)syncPlayback.checked=true;
 statusBox.textContent='已加入視角 '+String.fromCharCode(65+index)+'：'+label;
}}
const collabPollUrl={collab_poll_json};
const collabLabel={collab_label_json};
let collabPollTimer=null,collabPollInFlight=false;
async function refreshLiveCollab(){{
 if(!collabPollUrl||document.hidden||collabPollInFlight)return;
 collabPollInFlight=true;
 try{{
  const response=await fetch(collabPollUrl,{{cache:'no-store',headers:{{'Accept':'application/json'}}}});
  if(!response.ok)return;
  const payload=await response.json();
  const additions=Array.isArray(payload.streams)?payload.streams:[];
  additions.forEach(item=>{{
   const id=String(item.video_id||'');
   if(!/^[A-Za-z0-9_-]{{11}}$/.test(id)||streams.some(stream=>stream.videoId===id))return;
   appendWatchStream(id,String(item.label||id),String(item.channel_id||''));
  }});
  if(additions.length&&collabLabel)statusBox.title=collabLabel+' · Live POV 自動更新中';
 }}catch(_error){{
  // Preserve the current player wall; the next interval retries discovery.
 }}finally{{collabPollInFlight=false;}}
}}
if(collabPollUrl){{
 document.body.classList.add('collab-live-session');
 refreshLiveCollab();
 collabPollTimer=setInterval(refreshLiveCollab,15000);
 document.addEventListener('visibilitychange',()=>{{if(!document.hidden)refreshLiveCollab();}});
 window.addEventListener('pagehide',()=>{{if(collabPollTimer)clearInterval(collabPollTimer);}},{{once:true}});
}}
setReplacementTarget(primaryIndex);
/* The PTT iframe stays mounted: move only its existing node into the
   stage so Focus layout can put it below the small second video. */
const pttPanel=document.querySelector('.ptt-live-panel');
const contentGrid=document.querySelector('.custom-content-grid');
function mountImmersiveSurface(active){{
 // Never reparent a mounted YouTube iframe. Moving an iframe between DOM
 // parents can tear down its browsing context and stop an actively playing
 // single stream. Fullscreen promotes contentGrid to the top layer, while the
 // CSS geometry below handles browsers that decline requestFullscreen().
 void active;
}}
function placePttForLayout(){{
 if(!pttPanel||!contentGrid)return;
 if(streams.length>=2)stage.appendChild(pttPanel);
 else contentGrid.appendChild(pttPanel);
}}
placePttForLayout();

document.querySelectorAll('[data-layout]').forEach(button=>button.onclick=()=>{{stopFocusCarousel();layout=button.dataset.layout;applyLayout();if(layout==='primary'&&audioFollowFocus?.checked){{audioMaster=primaryIndex;applyAudio();}}}});
applyLayout();
function mountWatchPlayer(index){{
  const stream=streams[index];
  if(!stream||players[index])return;
  const card=stage.querySelector('.player-card[data-index="'+index+'"]');
  if(!card)return;
  const mounted=new YT.Player('player-'+card.dataset.slotId,{{
      videoId:stream.videoId,width:'100%',height:'100%',playerVars:{{playsinline:1,rel:0,controls:1}},
      events:{{onReady:()=>{{const current=players.indexOf(mounted);if(current<0)return;applyAudio();if(playAll)playAll.disabled=false;if(pauseAll)pauseAll.disabled=false;if(typeof startPttBridge==='function')startPttBridge(current);}},onStateChange:event=>{{const current=players.indexOf(mounted);if(current>=0)handlePlayerState(current,event);}},onError:event=>{{const current=players.indexOf(mounted);if(current<0)return;const code=Number(event?.data);statusBox.textContent='YouTube 內嵌播放失敗'+(Number.isFinite(code)?'（錯誤 '+code+'）':'')+'；可用 YouTube ↗ 開啟原影片確認。';}}}}
  }});
  players[index]=mounted;
}}
window.onYouTubeIframeAPIReady=function(){{streams.forEach((stream,index)=>mountWatchPlayer(index));}};
const api=document.createElement('script');api.src='https://www.youtube.com/iframe_api';document.head.appendChild(api);
"""
    if show_live_ptt and (ptt_worker_config or ptt_resolver_url):
        from pathlib import Path
        asset_dir = Path(__file__).resolve().parent / "public"
        for asset in ("ptt_timeline.js", "ptt_player_adapter.js", "ptt_worker_adapter.js"):
            script += "\n" + (asset_dir / asset).read_text(encoding="utf-8")
        script += "\n" + _worker_ptt_player_script(ptt_worker_config or {}, ptt_resolver_url)
    single_mode = ""
    if show_live_ptt and len(session.streams) == 1:
        ptt_kind = "vod" if ptt_worker_config and ptt_worker_config.get("mode") == "archive" else "live"
        single_mode = f" single-ptt single-{ptt_kind}"
    return client_document(
        title="自訂觀看",
        active="custom",
        content=content,
        extra_css=css,
        extra_script=script,
        body_class=f"layout-{layout} custom-session-watching{single_mode}",
    )
