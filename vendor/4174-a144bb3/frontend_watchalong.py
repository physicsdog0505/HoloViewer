"""Browser component for YouTube watch-along synchronization."""

from __future__ import annotations

import json
from typing import Sequence


def build_watchalong_html(
    *,
    master_video_id: str,
    source_video_id: str,
    source_video_ids: Sequence[str] | None = None,
    episode_master_starts: Sequence[float] | None = None,
    initial_master_seconds: float = 0.0,
    initial_source_seconds: float = 0.0,
    initial_correction_seconds: float = 0.0,
    archive_auto_lock: bool = False,
    live_queue_standby: bool = False,
    telemetry_endpoint: str | None = None,
    telemetry_token: str | None = None,
    telemetry_session_id: str | None = None,
    telemetry_interval_ms: int = 1000,
) -> str:
    """Render a master YouTube player and one queued source player.

    Archive mode has an explicit pending state before the first transcript-derived
    episode start. It never seeks/replays the source while pending. A user gesture
    can start both players together, while direct master playback also arms source
    following on a best-effort basis under browser autoplay policy.
    """
    queue = [item for item in (source_video_ids or [source_video_id]) if item]
    if not queue:
        queue = [source_video_id]
    starts = [max(0.0, float(item)) for item in (episode_master_starts or [])]
    if starts:
        starts = sorted(starts)[: len(queue)]
    auto_mode = bool(archive_auto_lock and starts)

    master = json.dumps(master_video_id)
    sources = json.dumps(queue, ensure_ascii=False)
    start_json = json.dumps(starts)
    master_anchor = max(0.0, float(initial_master_seconds))
    source_anchor = max(0.0, float(initial_source_seconds))
    correction = float(initial_correction_seconds)
    auto_js = "true" if auto_mode else "false"
    live_queue_js = "true" if (live_queue_standby and not auto_mode) else "false"
    telemetry_interval_ms = max(250, int(telemetry_interval_ms))
    telemetry_endpoint_json = json.dumps(telemetry_endpoint or "")
    telemetry_token_json = json.dumps(telemetry_token or "")
    telemetry_session_json = json.dumps(telemetry_session_id or "")
    if auto_mode:
        controls_markup = """
<div class="row"><button id="arm" class="primary">同步播放／啟動跟隨</button><button id="pause-both">同步暫停</button><button id="catchup">立即重新對齊</button></div>
<details id="manual-tools"><summary>進階／手動校正</summary><div class="row manual-row"><button id="anchor">手動覆寫對齊點</button><button id="minus5">來源 -5 秒</button><button id="minus1">來源 -1 秒</button><button id="plus1">來源 +1 秒</button><button id="plus5">來源 +5 秒</button></div></details>
"""
    else:
        controls_markup = """
<div class="row"><button id="arm" class="primary">播放左側直播</button><button id="pause-both">暫停左側直播</button><span>右側片源請使用 YouTube 播放器自行控制。Playlist 播完會載入下一集並停在待機。</span><button id="anchor" hidden>手動對齊</button><button id="minus5" hidden>-5</button><button id="minus1" hidden>-1</button><button id="plus1" hidden>+1</button><button id="plus5" hidden>+5</button><button id="catchup" hidden>追上</button></div>
"""

    return f"""<!doctype html>
<html lang="zh-Hant">
<head><meta charset="utf-8"><style>
* {{ box-sizing:border-box }} html,body {{ margin:0;background:#0b0b0b;color:#eee;font-family:-apple-system,BlinkMacSystemFont,"Noto Sans TC",sans-serif }}
#layout-controls {{ display:flex;justify-content:flex-end;gap:7px;margin-bottom:8px }}
#grid {{ display:grid;grid-template-columns:1fr 1fr;gap:10px;transition:grid-template-columns .18s ease }}
#grid.focus-source {{ grid-template-columns:minmax(220px,.34fr) minmax(0,1fr) }}
#grid.focus-source #master-card .head::after {{ content:' · 次要畫面';color:#888;font-weight:500 }}
.card {{ border:1px solid #2b2b2b;background:#111;min-width:0 }}
.head {{ padding:7px 9px;font-size:13px;font-weight:700;border-bottom:1px solid #2b2b2b }} .player-wrap {{ position:relative;width:100%;aspect-ratio:16/9;background:#000 }}
.player {{ position:absolute;inset:0;width:100%;height:100% }}
#source-adjustments {{ border-top:1px solid #2b2b2b;background:#0d0d0d;padding:6px 8px;display:grid;gap:5px;font-size:11px }}
.adjust-row {{ display:flex;align-items:center;gap:5px;flex-wrap:wrap }}
.adjust-label {{ min-width:138px;color:#bbb }}
.adjust-status {{ color:#9fd3ff;font-family:ui-monospace,SFMono-Regular,Menlo,monospace }}
.adjust-button {{ padding:4px 7px;font-size:11px }}
#controls {{ margin-top:10px;border:1px solid #2b2b2b;background:#111;padding:10px;display:grid;gap:8px }}
#status {{ font:13px ui-monospace,SFMono-Regular,Menlo,monospace;color:#d8d8d8;white-space:pre-wrap }} .row {{ display:flex;flex-wrap:wrap;gap:7px;align-items:center }}
button {{ border:1px solid #444;background:#1e1e1e;color:#eee;border-radius:6px;padding:7px 10px;cursor:pointer }} button.primary {{ background:#2457d6;border-color:#3768e7 }}
button.active {{ background:#2d467e;border-color:#5576bf }} button:disabled {{ opacity:.45;cursor:default }} .note {{ color:#aaa;font-size:12px;line-height:1.45 }} #ready {{ color:#ffd166;font-weight:650 }} #queue {{ color:#9fd3ff;font-size:12px }}
#pending {{ color:#ffd166;font-weight:700 }} details#manual-tools {{ border-top:1px solid #2b2b2b;padding-top:6px }} details#manual-tools summary {{ cursor:pointer;color:#bbb;font-size:12px }} .manual-row {{ margin-top:7px }}
@media(max-width:820px){{#grid,#grid.focus-source{{grid-template-columns:1fr}}.adjust-label{{min-width:auto;width:100%}}}}
</style></head><body>
<div id="layout-controls"><button id="layout-compare" class="active">對照</button><button id="layout-focus">Focus 動畫</button></div>
<div id="grid"><section id="master-card" class="card"><div class="head">Hololive 直播（主時間軸）</div><div class="player-wrap"><div id="master-player" class="player"></div></div></section>
<section id="source-card" class="card"><div class="head">同時視聽來源（YouTube）</div><div class="player-wrap"><div id="source-player" class="player"></div></div>
<div id="source-adjustments">
<div class="adjust-row"><span class="adjust-label">單集微調（只影響目前影片）</span><button class="adjust-button" data-episode-delta="-5">-5s</button><button class="adjust-button" data-episode-delta="-1">-1s</button><button class="adjust-button" data-episode-delta="1">+1s</button><button class="adjust-button" data-episode-delta="5">+5s</button><span id="episode-adjust-status" class="adjust-status">+0.0s</span></div>
<div class="adjust-row"><span class="adjust-label">片源微調（本集起套用後續）</span><button class="adjust-button" data-source-delta="-5">-5s</button><button class="adjust-button" data-source-delta="-1">-1s</button><button class="adjust-button" data-source-delta="1">+1s</button><button class="adjust-button" data-source-delta="5">+5s</button><span id="source-adjust-status" class="adjust-status">+0.0s</span></div>
</div></section></div>
<div id="controls"><div id="status">等待播放器…</div><div id="queue"></div><div id="pending"></div>
{controls_markup}
<div id="ready"></div><div class="note">{ "VOD：Transcript 節點到達後，自動選集、開始播放並依主時間軸校正；節點前片源保持待機。Focus／對照只切版面，不重建播放器或同步 session。片源微調會從目前這集開始延續到後面的影片。" if auto_mode else "即時：右側片源由使用者獨立控制，不跟著左側直播播放或暫停。Playlist 播完一集會自動載入下一集，並停在待機。" }</div></div>
<script>
const masterVideoId={master}; const sourceVideoIds={sources}; let episodeStarts={start_json}; let archiveAutoLock={auto_js}; const liveQueueStandby={live_queue_js};
const telemetryEndpoint={telemetry_endpoint_json}, telemetryToken={telemetry_token_json}, telemetrySessionId={telemetry_session_json}, telemetryIntervalMs={telemetry_interval_ms};
let masterPlayer=null, sourcePlayer=null; let anchorMaster={master_anchor}, anchorSource={source_anchor}, correction={correction}; let anchorReady=false; let activeEpisode=-1; let switching=false; let syncArmed=false; let pendingPrepared=false; let pendingPriming=false; let pendingPrimeReady=false; let liveStandby=liveQueueStandby; let liveQueueFinished=false;
const episodeCorrections=Array(sourceVideoIds.length).fill(0), sourceCorrections=Array(sourceVideoIds.length).fill(0);
const statusBox=document.getElementById('status'), queueBox=document.getElementById('queue'), pendingBox=document.getElementById('pending'), catchupButton=document.getElementById('catchup'), readyBox=document.getElementById('ready'), armButton=document.getElementById('arm'), episodeAdjustStatus=document.getElementById('episode-adjust-status'), sourceAdjustStatus=document.getElementById('source-adjust-status');
function safeTime(p){{if(!p||typeof p.getCurrentTime!=='function')return 0;const v=Number(p.getCurrentTime()||0);return Number.isFinite(v)&&v>=0?v:0}}
function fmt(seconds){{const sign=seconds<0?'-':'';const value=Math.abs(seconds);const h=Math.floor(value/3600),m=Math.floor((value%3600)/60),s=Math.floor(value%60);return sign+(h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')}}
function signed(value){{const v=Number(value)||0;return `${{v>=0?'+':''}}${{v.toFixed(1)}}s`}}
function episodeFor(masterSeconds){{if(!archiveAutoLock||!episodeStarts.length)return 0;if(masterSeconds<episodeStarts[0])return -1;let idx=0;for(let i=0;i<episodeStarts.length;i++){{if(masterSeconds>=episodeStarts[i])idx=i;else break}}return Math.min(idx,sourceVideoIds.length-1)}}
function currentEpisodeIndex(){{if(liveQueueStandby&&activeEpisode>=0)return Math.min(activeEpisode,sourceVideoIds.length-1);const idx=episodeFor(safeTime(masterPlayer));return idx<0?0:Math.min(idx,sourceVideoIds.length-1)}}
function manualCorrectionFor(idx){{return correction+(episodeCorrections[idx]||0)+(sourceCorrections[idx]||0)}}
function targetFor(masterSeconds){{if(archiveAutoLock&&episodeStarts.length){{const idx=episodeFor(masterSeconds);if(idx<0)return 0;return Math.max(0,masterSeconds-episodeStarts[idx]+manualCorrectionFor(idx))}}const elapsed=masterSeconds-anchorMaster;return Math.max(0,anchorSource+elapsed+manualCorrectionFor(0))}}
function sourceState(){{return sourcePlayer&&typeof sourcePlayer.getPlayerState==='function'?sourcePlayer.getPlayerState():-1}}
function masterState(){{return masterPlayer&&typeof masterPlayer.getPlayerState==='function'?masterPlayer.getPlayerState():-1}}
function setLayout(mode){{const focus=mode==='focus';document.getElementById('grid').classList.toggle('focus-source',focus);document.getElementById('layout-compare').classList.toggle('active',!focus);document.getElementById('layout-focus').classList.toggle('active',focus)}}
function updateAdjustmentStatus(){{const idx=currentEpisodeIndex();episodeAdjustStatus.textContent=`第 ${{idx+1}} 集 ${{signed(episodeCorrections[idx])}}`;sourceAdjustStatus.textContent=`第 ${{idx+1}} 集起累計 ${{signed(sourceCorrections[idx])}}`}}
function seekSourceToTarget(){{if(!sourcePlayer||typeof sourcePlayer.seekTo!=='function')return;const masterSeconds=safeTime(masterPlayer);if(episodeFor(masterSeconds)<0)return;sourcePlayer.seekTo(targetFor(masterSeconds),true)}}
function adjustEpisode(delta){{const idx=currentEpisodeIndex();episodeCorrections[idx]+=Number(delta)||0;seekSourceToTarget();updateAdjustmentStatus();syncStatus()}}
function adjustSourceFromHere(delta){{const idx=currentEpisodeIndex(),amount=Number(delta)||0;for(let i=idx;i<sourceCorrections.length;i++)sourceCorrections[i]+=amount;seekSourceToTarget();updateAdjustmentStatus();syncStatus()}}
function preparePending(){{if(pendingPrepared||!sourcePlayer||!archiveAutoLock||!episodeStarts.length)return;pendingPrepared=true;activeEpisode=-1;if(typeof sourcePlayer.cueVideoById==='function')sourcePlayer.cueVideoById({{videoId:sourceVideoIds[0],startSeconds:0}});if(typeof sourcePlayer.pauseVideo==='function')sourcePlayer.pauseVideo()}}
function primePendingSource(){{if(!archiveAutoLock||!episodeStarts.length||!sourcePlayer||pendingPriming||pendingPrimeReady)return;const masterSeconds=safeTime(masterPlayer);if(episodeFor(masterSeconds)>=0)return;pendingPriming=true;if(typeof sourcePlayer.mute==='function')sourcePlayer.mute();if(typeof sourcePlayer.playVideo==='function')sourcePlayer.playVideo();setTimeout(()=>{{if(typeof sourcePlayer.pauseVideo==='function')sourcePlayer.pauseVideo();if(typeof sourcePlayer.seekTo==='function')sourcePlayer.seekTo(0,true);if(typeof sourcePlayer.unMute==='function')sourcePlayer.unMute();pendingPriming=false;pendingPrimeReady=true;syncStatus()}},250)}}
function followPlaybackState(){{if(!archiveAutoLock||!syncArmed||!sourcePlayer||liveStandby||liveQueueFinished)return;if(archiveAutoLock&&activeEpisode<0)return;const ms=masterState();if(ms===1&&typeof sourcePlayer.playVideo==='function')sourcePlayer.playVideo();else if((ms===2||ms===0)&&typeof sourcePlayer.pauseVideo==='function')sourcePlayer.pauseVideo()}}
function maybeSwitchEpisode(masterSeconds){{if(!archiveAutoLock||switching||!sourcePlayer)return;const wanted=episodeFor(masterSeconds);if(wanted<0){{preparePending();return}}if(wanted===activeEpisode)return;activeEpisode=wanted;pendingPrepared=false;switching=true;const target=targetFor(masterSeconds);const opts={{videoId:sourceVideoIds[activeEpisode],startSeconds:target}};if(syncArmed&&masterState()===1&&typeof sourcePlayer.loadVideoById==='function')sourcePlayer.loadVideoById(opts);else if(typeof sourcePlayer.cueVideoById==='function')sourcePlayer.cueVideoById(opts);updateAdjustmentStatus();setTimeout(()=>{{switching=false;followPlaybackState()}},700)}}
function syncStatus(){{const masterSeconds=safeTime(masterPlayer);maybeSwitchEpisode(masterSeconds);const wanted=episodeFor(masterSeconds);const sourceSeconds=safeTime(sourcePlayer),target=targetFor(masterSeconds),delta=target-sourceSeconds;if(archiveAutoLock&&wanted<0){{const wait=Math.max(0,episodeStarts[0]-masterSeconds);statusBox.textContent=`Archive Pending\n主時間 ${{fmt(masterSeconds)}} · 第 1 集將於 ${{fmt(episodeStarts[0])}} 開始`;queueBox.textContent=`片源序列：Pending → 1 / ${{sourceVideoIds.length}}`;pendingBox.textContent=`等待第 1 集開始，還有約 ${{fmt(wait)}}；來源保持暫停，不會重播開頭。${{pendingPrimeReady?' 已完成來源播放授權準備。':''}}`;catchupButton.disabled=true;updateAdjustmentStatus();return}}if(liveQueueStandby&&liveStandby){{statusBox.textContent=`即時模式 · 第 ${{activeEpisode+1}} 集已載入待機\n主時間 ${{fmt(masterSeconds)}} · 來源 00:00`;queueBox.textContent=`片源序列：第 ${{activeEpisode+1}} / ${{sourceVideoIds.length}} 集待機中`;pendingBox.textContent='即時模式右側片源完全手動播放；左側播放、暫停、跳轉不會控制右側。Playlist 自動載入下一集但不自動播放。';catchupButton.disabled=true;updateAdjustmentStatus();return}}if(liveQueueStandby&&liveQueueFinished){{statusBox.textContent='即時模式 · Playlist 已播完';queueBox.textContent=`片源序列：${{sourceVideoIds.length}} / ${{sourceVideoIds.length}}`;pendingBox.textContent='Playlist 已沒有下一集；不會自動重播最後一集。';catchupButton.disabled=true;updateAdjustmentStatus();return}}pendingBox.textContent='';let anchorText;if(archiveAutoLock&&episodeStarts.length)anchorText=`Archive 自動對齊：第 ${{activeEpisode+1}} 集 master ${{fmt(episodeStarts[activeEpisode])}} ↔ source 00:00`;else anchorText=anchorReady?`對齊點 master ${{fmt(anchorMaster)}} ↔ source ${{fmt(anchorSource)}}`:'尚未建立對齊點（目前使用初始 0 ↔ 0）';const idx=currentEpisodeIndex();statusBox.textContent=`${{anchorText}}\n主時間 ${{fmt(masterSeconds)}} · 來源 ${{fmt(sourceSeconds)}} · 來源目標 ${{fmt(target)}} · 差 ${{delta>=0?'+':''}}${{delta.toFixed(1)}} 秒 · 基礎校正 ${{correction>=0?'+':''}}${{correction.toFixed(1)}} 秒 · 單集 ${{signed(episodeCorrections[idx])}} · 片源 ${{signed(sourceCorrections[idx])}}`;queueBox.textContent=sourceVideoIds.length>1?`片源序列：${{activeEpisode+1}} / ${{sourceVideoIds.length}}`:'片源序列：1 / 1';catchupButton.disabled=!sourcePlayer||typeof sourcePlayer.seekTo!=='function';updateAdjustmentStatus();if(archiveAutoLock&&syncArmed&&!liveStandby&&!liveQueueFinished&&wanted>=0&&!switching&&masterState()===1&&sourceState()!==1&&sourcePlayer&&typeof sourcePlayer.playVideo==='function')sourcePlayer.playVideo();if(archiveAutoLock&&activeEpisode>=0&&!switching&&Math.abs(delta)>2.5&&masterState()===1&&sourceState()===1)sourcePlayer.seekTo(target,true)}}
function makeAnchor(){{anchorMaster=safeTime(masterPlayer);anchorSource=safeTime(sourcePlayer);correction=0;anchorReady=true;syncStatus()}}
function adjustCorrection(delta){{correction+=delta;syncStatus()}}
function catchUp(){{if(!sourcePlayer||typeof sourcePlayer.seekTo!=='function'||episodeFor(safeTime(masterPlayer))<0)return;sourcePlayer.seekTo(targetFor(safeTime(masterPlayer)),true);syncStatus()}}
function armSync(){{if(!archiveAutoLock){{if(masterPlayer&&typeof masterPlayer.playVideo==='function')masterPlayer.playVideo();syncStatus();return}}const masterSeconds=safeTime(masterPlayer);if(liveQueueStandby){{anchorMaster=masterSeconds;anchorSource=safeTime(sourcePlayer);correction=0;anchorReady=true;liveStandby=false}}syncArmed=true;armButton.textContent='同步播放／重新啟動';maybeSwitchEpisode(masterSeconds);if(archiveAutoLock&&episodeFor(masterSeconds)<0)primePendingSource();if(!liveQueueStandby&&episodeFor(masterSeconds)>=0&&sourcePlayer&&typeof sourcePlayer.seekTo==='function')sourcePlayer.seekTo(targetFor(masterSeconds),true);if(masterPlayer&&typeof masterPlayer.playVideo==='function')masterPlayer.playVideo();if((!archiveAutoLock||episodeFor(masterSeconds)>=0)&&sourcePlayer&&typeof sourcePlayer.playVideo==='function')sourcePlayer.playVideo();syncStatus()}}
function pauseBoth(){{if(masterPlayer&&typeof masterPlayer.pauseVideo==='function')masterPlayer.pauseVideo();if(archiveAutoLock&&sourcePlayer&&typeof sourcePlayer.pauseVideo==='function')sourcePlayer.pauseVideo();syncStatus()}}
function cueLiveEpisodeStandby(index){{activeEpisode=index;liveStandby=true;liveQueueFinished=false;syncArmed=false;anchorReady=false;anchorMaster=safeTime(masterPlayer);anchorSource=0;correction=0;switching=true;const opts={{videoId:sourceVideoIds[activeEpisode],startSeconds:0}};if(typeof sourcePlayer.cueVideoById==='function')sourcePlayer.cueVideoById(opts);armButton.textContent='下一集待機中：手動播放';readyBox.textContent=`第 ${{activeEpisode+1}} 集正在載入待機；請在右側 YouTube 播放器手動開始。`;updateAdjustmentStatus();setTimeout(()=>{{switching=false;syncStatus()}},700)}}
function onSourceStateChange(event){{if(liveQueueStandby&&event){{if(event.data===5&&liveStandby){{switching=false;readyBox.textContent=`第 ${{activeEpisode+1}} 集已載入待機；請在右側 YouTube 播放器手動開始。`;syncStatus();return}}if(event.data===0&&activeEpisode>=0){{if(activeEpisode<sourceVideoIds.length-1){{cueLiveEpisodeStandby(activeEpisode+1);return}}liveQueueFinished=true;liveStandby=false;syncArmed=false;readyBox.textContent='Playlist 已播完；最後一集不會自動重播。';syncStatus();return}}}}syncStatus()}}
function publishPlaybackTelemetry(){{if(!telemetryEndpoint||!telemetryToken||!telemetrySessionId||!masterPlayer)return;const payload={{session_id:telemetrySessionId,master_seconds:safeTime(masterPlayer),player_state:masterState()}};fetch(telemetryEndpoint,{{method:'POST',headers:{{'Content-Type':'application/json','X-Watchalong-Telemetry-Token':telemetryToken}},body:JSON.stringify(payload),cache:'no-store'}}).catch(()=>{{}})}}
function onMasterStateChange(){{if(archiveAutoLock&&masterState()===1&&!syncArmed){{syncArmed=true;armButton.textContent='同步播放／重新啟動'}}followPlaybackState();syncStatus();publishPlaybackTelemetry()}}
document.getElementById('arm').onclick=armSync;document.getElementById('pause-both').onclick=pauseBoth;document.getElementById('anchor').onclick=makeAnchor;document.getElementById('minus5').onclick=()=>adjustCorrection(-5);document.getElementById('minus1').onclick=()=>adjustCorrection(-1);document.getElementById('plus1').onclick=()=>adjustCorrection(1);document.getElementById('plus5').onclick=()=>adjustCorrection(5);document.getElementById('catchup').onclick=catchUp;document.getElementById('layout-compare').onclick=()=>setLayout('compare');document.getElementById('layout-focus').onclick=()=>setLayout('focus');
document.querySelectorAll('[data-episode-delta]').forEach(button=>button.onclick=()=>adjustEpisode(button.dataset.episodeDelta));document.querySelectorAll('[data-source-delta]').forEach(button=>button.onclick=()=>adjustSourceFromHere(button.dataset.sourceDelta));
window.onYouTubeIframeAPIReady=function(){{masterPlayer=new YT.Player('master-player',{{videoId:masterVideoId,width:'100%',height:'100%',playerVars:{{playsinline:1,rel:0}},events:{{onReady:()=>{{readyBox.textContent=archiveAutoLock?'Archive 自動模式：不需要手動建立對齊點；請按一次「同步播放／啟動跟隨」。Pending 時會先啟用來源播放器，等 transcript cue 到點後自動選集／seek／播放。手動對齊只在進階區作為覆寫。':'Live：右側來源獨立控制；播放左側不會讓右側自動開始。';updateAdjustmentStatus();syncStatus();publishPlaybackTelemetry()}},onStateChange:onMasterStateChange}}}});sourcePlayer=new YT.Player('source-player',{{videoId:sourceVideoIds[0],width:'100%',height:'100%',playerVars:{{playsinline:1,rel:0}},events:{{onReady:()=>{{const m=safeTime(masterPlayer);if(archiveAutoLock&&episodeStarts.length&&episodeFor(m)<0)preparePending();else if(archiveAutoLock&&episodeStarts.length){{activeEpisode=episodeFor(m);const opts={{videoId:sourceVideoIds[activeEpisode],startSeconds:targetFor(m)}};if(typeof sourcePlayer.cueVideoById==='function')sourcePlayer.cueVideoById(opts)}}else activeEpisode=0;if(liveQueueStandby){{liveStandby=true;syncArmed=false;if(typeof sourcePlayer.pauseVideo==='function')sourcePlayer.pauseVideo();readyBox.textContent='即時模式：左側直播與右側片源獨立控制。請自行播放右側片源；Playlist 播完一集會載入下一集並保持待機。'}}updateAdjustmentStatus();syncStatus()}},onStateChange:onSourceStateChange}}}});setInterval(syncStatus,500);setInterval(publishPlaybackTelemetry,telemetryIntervalMs)}};
const api=document.createElement('script');api.src='https://www.youtube.com/iframe_api';document.head.appendChild(api);
</script></body></html>"""