/* Direct DOM transplant from shared_viewing_core.py @ a144bb378a8bdd772faa867d608c1e7491253883.
 * Only the server-injected PTT fragment is selected at runtime. */
window.render4174SharedViewerDOM=function render4174SharedViewerDOM(showLivePtt){
 const pttPanel=showLivePtt?
 '<aside class="ptt-live-panel" aria-label="PTT 今日專串"><div class="ptt-panel-heading"><span>PTT 今日專串<small>今日公開推文・尚未與影片時間軸連動</small></span><a href="/ptt-today" target="_blank" rel="noopener">獨立閱讀 ↗</a><span class="ptt-embed-controls"><label class="ptt-embed-floor"><input id="pttEmbedShowFloor" type="checkbox" checked> 樓</label><label class="ptt-embed-font">字體 <input id="pttFontSize" type="range" min="12" max="26" value="16" step="2" aria-label="調整推文字體大小"><output id="pttFontValue">16px</output></label></span></div><iframe title="PTT 今日專串即時閱讀" src="/ptt-today?focus=1&embed=1" loading="lazy"></iframe></aside>':'';
 return `
<div class="viewer-workspace">
  <div class="viewer-head">
    <h1>自訂觀看</h1>
    <a class="subtle-action" href="/custom-view">調整觀看清單</a>
  </div>
  <div class="watch-actions"><div class="watch-mode-switch" role="group" aria-label="觀看模式"><button type="button" id="watchSingleMode" aria-pressed="true">單人</button><button type="button" id="watchModeToggle" class="watch-mode-toggle" role="switch" aria-checked="false" aria-label="切換單人／多人模式"></button><button type="button" id="watchMultiMode" aria-pressed="false">多人</button></div><label class="global-volume-label">總音量 <input id="globalVolume" type="range" min="0" max="100" value="100" aria-label="所有視角總音量"><output id="globalVolumeValue">100%</output></label><button type="button" id="watchSettings" aria-expanded="false">設定</button><button type="button" id="watchImmersive">沉浸模式</button></div><label class="immersive-global-volume">總音量 <input id="immersiveGlobalVolume" type="range" min="0" max="100" value="100" aria-label="沉浸模式總音量"><output id="immersiveGlobalVolumeValue">100%</output></label><div class="player-toolbar">
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
  <div class="custom-content-grid${showLivePtt?'':' video-only'}"><div class="custom-player-column"><main id="stage"></main><div class="translation-slot" id="translationSlot" aria-label="VOD 翻譯字幕" hidden><div class="translation-track-controls"><button type="button" id="translationA">A方案</button><button type="button" id="translationB">B方案</button></div><div id="translationStatus" class="note"></div><div id="translationText" class="translation-text"></div></div></div>${pttPanel}</div>
</div>`;
};
