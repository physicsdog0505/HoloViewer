"""Optional Watchalong UX overlays reused from the multistream surface.

This module keeps the core YouTube synchronization component focused on playback.
It augments the rendered HTML with immersive fullscreen, transcript subtitles,
source-video subtitle/danmaku overlays, and a synchronized read-only PTT panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Iterable, Sequence

from frontend_config import database_paths
from frontend_db import merged_pushes_for_date, merged_pushes_for_window
from frontend_feed_polling import FEED_POLLING_JS
from frontend_multistream_sync import _timeline_messages
from ptt_reader_components import decorate_ptt_reader_html, replay_timeline_messages
from youtube_metadata import YoutubeMetadataError, fetch_video, load_api_key


@dataclass(frozen=True, slots=True)
class WatchalongPttPayload:
    messages: tuple[dict, ...]
    notice: str = ""


_DISPLAY_TIMESTAMP_PREFIXES = (
    re.compile(r"^\s*\[?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?\]?\s*[-–—:：]?\s*"),
    re.compile(r"^\s*\d+\s*minutes?\s*,?\s*\d+\s*seconds?\s*[-–—:：]?\s*", re.I),
    re.compile(r"^\s*\d+\s*分\s*\d+\s*秒\s*[-–—:：]?\s*"),
)


def _clean_subtitle_text(value: object) -> str:
    """Remove transcript timestamp labels from speech text shown to viewers."""
    text = str(value or "").strip()
    previous = None
    while text and text != previous:
        previous = text
        for pattern in _DISPLAY_TIMESTAMP_PREFIXES:
            text = pattern.sub("", text, count=1).strip()
    return text


MIN_DANMAKU_DURATION = 6.0
MAX_DANMAKU_DURATION = 15.0


def calculate_danmaku_duration(cue_or_text: object, mode: str = "both") -> float:
    """Calculate character-length and language-aware danmaku display duration in seconds."""
    if isinstance(cue_or_text, str):
        jp_text = cue_or_text
        zh_text = ""
    elif isinstance(cue_or_text, dict):
        jp_text = str(cue_or_text.get("text") or "").strip()
        zh_text = str(cue_or_text.get("translated") or "").strip()
    else:
        jp_text = str(getattr(cue_or_text, "source_text", getattr(cue_or_text, "text", "")) or "").strip()
        zh_text = str(getattr(cue_or_text, "translated_text", getattr(cue_or_text, "translated", "")) or "").strip()

    jp_len = len(jp_text)
    zh_len = len(zh_text)

    if mode == "ja" or not zh_text:
        duration = 7.5 + jp_len * 0.12
    elif mode == "zh":
        duration = 8.0 + zh_len * 0.18
    else:
        duration = 9.0 + (zh_len * 0.18 + jp_len * 0.10)

    if duration < MIN_DANMAKU_DURATION:
        duration = MIN_DANMAKU_DURATION
    if duration > MAX_DANMAKU_DURATION:
        duration = MAX_DANMAKU_DURATION
    return round(duration, 2)


def subtitle_payload(segments: Iterable) -> tuple[dict, ...]:
    """Convert transcript segments to the shared subtitle-preview shape."""
    result: list[dict] = []
    for segment in segments:
        source_text = _clean_subtitle_text(getattr(segment, "source_text", ""))
        translated_text = _clean_subtitle_text(getattr(segment, "translated_text", ""))
        if not source_text:
            continue
        result.append(
            {
                "start": max(0.0, float(getattr(segment, "start_ms", 0)) / 1000.0),
                "end": max(0.0, float(getattr(segment, "end_ms", 0)) / 1000.0),
                "text": source_text,
                "translated": translated_text,
            }
        )
    return tuple(result)


def _ptt_payload(
    status: str,
    notice: str,
    *,
    messages: Sequence[dict] = (),
    live_feed_url: str = "",
    session_start: str = "",
) -> WatchalongPttPayload:
    meta = {
        "__watchalong_meta__": True,
        "status": status,
        "notice": notice,
        "live_feed_url": live_feed_url,
        "session_start": session_start,
    }
    return WatchalongPttPayload((meta, *tuple(messages)), notice)




def _watchalong_replay_messages(messages: Sequence[dict]) -> tuple[dict, ...]:
    return replay_timeline_messages(messages)


def load_watchalong_ptt_messages(master_video_id: str) -> WatchalongPttPayload:
    """Load a read-only PTT timeline and attach live polling metadata when needed."""
    if not master_video_id:
        return _ptt_payload("unavailable", "沒有 master video id，略過 PTT。")
    try:
        meta = fetch_video(master_video_id, load_api_key())
    except YoutubeMetadataError as exc:
        return _ptt_payload("unavailable", f"PTT 時間軸暫不可用：{exc}")
    except Exception as exc:
        return _ptt_payload("unavailable", f"PTT 時間軸暫不可用：{type(exc).__name__}")

    if meta.completed and (meta.actual_start is None or meta.actual_end is None):
        return _ptt_payload("unavailable", "已結束影片缺少可驗證的實際開播或結束時間，不能對齊歷史 PTT。")
    session_start = meta.actual_start if meta.completed else meta.preferred_start
    if session_start is None:
        return _ptt_payload("unavailable", "YouTube 沒有可用開播時間，暫時無法對齊 PTT。")
    if session_start.tzinfo is None:
        session_start = session_start.replace(tzinfo=timezone.utc)

    session_end = meta.actual_end
    if session_end is None:
        session_end = max(datetime.now(timezone.utc), session_start + timedelta(minutes=1))
    if session_end.tzinfo is None:
        session_end = session_end.replace(tzinfo=timezone.utc)

    database, web_database = database_paths()
    try:
        pushes = merged_pushes_for_window(database, web_database, session_start, session_end)
    except Exception as exc:
        return _ptt_payload("unavailable", f"PTT 讀取失敗：{type(exc).__name__}: {exc}")

    shared_timeline = _timeline_messages(pushes, session_start)
    # Live polling serves the shared raw timeline: the initial seed must use
    # exactly the same offsets as subsequent GET /pushes responses.
    timeline = (
        tuple(shared_timeline)
        if not meta.completed
        else _watchalong_replay_messages(shared_timeline)
    )
    if not meta.completed:
        try:
            from collab_live_feed import start_live_feed_server

            feed = start_live_feed_server(str(database), str(web_database))
        except Exception as exc:
            return _ptt_payload(
                "unavailable",
                f"PTT 即時來源目前不可用：{type(exc).__name__}: {exc}",
                messages=timeline,
                session_start=session_start.isoformat(),
            )
        return _ptt_payload(
            "live",
            "PTT 即時讀取中；會自動跟隨既有 Collector 的 SQLite 更新。",
            messages=timeline,
            live_feed_url=feed.base_url,
            session_start=session_start.isoformat(),
        )

    if timeline:
        return _ptt_payload(
            "ready",
            f"已載入同時段 PTT {len(timeline)} 則；歷史來源 Coverage／Gap 未確認完整，非影片專屬留言。",
            messages=timeline,
            session_start=session_start.isoformat(),
        )

    try:
        dates = {session_start.date(), session_end.date()}
        any_day_data = any(
            merged_pushes_for_date(database, web_database, selected)
            for selected in dates
        )
    except Exception as exc:
        return _ptt_payload(
            "unavailable",
            f"PTT 歷史資料狀態無法確認：{type(exc).__name__}: {exc}",
            session_start=session_start.isoformat(),
        )
    if any_day_data:
        return _ptt_payload(
            "incomplete",
            "這個時間窗內未找到推文，但歷史來源 Coverage／Gap 未確認完整，不能判定確實為零筆。",
            session_start=session_start.isoformat(),
        )
    return _ptt_payload(
        "incomplete",
        "這個直播日期的歷史 PTT 資料尚未補齊。",
        session_start=session_start.isoformat(),
    )


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def enhance_watchalong_html(
    base_html: str,
    *,
    subtitles: Sequence[dict] = (),
    a_subtitles: Sequence[dict] = (),
    b_subtitles: Sequence[dict] = (),
    ptt_messages: Sequence[dict] = (),
    subtitle_feed_url: str = "",
    subtitle_feed_token: str = "",
    subtitle_feed_session_id: str = "",
    subtitle_poll_ms: int = 1000,
) -> str:
    """Add immersive fullscreen, subtitles, source overlays, and PTT."""
    if 'id="master-player"' not in base_html or 'id="source-player"' not in base_html:
        raise ValueError("watchalong base HTML is missing expected player anchors")

    css = r'''
#immersive { margin-left:auto; }
#controls > .row:first-of-type { position:fixed; right:12px; bottom:12px; z-index:50; background:#111; border:1px solid #444; border-radius:8px; padding:6px; box-shadow:0 4px 16px #0008; }
#subtitle-shell { border-top:1px solid #2b2b2b; background:#0d0d0d; }
#subtitle-toolbar { display:flex; justify-content:flex-end; gap:4px; padding:3px 5px 0; flex-wrap:wrap; }
.subtitle-mode,.subtitle-display-mode,.subtitle-track { border:1px solid #3b3b3b; background:#1c1c1c; color:#bbb; border-radius:4px; padding:2px 6px; font-size:10px; cursor:pointer; }
.subtitle-mode.active,.subtitle-display-mode.active,.subtitle-track.active { background:#e5e5e5; border-color:#e5e5e5; color:#111; font-weight:700; }
#jp-subtitle { min-height:3.5em; display:flex; flex-direction:column; align-items:center; justify-content:center; padding:4px 10px 7px; line-height:1.35; text-align:center; }
#jp-subtitle.empty { color:#777; font-size:12px; }
.subtitle-jp { color:#f4f4f4; font-size:15px; }
.subtitle-zh { color:#d8d8d8; font-size:14px; margin-top:2px; }
body.subtitle-ja .subtitle-zh { display:none; }
body.subtitle-zh .subtitle-jp { display:none; }
#source-card .player-wrap { overflow:hidden; }
#source-subtitle-overlay { position:absolute; z-index:7; left:8%; right:8%; top:12%; bottom:auto; display:none; pointer-events:none; text-align:center; line-height:1.35; text-shadow:-2px -2px 2px #000,2px -2px 2px #000,-2px 2px 2px #000,2px 2px 2px #000,0 3px 8px #000; }
#source-subtitle-overlay.enabled { display:flex; flex-direction:column; align-items:center; }
#source-subtitle-overlay .overlay-jp { color:#bfe8ff; font-size:clamp(15px,2vw,25px); font-weight:800; padding:2px 7px; }
#source-subtitle-overlay .overlay-zh { color:#8fd3ff; font-size:clamp(14px,1.8vw,22px); font-weight:800; padding:2px 7px; margin-top:3px; }
body.subtitle-ja #source-subtitle-overlay .overlay-zh { display:none; }
body.subtitle-zh #source-subtitle-overlay .overlay-jp { display:none; }
#source-danmaku-layer { position:absolute; inset:0; z-index:8; overflow:hidden; pointer-events:none; display:none; }
#source-danmaku-layer.enabled { display:block; }
.source-danmaku { position:absolute; left:100%; white-space:nowrap; color:#bfe8ff; font-size:clamp(15px,1.9vw,23px); font-weight:800; text-shadow:0 1px 2px #000,1px 1px 0 #000,-1px -1px 0 #000; animation:watchalongDanmaku 8s linear forwards; }
@keyframes watchalongDanmaku { from { transform:translateX(0); } to { transform:translateX(calc(-100vw - 120%)); } }
#ptt-panel { height:210px; min-height:120px; display:flex; flex-direction:column; border-top:1px solid #2b2b2b; background:#0d0d0d; }
/* The master card owns both video and PTT.  In the full-height watchalong
   workspace the PTT reader must consume the remaining card height instead of
   keeping the legacy fixed 210px preview height. */
body.watchalong-session-fit #master-card{display:flex;flex-direction:column;min-height:0;overflow:hidden}
body.watchalong-session-fit #master-card .player-wrap{flex:0 0 auto}
body.watchalong-session-fit #ptt-panel{flex:1 1 0;height:auto;min-height:0;overflow:hidden}
body.watchalong-session-fit #ptt-feed{height:auto;min-height:0;flex:1 1 0;overflow-y:auto}
#ptt-head { display:flex; justify-content:space-between; padding:5px 8px; background:#151515; border-bottom:1px solid #242424; font-size:12px; }
#ptt-feed { min-height:0; flex:1; overflow-y:auto; padding:3px 7px 10px; display:flex; flex-direction:column; }
#ptt-feed > .ptt-row:first-child { margin-top:auto; }
.ptt-row { display:grid; grid-template-columns:1.2em 4.4em 3.4em minmax(0,1fr); gap:5px; padding:3px 1px; border-bottom:1px solid #181818; font-family:Menlo,Monaco,monospace; font-size:12px; line-height:1.35; }
.ptt-floor { color:#777; font-size:.82em; padding-top:.15em; white-space:nowrap; }
#ptt-feed.ptt-hide-floor .ptt-row { grid-template-columns:1.2em 4.4em minmax(0,1fr); }
#ptt-feed.ptt-hide-floor .ptt-floor { display:none; }
.ptt-kind { font-weight:800; text-align:center; }.ptt-kind.push { color:#eee; }.ptt-kind.boo,.ptt-kind.arrow { color:#ff4b4b; }
.ptt-clock { color:#999; font-size:.82em; padding-top:.15em; white-space:nowrap; }.ptt-author { color:#ffff00; font-weight:700; margin-right:.4em; }.ptt-content { color:#a9a900; white-space:pre-wrap; }
body.immersive #layout-controls,body.immersive #controls { display:none; }
body.immersive #ptt-head { display:none; }
body.immersive #ptt-panel { border-top:0; }
body.immersive #ptt-feed { padding-top:6px; }
body.immersive #grid { height:100vh; gap:4px; }
body.immersive #grid.focus-source { grid-template-columns:minmax(220px,.30fr) minmax(0,1fr); }
body.immersive .card { border-color:#151515; }
body.immersive #source-card .player-wrap { height:100%; aspect-ratio:auto; }
body.immersive #source-card { min-height:0; }
@media(max-width:820px){#ptt-panel{height:180px;}body.immersive #grid,body.immersive #grid.focus-source{height:auto;grid-template-columns:1fr}}
'''
    base_html = base_html.replace("</style></head>", css + "</style></head>", 1)
    # Stable body hook for the production Client's full-height PTT layout.
    def _add_watchalong_body_class(match: re.Match[str]) -> str:
        attrs = match.group(1)
        class_match = re.search(r"\bclass=(['\"])(.*?)\1", attrs, flags=re.S)
        if class_match:
            classes = class_match.group(2).split()
            if "watchalong-session-fit" not in classes:
                classes.append("watchalong-session-fit")
            replacement = f'class={class_match.group(1)}{" ".join(classes)}{class_match.group(1)}'
            attrs = attrs[:class_match.start()] + replacement + attrs[class_match.end():]
        else:
            attrs += ' class="watchalong-session-fit"'
        return f"<body{attrs}>"

    base_html, body_replacements = re.subn(
        r"<body([^>]*)>", _add_watchalong_body_class, base_html, count=1, flags=re.I
    )
    if body_replacements != 1:
        raise ValueError("watchalong base HTML changed: body tag missing")

    base_html = base_html.replace(
        '<button id="layout-focus">Focus 動畫</button></div>',
        '<button id="layout-focus">Focus 動畫</button><button id="immersive">沉浸全螢幕</button></div>',
        1,
    )
    base_html = base_html.replace(
        '<div id="source-player" class="player"></div>',
        '<div id="source-player" class="player"></div><div id="source-subtitle-overlay"></div><div id="source-danmaku-layer"></div>',
        1,
    )

    master_extras = (
        '<div id="subtitle-shell">'
        '<div id="subtitle-toolbar"><button class="subtitle-mode active" data-subtitle-mode="both">中日</button>'
        '<button class="subtitle-mode" data-subtitle-mode="zh">中文</button>'
        '<button class="subtitle-mode" data-subtitle-mode="ja">日文</button><button class="subtitle-track" id="subtitle-track-a">A方案</button><button class="subtitle-track" id="subtitle-track-b">B方案</button>'
        '<button class="subtitle-display-mode" id="toggle-source-subtitle">畫面字幕</button>'
        '<button class="subtitle-display-mode" id="toggle-source-danmaku">彈幕</button></div>'
        '<div id="jp-subtitle" class="empty">字幕會跟隨兔子時間軸</div></div>'
        '<div id="ptt-panel"><div id="ptt-head"><span id="ptt-count">PTT 載入中</span>'
        '<div class="ptt-toolbar"><button type="button" id="ptt-latest">最新</button> <label><input id="ptt-follow" type="checkbox" checked> 自動跟隨</label> <label><input id="ptt-floor-toggle" type="checkbox" checked> 顯示樓數</label></div></div>'
        '<div id="ptt-feed"><div id="ptt-waiting" style="color:#777;text-align:center;padding:18px 8px;font-size:12px">正在確認 PTT 資料狀態</div></div></div>'
    )
    source_card = re.search(r"<section\s+id=['\"]source-card['\"]", base_html)
    if source_card is None:
        raise ValueError("watchalong base HTML changed: source card missing")
    master_close = base_html.rfind("</section>", 0, source_card.start())
    if master_close < 0:
        raise ValueError("watchalong base HTML changed: master card closing tag missing")
    base_html = base_html[:master_close] + master_extras + base_html[master_close:]

    js = r'''
<script>
const watchalongPttSeed=__PTT__;
const watchalongPttMeta=watchalongPttSeed.find(item=>item&&item.__watchalong_meta__)||{};
let watchalongPtt=watchalongPttSeed.filter(item=>!(item&&item.__watchalong_meta__));
const watchalongTrackA=__A_SUBTITLES__;
const watchalongTrackB=__B_SUBTITLES__;
let watchalongSubtitles=watchalongTrackA.length?watchalongTrackA:__SUBTITLES__;
const watchalongSubtitleFeedUrl=__SUBTITLE_FEED_URL__;
const watchalongSubtitleFeedToken=__SUBTITLE_FEED_TOKEN__;
const watchalongSubtitleFeedSessionId=__SUBTITLE_FEED_SESSION__;
const watchalongSubtitlePollMs=__SUBTITLE_POLL_MS__;
let watchalongSubtitleFeedVersion=-1;
const jpSubtitle=document.getElementById('jp-subtitle');
const sourceSubtitleOverlay=document.getElementById('source-subtitle-overlay');
const sourceDanmakuLayer=document.getElementById('source-danmaku-layer');
const toggleSourceSubtitle=document.getElementById('toggle-source-subtitle');
const toggleSourceDanmaku=document.getElementById('toggle-source-danmaku');
const pttFeed=document.getElementById('ptt-feed');
const pttCount=document.getElementById('ptt-count');
const pttFollow=document.getElementById('ptt-follow');
const pttLatest=document.getElementById('ptt-latest');
const pttFloorToggle=document.getElementById('ptt-floor-toggle');
function applyPttFloorSetting(){if(pttFeed&&pttFloorToggle)pttFeed.classList.toggle('ptt-hide-floor',!pttFloorToggle.checked);}
if(pttFloorToggle){try{pttFloorToggle.checked=localStorage.getItem('holoviewer-ptt-show-floor')!=='false';}catch(_error){}pttFloorToggle.onchange=()=>{try{localStorage.setItem('holoviewer-ptt-show-floor',String(pttFloorToggle.checked));}catch(_error){}applyPttFloorSetting();};}
applyPttFloorSetting();
if(pttLatest)pttLatest.onclick=()=>{if(pttFollow)pttFollow.checked=true;pttFeed.scrollTop=pttFeed.scrollHeight;};
let watchalongShownPtt=-2;
// PTT display is independent of subtitle setup and network subscriptions.
updatePtt(0);
setInterval(updateWatchalongExtras,400);
let currentSubtitleCue=null;
let sourceSubtitleEnabled=false;
let sourceDanmakuEnabled=false;
let lastDanmakuKey='';
let danmakuLane=0;
function escapeText(value){return String(value??'');}
function currentSubtitleMode(){return document.body.classList.contains('subtitle-zh')?'zh':document.body.classList.contains('subtitle-ja')?'ja':'both';}
function cueDisplayText(cue){
  if(!cue)return '';
  const mode=currentSubtitleMode(),jp=escapeText(cue.text),zh=escapeText(cue.translated||'');
  if(mode==='zh')return zh||jp;
  if(mode==='ja')return jp;
  return zh?jp+String.fromCharCode(10)+zh:jp;
}
function renderSourceSubtitle(cue){
  if(!sourceSubtitleOverlay)return;
  sourceSubtitleOverlay.replaceChildren();
  if(!sourceSubtitleEnabled||!cue)return;
  const jp=document.createElement('div');jp.className='overlay-jp';jp.textContent=escapeText(cue.text);
  const zh=document.createElement('div');zh.className='overlay-zh';zh.textContent=escapeText(cue.translated||'');
  sourceSubtitleOverlay.append(jp,zh);
}
function computeDanmakuDuration(cue){
  if(!cue)return 8.0;
  const mode=currentSubtitleMode(),jp=escapeText(cue.text||'').trim(),zh=escapeText(cue.translated||'').trim();
  const jpLen=jp.length,zhLen=zh.length;
  let d=8.0;
  if(mode==='ja'||!zh){d=7.5+jpLen*0.12;}
  else if(mode==='zh'){d=8.0+zhLen*0.18;}
  else{d=9.0+(zhLen*0.18+jpLen*0.10);}
  if(d<6.0)d=6.0;if(d>15.0)d=15.0;
  return Math.round(d*100)/100;
}
function emitDanmaku(cue){
  if(!sourceDanmakuLayer||!sourceDanmakuEnabled||!cue)return;
  const key=String(cue.start)+'|'+String(cue.end)+'|'+escapeText(cue.text)+'|'+currentSubtitleMode();
  if(key===lastDanmakuKey)return;
  lastDanmakuKey=key;
  const text=cueDisplayText(cue);if(!text)return;
  const durationSec=computeDanmakuDuration(cue);
  const item=document.createElement('div');item.className='source-danmaku';
  item.style.animationDuration=durationSec+'s';
  item.textContent=text.split(String.fromCharCode(10)).join('　');
  item.style.top=(10+(danmakuLane%6)*11)+'%';danmakuLane+=1;
  sourceDanmakuLayer.appendChild(item);setTimeout(()=>item.remove(),Math.round((durationSec+0.3)*1000));
}
function setWatchalongSubtitleMode(mode){
  document.body.classList.remove('subtitle-both','subtitle-zh','subtitle-ja');
  document.body.classList.add('subtitle-'+mode);
  document.querySelectorAll('[data-subtitle-mode]').forEach(button=>button.classList.toggle('active',button.dataset.subtitleMode===mode));
  renderSourceSubtitle(currentSubtitleCue);
  lastDanmakuKey='';
  emitDanmaku(currentSubtitleCue);
}
document.querySelectorAll('[data-subtitle-mode]').forEach(button=>button.onclick=()=>setWatchalongSubtitleMode(button.dataset.subtitleMode));
setWatchalongSubtitleMode('both');
const subtitleTrackA=document.getElementById('subtitle-track-a');
const subtitleTrackB=document.getElementById('subtitle-track-b');
function selectWatchalongTrack(name){
  const next=name==='B'?watchalongTrackB:watchalongTrackA;
  if(!next.length)return;
  watchalongSubtitles=next;
  if(subtitleTrackA)subtitleTrackA.classList.toggle('active',name==='A');
  if(subtitleTrackB)subtitleTrackB.classList.toggle('active',name==='B');
  const t=typeof masterPlayer!=='undefined'&&masterPlayer&&typeof safeTime==='function'?safeTime(masterPlayer):0;
  updateJapaneseSubtitle(t);
}
if(subtitleTrackA){subtitleTrackA.hidden=!watchalongTrackA.length;subtitleTrackA.onclick=()=>selectWatchalongTrack('A');}
if(subtitleTrackB){subtitleTrackB.hidden=!watchalongTrackB.length;subtitleTrackB.onclick=()=>selectWatchalongTrack('B');}
if(watchalongTrackA.length)selectWatchalongTrack('A');
if(toggleSourceSubtitle)toggleSourceSubtitle.onclick=()=>{sourceSubtitleEnabled=!sourceSubtitleEnabled;toggleSourceSubtitle.classList.toggle('active',sourceSubtitleEnabled);if(sourceSubtitleOverlay)sourceSubtitleOverlay.classList.toggle('enabled',sourceSubtitleEnabled);renderSourceSubtitle(currentSubtitleCue);};
if(toggleSourceDanmaku)toggleSourceDanmaku.onclick=()=>{sourceDanmakuEnabled=!sourceDanmakuEnabled;toggleSourceDanmaku.classList.toggle('active',sourceDanmakuEnabled);if(sourceDanmakuLayer)sourceDanmakuLayer.classList.toggle('enabled',sourceDanmakuEnabled);lastDanmakuKey='';emitDanmaku(currentSubtitleCue);};
function pollWatchalongSubtitles(){return;}
function updateJapaneseSubtitle(t){
  let active=null;
  for(const cue of watchalongSubtitles){if(t>=Number(cue.start||0)&&t<Number(cue.end||0)){active=cue;break;}}
  currentSubtitleCue=active;
  if(jpSubtitle){
    if(active){
      const jp=document.createElement('div');jp.className='subtitle-jp';jp.textContent=escapeText(active.text);
      const zh=document.createElement('div');zh.className='subtitle-zh';zh.textContent=escapeText(active.translated||'');
      jpSubtitle.replaceChildren(jp,zh);jpSubtitle.classList.remove('empty');
    }else{jpSubtitle.textContent=watchalongSubtitles.length?'…':'尚未載入 transcript';jpSubtitle.classList.add('empty');}
  }
  renderSourceSubtitle(active);emitDanmaku(active);
}
function pttRow(message){
  const row=document.createElement('div');row.className='ptt-row';
  const kind=document.createElement('div');const raw=escapeText(message.kind);kind.className='ptt-kind '+(raw==='推'?'push':raw==='噓'||raw==='嘘'?'boo':'arrow');kind.textContent=raw;
  const clock=document.createElement('div');clock.className='ptt-clock';clock.textContent=escapeText(message.clock);
  const floor=document.createElement('div');floor.className='ptt-floor';floor.textContent=message.floor?(escapeText(message.floor)+'樓'):'';
  const body=document.createElement('div'),author=document.createElement('span'),content=document.createElement('span');author.className='ptt-author';content.className='ptt-content';author.textContent=escapeText(message.author)+': ';content.textContent=escapeText(message.content);body.append(author,content);row.append(kind,clock,floor,body);return row;
}
function pttEmptyText(){
  if(watchalongPttMeta.status==='live')return 'PTT 推文 0 則 · 即時更新中';
  if(watchalongPttMeta.status==='incomplete')return 'PTT · 歷史資料尚未補齊';
  if(watchalongPttMeta.status==='unavailable')return 'PTT · 資料來源目前不可用';
  return 'PTT 推文 0 則';
}
function installWatchalongPtt(next){
  watchalongPtt=[...new Map((next||[]).map(message=>[message.key||JSON.stringify(message),message])).values()].sort((a,b)=>Number(a.offset||0)-Number(b.offset||0));
  watchalongShownPtt=-2;
  const t=typeof masterPlayer!=='undefined'&&masterPlayer&&typeof safeTime==='function'?safeTime(masterPlayer):0;
  updatePtt(t);
}
function updatePtt(t){
  if(!pttFeed||!pttCount)return;
  if(!watchalongPtt.length){
    pttCount.textContent=pttEmptyText();
    pttFeed.innerHTML='';
    const empty=document.createElement('div');empty.style.cssText='color:#777;text-align:center;padding:18px 8px;font-size:12px';empty.textContent=escapeText(watchalongPttMeta.notice||pttEmptyText());pttFeed.appendChild(empty);
    watchalongShownPtt=-1;
    return;
  }
  // Both completed VODs and live Watchalong sessions follow the master
  // playback clock. Historical rows already carry watchalong_replay_offset,
  // so seeking the VOD backwards/forwards must move the PTT rail with it.
  let wanted=pttReplayUpperBound(watchalongPtt,t)-1;
  if(wanted===watchalongShownPtt){if(pttFollow&&pttFollow.checked)pttFeed.scrollTop=pttFeed.scrollHeight;return;}
  pttFeed.innerHTML='';const start=Math.max(0,wanted-119);for(let i=start;i<=wanted;i++)pttFeed.appendChild(pttRow(watchalongPtt[i]));
  watchalongShownPtt=wanted;pttCount.textContent='PTT 推文 '+Math.max(0,wanted+1)+' / '+watchalongPtt.length+' 則'+(watchalongPttMeta.status==='live'?' · 即時':'');
  if(wanted<0)pttFeed.innerHTML='<div id="ptt-waiting" style="color:#777;text-align:center;padding:18px 8px;font-size:12px">等待播放至第一則推文時間</div>';
  if(pttFollow&&pttFollow.checked)pttFeed.scrollTop=pttFeed.scrollHeight;
}
function updateWatchalongExtras(){if(typeof masterPlayer==='undefined'||!masterPlayer)return;const t=typeof safeTime==='function'?safeTime(masterPlayer):0;updateJapaneseSubtitle(t);updatePtt(t);}
async function enterWatchalongFullscreen(){
  if(!document.documentElement.requestFullscreen){if(typeof statusBox!=='undefined')statusBox.textContent='此瀏覽器環境不支援沉浸全螢幕';return;}
  try{await document.documentElement.requestFullscreen();}catch(error){if(typeof statusBox!=='undefined')statusBox.textContent='瀏覽器拒絕全螢幕；可先點頁面後再試一次';}
}
const immersiveButton=document.getElementById('immersive');
if(immersiveButton)immersiveButton.onclick=enterWatchalongFullscreen;
document.addEventListener('fullscreenchange',()=>{document.body.classList.toggle('immersive',Boolean(document.fullscreenElement));if(pttFollow&&pttFollow.checked){requestAnimationFrame(()=>requestAnimationFrame(()=>{pttFeed.scrollTop=pttFeed.scrollHeight;}));setTimeout(()=>{pttFeed.scrollTop=pttFeed.scrollHeight;},250);}});
__POLLING_JS__
if(watchalongPttMeta.live_feed_url&&watchalongPttMeta.session_start){
  try{startLivePushPolling(watchalongPttMeta.live_feed_url,watchalongPttMeta.session_start,3000,watchalongPtt,installWatchalongPtt);}
  catch(error){console.error('Watchalong PTT live polling failed',error);}
}
</script>
'''
    subtitle_poll_ms = max(500, int(subtitle_poll_ms))
    js = (
        js.replace("__SUBTITLES__", _safe_json(list(subtitles)))
        .replace("__A_SUBTITLES__", _safe_json(list(a_subtitles)))
        .replace("__B_SUBTITLES__", _safe_json(list(b_subtitles)))
        .replace("__PTT__", _safe_json(list(ptt_messages)))
        .replace("__SUBTITLE_FEED_URL__", _safe_json(subtitle_feed_url))
        .replace("__SUBTITLE_FEED_TOKEN__", _safe_json(subtitle_feed_token))
        .replace("__SUBTITLE_FEED_SESSION__", _safe_json(subtitle_feed_session_id))
        .replace("__SUBTITLE_POLL_MS__", str(subtitle_poll_ms))
        .replace("__POLLING_JS__", FEED_POLLING_JS)
    )
    return decorate_ptt_reader_html(base_html.replace("</body></html>", js + "</body></html>", 1), feed_id="ptt-feed", default_font=14)
