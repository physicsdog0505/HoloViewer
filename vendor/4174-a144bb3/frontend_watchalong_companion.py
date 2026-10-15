"""Authenticated-browser companion mode for non-embeddable watch-along providers."""

from __future__ import annotations

import json


def build_companion_watchalong_html(
    *,
    master_video_id: str,
    provider_label: str,
    initial_correction_seconds: float = 0.0,
) -> str:
    """Render the Hololive master clock plus a manual source-position companion.

    The external provider remains in the user's normal browser tab/window so login,
    quality, subscription state, and provider-native ads stay under provider control.
    This component never attempts to inspect or control that external tab.
    """
    master = json.dumps(master_video_id)
    provider = json.dumps(provider_label, ensure_ascii=False)
    correction = float(initial_correction_seconds)

    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background:#0b0b0b; color:#eee; font-family:-apple-system,BlinkMacSystemFont,"Noto Sans TC",sans-serif; }}
#layout {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr); gap:10px; }}
.card {{ border:1px solid #2b2b2b; background:#111; min-width:0; }}
.head {{ padding:7px 9px; font-size:13px; font-weight:700; border-bottom:1px solid #2b2b2b; }}
.player-wrap {{ position:relative; width:100%; aspect-ratio:16/9; background:#000; }}
#master-player {{ position:absolute; inset:0; width:100%; height:100%; }}
#side {{ padding:12px; display:grid; gap:10px; }}
#status {{ white-space:pre-wrap; font:13px ui-monospace,SFMono-Regular,Menlo,monospace; line-height:1.45; }}
label {{ display:grid; gap:5px; font-size:12px; color:#bbb; }}
input {{ width:100%; border:1px solid #444; background:#1b1b1b; color:#eee; border-radius:6px; padding:8px; font:14px ui-monospace,SFMono-Regular,Menlo,monospace; }}
.row {{ display:flex; flex-wrap:wrap; gap:7px; }}
button {{ border:1px solid #444; background:#1e1e1e; color:#eee; border-radius:6px; padding:7px 10px; cursor:pointer; }}
button.primary {{ background:#2457d6; border-color:#3768e7; }}
.note {{ color:#aaa; font-size:12px; line-height:1.45; }}
#target {{ font-size:24px; font-weight:750; letter-spacing:.02em; }}
@media (max-width:820px) {{ #layout {{ grid-template-columns:1fr; }} }}
</style></head><body>
<div id="layout">
  <section class="card">
    <div class="head">Hololive 直播（主時間軸）</div>
    <div class="player-wrap"><div id="master-player"></div></div>
  </section>
  <section class="card"><div class="head" id="provider-head"></div><div id="side">
    <div class="note">外部片源留在你原本已登入的瀏覽器分頁。此頁不讀取帳密、不控制該分頁，也不猜廣告時間。</div>
    <label>外部片源目前時間（HH:MM:SS 或 MM:SS）
      <input id="source-time" value="00:00" inputmode="numeric" placeholder="例如 12:34">
    </label>
    <button id="anchor" class="primary">以目前位置建立對齊點</button>
    <div>目前應播放到：<span id="target">00:00</span></div>
    <div class="row">
      <button id="minus5">來源 -5 秒</button><button id="minus1">來源 -1 秒</button>
      <button id="plus1">來源 +1 秒</button><button id="plus5">來源 +5 秒</button>
    </div>
    <button id="copy" class="primary">複製目標時間</button>
    <div id="status">等待播放器…</div>
    <div class="note">前置廣告：先在外部分頁播完，再把實際片源位置填入並建立對齊點。中插廣告：主時間照走；廣告結束後依「目前應播放到」手動 seek 回去。若平台未提供可安全控制的 API，就維持這個 companion 流程。</div>
  </div></section>
</div>
<script>
const masterVideoId = {master};
const providerLabel = {provider};
let masterPlayer = null;
let anchorMaster = 0;
let anchorSource = 0;
let correction = {correction};
let anchorReady = false;
const statusBox = document.getElementById('status');
const targetBox = document.getElementById('target');
document.getElementById('provider-head').textContent = `${{providerLabel}}（已登入瀏覽器 companion）`;

function safeMasterTime() {{
  if (!masterPlayer || typeof masterPlayer.getCurrentTime !== 'function') return 0;
  const value = Number(masterPlayer.getCurrentTime() || 0);
  return Number.isFinite(value) && value >= 0 ? value : 0;
}}
function parseClock(text) {{
  const parts = String(text || '').trim().split(':').map(Number);
  if (!parts.length || parts.some(v => !Number.isFinite(v) || v < 0)) return null;
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 1) return parts[0];
  return null;
}}
function fmt(seconds) {{
  seconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return (h ? String(h).padStart(2,'0') + ':' : '') + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
}}
function targetFor(masterSeconds) {{
  return Math.max(0, anchorSource + (masterSeconds - anchorMaster) + correction);
}}
function render() {{
  const master = safeMasterTime();
  const target = targetFor(master);
  targetBox.textContent = fmt(target);
  const anchorText = anchorReady ? `對齊點 master ${{fmt(anchorMaster)}} ↔ source ${{fmt(anchorSource)}}` : '尚未建立對齊點';
  statusBox.textContent = `${{anchorText}}\n主時間 ${{fmt(master)}} · 目標 ${{fmt(target)}} · 手動校正 ${{correction >= 0 ? '+' : ''}}${{correction.toFixed(1)}} 秒`;
}}
function anchor() {{
  const source = parseClock(document.getElementById('source-time').value);
  if (source === null) {{ statusBox.textContent = '外部片源時間格式無法辨識'; return; }}
  anchorMaster = safeMasterTime(); anchorSource = source; correction = 0; anchorReady = true; render();
}}
function adjust(delta) {{ correction += delta; render(); }}
document.getElementById('anchor').onclick = anchor;
document.getElementById('minus5').onclick = () => adjust(-5);
document.getElementById('minus1').onclick = () => adjust(-1);
document.getElementById('plus1').onclick = () => adjust(1);
document.getElementById('plus5').onclick = () => adjust(5);
document.getElementById('copy').onclick = async () => {{
  const text = targetBox.textContent;
  try {{ await navigator.clipboard.writeText(text); statusBox.textContent += `\n已複製 ${{text}}`; }}
  catch (_) {{ statusBox.textContent += `\n無法自動複製，請手動記下 ${{text}}`; }}
}};
window.onYouTubeIframeAPIReady = function() {{
  masterPlayer = new YT.Player('master-player', {{ videoId: masterVideoId, width:'100%', height:'100%', playerVars:{{playsinline:1,rel:0}}, events:{{onReady:render,onStateChange:render}} }});
  setInterval(render, 250);
}};
const api = document.createElement('script'); api.src='https://www.youtube.com/iframe_api'; document.head.appendChild(api);
</script></body></html>"""
