"""Multi-stream YouTube collab player components.

Playback/layout state stays inside one browser component so audio-master and
per-player volume changes do not recreate YouTube players. The shared stream model
supports the verified two-person baseline and the staged four-person 2x2 layout.
"""

from __future__ import annotations

from dataclasses import dataclass
import json


@dataclass(frozen=True)
class CollabStream:
    """One stream in a collab session.

    ``sync_offset_ms`` is retained for archived real-world-time alignment.
    """

    video_id: str
    label: str
    volume: int = 100
    sync_offset_ms: int = 0

    def __post_init__(self) -> None:
        if not self.video_id.strip():
            raise ValueError("video_id must not be empty")
        if not 0 <= int(self.volume) <= 100:
            raise ValueError("volume must be between 0 and 100")


def build_multistream_player_html(
    streams: list[CollabStream],
    *,
    audio_master: int = 0,
) -> str:
    """Build a fixed-layout two- or four-person live collab surface.

    Four streams use a fixed 2x2 grid. The browser owns player instances after
    creation; audio-master switches and volume sliders call the IFrame API directly.
    """

    if len(streams) not in (2, 4):
        raise ValueError("multi-stream player requires exactly two or four streams")
    if not 0 <= audio_master < len(streams):
        raise ValueError("audio_master must reference an existing stream")

    payload = json.dumps(
        [
            {
                "videoId": stream.video_id,
                "label": stream.label or f"Stream {index + 1}",
                "volume": int(stream.volume),
                "syncOffsetMs": int(stream.sync_offset_ms),
            }
            for index, stream in enumerate(streams)
        ],
        ensure_ascii=False,
    ).replace("<", "\\u003c").replace(">", "\\u003e")

    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; background: #090909; color: #eee;
  font-family: -apple-system, BlinkMacSystemFont, "Noto Sans TC", sans-serif; }}
#root {{ padding: 8px; }}
#players {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
.card {{ min-width: 0; background: #111; border: 1px solid #2b2b2b; border-radius: 8px;
  overflow: hidden; }}
.video-wrap {{ position: relative; width: 100%; aspect-ratio: 16 / 9; background: #000; }}
.player {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.controls {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px;
  align-items: center; padding: 9px 10px; }}
.meta {{ min-width: 0; }}
.label {{ font-size: 13px; font-weight: 700; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }}
.audio-row {{ display: flex; align-items: center; gap: 8px; margin-top: 7px; }}
.audio-row input[type=range] {{ flex: 1; min-width: 80px; }}
.volume {{ color: #aaa; font-size: 12px; min-width: 34px; text-align: right; }}
.master {{ border: 1px solid #444; background: #202020; color: #eee; border-radius: 6px;
  padding: 7px 9px; cursor: pointer; white-space: nowrap; }}
.master.active {{ background: #f1f1f1; color: #111; border-color: #f1f1f1; font-weight: 700; }}
#status {{ padding: 8px 10px 2px; color: #aaa; font-size: 12px; }}
@media (max-width: 760px) {{
  #players {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div id="root">
  <div id="players"></div>
  <div id="status">載入 YouTube 播放器…</div>
</div>
<script>
const streams = {payload};
let audioMaster = {audio_master};
const players = Array(streams.length).fill(null);
const playerHost = document.getElementById('players');
const statusBox = document.getElementById('status');

function clampVolume(value) {{
  return Math.max(0, Math.min(100, Number(value) || 0));
}}

function applyAudioState() {{
  players.forEach((player, index) => {{
    if (!player || typeof player.setVolume !== 'function') return;
    player.setVolume(clampVolume(streams[index].volume));
    if (index === audioMaster) player.unMute(); else player.mute();
  }});
  document.querySelectorAll('.master').forEach((button, index) => {{
    const active = index === audioMaster;
    button.classList.toggle('active', active);
    button.textContent = active ? '主聲源 🔊' : '切換聲音';
  }});
  statusBox.textContent = `目前主聲源：${{streams[audioMaster].label}} · 即時模式不強制時間同步`;
}}

function buildCard(stream, index) {{
  const card = document.createElement('section');
  card.className = 'card';
  card.innerHTML = `
    <div class="video-wrap"><div id="player-${{index}}" class="player"></div></div>
    <div class="controls">
      <div class="meta">
        <div class="label"></div>
        <div class="audio-row">
          <span>音量</span>
          <input class="slider" type="range" min="0" max="100" step="1">
          <span class="volume"></span>
        </div>
      </div>
      <button class="master" type="button"></button>
    </div>`;
  card.querySelector('.label').textContent = stream.label;
  const slider = card.querySelector('.slider');
  const volume = card.querySelector('.volume');
  slider.value = stream.volume;
  volume.textContent = `${{stream.volume}}%`;
  slider.addEventListener('input', event => {{
    stream.volume = clampVolume(event.target.value);
    volume.textContent = `${{stream.volume}}%`;
    const player = players[index];
    if (player && typeof player.setVolume === 'function') player.setVolume(stream.volume);
  }});
  card.querySelector('.master').addEventListener('click', () => {{
    audioMaster = index;
    applyAudioState();
  }});
  return card;
}}

streams.forEach((stream, index) => playerHost.appendChild(buildCard(stream, index)));

window.onYouTubeIframeAPIReady = function() {{
  let ready = 0;
  streams.forEach((stream, index) => {{
    players[index] = new YT.Player(`player-${{index}}`, {{
      videoId: stream.videoId,
      width: '100%', height: '100%',
      playerVars: {{ playsinline: 1, rel: 0, controls: 1 }},
      events: {{
        onReady: () => {{
          ready += 1;
          applyAudioState();
          if (ready === streams.length) statusBox.textContent = `${{streams.length}} 個播放器已就緒 · 主聲源：${{streams[audioMaster].label}}`;
        }}
      }}
    }});
  }});
}};
const api = document.createElement('script');
api.src = 'https://www.youtube.com/iframe_api';
document.head.appendChild(api);
</script>
</body>
</html>"""
