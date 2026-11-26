# 06 — 多視角播放器 / Multi-view player

## 繁體中文

### 問題

多視角播放器不是單純建立多個 YouTube iframe。實際上需要同時管理：

- 最多可掛載多少影片；
- 哪一個是主視角；
- 哪一個輸出聲音；
- 使用者切換版型時是否會打斷播放；
- play / pause 是否連動；
- 新增或移除 POV 時如何維持狀態；
- live collab 與 historical VOD collab 如何區分；
- 有 timeline 時與沒有 timeline 時，seek 行為不能混用。

目前公開 viewer 最多接受：

    MAX_STREAMS = 16

這是 UI / browser runtime 上限，不是 YouTube 平台本身的通用限制。

### Player identity 與 DOM lifecycle

每一個 stream 以 YouTube video ID 作為 player source identity。

播放器由 YouTube IFrame API 建立。

一個重要設計原則是：

> 版型變更只改 CSS geometry，不搬動既有 iframe DOM node。

因為移動或重新掛載 YouTube iframe 可能中斷正在播放的 player state。

因此 equal / primary / focus 之間切換，優先保留既有 player instance。

### 主視角與音訊是兩個概念

系統同時維護：

- primaryIndex：目前主要視角；
- audioMaster：目前允許輸出聲音的 player。

切換主視角時，目前實作會同步把 audioMaster 切到新的 primary，並：

- 新 primary unmute；
- 其他 players mute。

這避免多個 POV 同時輸出音訊造成重疊。

但架構上 primary 與 audio 是兩個獨立 state，因此未來仍可以支援「畫面看 A、聲音聽 B」。

### 一般多人觀看的連動播放

一般 multi-view 的「連動播放」只同步：

- PLAYING
- PAUSED

當任一 player 發生使用者觸發的 play / pause：

    source player state change
        ↓
    propagate same play/pause state
        ↓
    other mounted players

它不代表所有影片被強制 seek 到相同秒數。

這個 distinction 很重要。

如果兩支直播本來開台時間不同，單純將兩個 YouTube player 都跳到第 300 秒，並不代表它們處於同一個真實事件時間。

因此：

    linked transport != timeline synchronization

### 避免 state-change feedback loop

如果程式對 Player B 呼叫 playVideo()，B 又會產生 onStateChange。

如果不處理，就可能：

    A triggers B
    B triggers A
    A triggers B
    ...

目前使用一個短期 expected-state marker。

概念：

    before programmatic play/pause:
        expected[player] = {state, expiry}

    on state change:
        if state matches expected before expiry:
            consume expected marker
            do not propagate again

目前 expiry window 是約 900 ms。

這不是同步精度，而是避免程式觸發的 state event 被誤判成新的使用者操作。

### 全部播放 / 全部暫停

Viewer 也提供 explicit transport controls，讓使用者一次對所有已掛載 players 發出 play 或 pause。

瀏覽器 autoplay policy 仍然存在，因此不能假設所有 programmatic play 都一定成功。

這也是為什麼 viewer 不應把「呼叫 playVideo 成功送出」等同「所有 player 已確實進入 playing」。

### 新增 POV

多人模式加入新影片時：

- 先檢查 video ID；
- 避免重複加入；
- 超過 MAX_STREAMS 則拒絕；
- 建立新的 card / player host；
- 如果主 player 當下正在播放，可以讓新 player 以相同 run intent 啟動；
- 如果有 timeline，則先計算對應 source time 再 mount。

沒有 timeline 的普通 live multi-view，不會自行猜測「應該 seek 到主視角第幾秒」。

### 移除 POV

移除 player 時：

- destroy 該 YouTube player；
- 移除 card；
- 重新整理 stream / player array index；
- 如果移除的是 primary，選擇下一個有效 primary；
- audio master 跟著重新指定；
- focus / layout state 重新計算。

這些 state mutation 必須一起做，否則 UI index 與 player index 很容易漂移。

### 切換單人 / 多人模式

從多人切回單人時，目前保留當下 primary POV：

    selected primary
        ↓
    destroy other players
        ↓
    rebuild single-player state

這比永遠保留第一個加入的影片更符合使用者意圖。

### Live collab 與 VOD collab

兩者不能使用相同同步假設。

#### Live collab

live collab 主要處理：

- 哪些 POV 目前 lifecycle = live；
- 新 POV 開播時加入；
- 已不在 active set 的 POV 移除。

它不假設可以取得完整歷史共同時間軸。

#### VOD collab

VOD collab 若 event 明確標記 sync available，可以建立 viewing timeline。

只有這種情況，viewer 才進入 master-time based synchronization。

### 版型與播放狀態分離

equal / primary / focus / carousel 是 presentation state。

播放與時間軸則是 playback state。

架構刻意避免讓：

    layout change
        ↓
    recreate iframe

因為 presentation mutation 不應破壞 media session。

### 已確認的風險／避免做法

#### F-019 — 搬動 iframe 來排版
Status: explicitly avoided.

風險：重新 append / transplant iframe 可能造成 YouTube player 中斷或 state reset。

目前做法：CSS-only geometry。

#### F-020 — play/pause 事件互相遞迴
Status: explicitly avoided.

風險：programmatic state change 被其他 player 當成新的 source event。

目前做法：短期 expected-state suppression。

#### F-021 — 一般多人模式把相同秒數當同一事件時間
Status: explicitly avoided.

風險：不同開台時間的 POV 在相同 source second 並不代表相同 absolute time。

目前做法：普通 multi-view 只連動 transport；需要真正時間同步時使用 Chapter 07 的 master timeline。

### 限制

- YouTube iframe API 與瀏覽器 autoplay policy 會影響實際播放；
- player buffering 狀態不能被當成精確 clock；
- 一般 live multi-view 沒有完整 master timeline 時，不保證跨 POV 的內容對齊；
- 16 streams 是目前 UI/runtime contract，不代表實務上 16 路同時播放在所有裝置都能流暢；
- 多 player 對 CPU、記憶體、網路與 decoder 都有成本。

### 可替代方案

其他實作可以考慮：

- 單一 audio graph 管理多 player 聲音；
- visibility-aware player suspension；
- lazy mount 非可見 POV；
- offscreen preview image 取代持續解碼；
- player state machine 明確區分 USER_EVENT 與 PROGRAMMATIC_EVENT；
- adaptive stream limit 依裝置能力調整。

目前 HoloDocchi 優先保持 iframe identity 穩定與 state 可解釋，不宣稱是資源效率最佳方案。

---

## English

### Problem

A multi-view player is not simply a collection of YouTube iframes. It must manage:

- how many streams can be mounted;
- which POV is primary;
- which player owns audio;
- whether layout changes interrupt playback;
- whether play/pause actions propagate;
- how POVs are added or removed without state drift;
- how live and historical collaboration modes differ;
- why seek behavior must change when an explicit timeline exists.

The current public viewer accepts at most:

    MAX_STREAMS = 16

This is a UI/browser runtime contract, not a universal YouTube limit.

### Player identity and DOM lifecycle

Each stream uses a YouTube video ID as its media-source identity and is mounted through the YouTube IFrame API.

A key design rule is:

> Layout changes alter CSS geometry rather than moving existing iframe DOM nodes.

Moving or recreating an active YouTube iframe can interrupt playback state.

### Primary POV and audio ownership

The viewer separately maintains:

- primaryIndex: the visually primary POV;
- audioMaster: the player allowed to output audio.

Current behavior moves audio ownership with primary selection:

- new primary is unmuted;
- other players are muted.

The two states remain architecturally separate, allowing future designs such as watching POV A while listening to POV B.

### Linked playback in ordinary multi-view mode

The ordinary multi-view “sync playback” control propagates only:

- PLAYING
- PAUSED

A user-generated state change is propagated to the other mounted players.

It does **not** mean all videos are force-seeked to the same source second.

This distinction matters because two streams that began at different real times are not aligned merely because both are at source second 300.

Therefore:

    linked transport != timeline synchronization

### Preventing state-change feedback loops

Programmatically calling playVideo() on Player B generates its own state event.

Without suppression, propagation can loop between players.

The viewer stores a short-lived expected-state marker before programmatic play/pause. If the matching state event arrives before expiry, it is consumed rather than propagated again.

The current suppression window is approximately 900 ms.

This is an event-loop guard, not a synchronization-accuracy target.

### Explicit play-all / pause-all

The viewer also provides controls that issue play or pause to all mounted players.

Browser autoplay policy still applies, so issuing playVideo() is not proof that every player actually entered PLAYING.

### Adding a POV

When a new stream is added:

- validate the video ID;
- reject duplicates;
- enforce MAX_STREAMS;
- create a new card/player host;
- optionally preserve the current run intent;
- if an explicit timeline exists, resolve the target source time before mounting.

In ordinary live multi-view mode, the viewer does not invent a seek offset relative to the primary player.

### Removing a POV

Removal destroys the YouTube player, removes its card, reindexes stream/player arrays, selects a valid replacement primary when needed, reassigns audio ownership, and recalculates layout/focus state.

These mutations must remain coordinated to avoid UI/player index drift.

### Switching between single and multi mode

When moving from multi-view back to single-view, the current primary POV is retained and other players are destroyed.

This preserves the user's active choice rather than always keeping the first-added stream.

### Live collaboration versus VOD collaboration

#### Live collaboration

Live collaboration primarily reconciles which POVs are currently active.

New live POVs can be added and no-longer-active POVs removed, but the system does not assume a complete historical master timeline exists.

#### VOD collaboration

When an event explicitly declares synchronization available, the viewer can initialize the master timeline described in Chapter 07.

Only then does synchronization become master-time based.

### Presentation state is separate from playback state

Equal, primary, focus and carousel are presentation states.

Playback and timeline state are media states.

The architecture avoids:

    layout change
        ↓
    recreate iframe

because presentation changes should not destroy the media session.

### Failed / risky approaches

#### F-019 — Moving iframes to implement layout
Status: explicitly avoided.

Risk: DOM reparenting/recreation can interrupt YouTube playback.

Current design: CSS-only geometry.

#### F-020 — Recursive play/pause propagation
Status: explicitly avoided.

Risk: programmatic state changes are mistaken for new source events.

Current design: short-lived expected-state suppression.

#### F-021 — Treating equal source seconds as equal event time
Status: explicitly avoided.

Risk: different stream start times make equal source seconds semantically different.

Current design: ordinary multi-view synchronizes transport only; true temporal alignment uses the master timeline in Chapter 07.

### Limitations

- YouTube iframe behavior and browser autoplay policy affect actual playback;
- buffering cannot be treated as a precise clock;
- ordinary live multi-view without a master timeline does not guarantee content alignment across POVs;
- 16 streams is a current UI/runtime contract, not a guarantee that all devices can decode 16 concurrent videos smoothly;
- multiple active players consume CPU, memory, bandwidth and decoder resources.

### Alternatives

Possible improvements include:

- centralized audio management;
- visibility-aware player suspension;
- lazy mounting for offscreen POVs;
- preview images instead of continuous decoding;
- an explicit USER_EVENT / PROGRAMMATIC_EVENT player state machine;
- adaptive stream limits based on device capability.

HoloDocchi currently prioritizes stable iframe identity and explainable state over claiming maximum resource efficiency.

[回目錄 / Index](README.md)
