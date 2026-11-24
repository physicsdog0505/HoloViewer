# 07 — 共同時間軸引擎 / Master timeline engine

## 繁體中文

### 問題

真正的多視角同步不能直接比較每支影片的 source second。

假設：

- POV A 19:00 開播；
- POV B 19:07 開播。

那麼：

    A at 10:00
    B at 10:00

代表的真實時間不同。

因此 HoloDocchi 建立一條 session master timeline，把每個 POV 的影片片段映射到同一事件座標系。

### Session model

目前 schema：

    holoviewer-viewing-timeline-v1

一個 session 至少包含：

- session_id；
- absolute_start_ms；
- master_end_ms；
- 一個以上 POV；
- 每個 POV 的零個以上 segments。

每個 segment 至少包含：

- segment_id；
- video_id；
- master_start_ms；
- master_end_ms；
- source_start_ms。

### 三種時間

必須區分：

#### 1. Absolute time

真實世界中的時間，例如 Unix epoch milliseconds。

#### 2. Master time

相對於整個 session 起點的時間：

    absolute_time
    =
    session.absolute_start_ms
    +
    master_time

#### 3. Source time

某一支 YouTube video 內的播放時間。

對 segment：

    source_time
    =
    segment.source_start_ms
    +
    (master_time - segment.master_start_ms)

這是整個同步系統最核心的換算。

### 範例

假設 session 起點是 19:00。

POV B 到 19:07 才開播。

則 POV B segment：

    master_start = 7 min
    source_start = 0

當 master time = 12 min：

    source_time_B
    = 0 + (12 - 7)
    = 5 min

所以此時：

- A 可能在 source 12:00；
- B 在 source 05:00；
- 但兩者對應的是同一 absolute event time。

### Segment 讓一個 POV 可以跨多支影片

一個 POV 不一定只有一支 video。

如果直播斷線重開、分 Part、或來源需要換片，單一 POV 可以有多個 segment。

規格要求：

- segment 不得 overlap；
- master_end > master_start；
- segment 必須位於 session 範圍內；
- 同 POV 的 segment_id 不得重複。

master time 進入下一個 segment 時，viewer 可以換成新的 video_id，並 seek 到對應 source_start。

因此：

    POV identity != video identity

這是處理斷線重開的重要抽象。

### NO_COVERAGE 是正式狀態

如果某 POV 在目前 master time 沒有 segment，resolver 回傳：

    NO_COVERAGE

而不是：

- 猜最近一支影片；
- clamp 到 0 秒；
- 繼續播放上一支影片；
- 假裝該 POV 有內容。

這讓「這段時間這個 POV 本來就沒有直播」可以被正確表示。

### READY resolution

當有 coverage 時，resolver 回傳：

- pov_id；
- segment_id；
- video_id；
- master_time_ms；
- source_time_ms；
- absolute_time_ms。

Viewer 不需要自己重算 segment mapping。

### Master clock owner

Runtime 會選一個 clock POV 作為可觀測 media clock 來源。

目前初始化使用 session 的第一個 POV 作為 clock POV。

當該 player 處於：

- PLAYING；
- PAUSED；
- BUFFERING；

而且目前 segment READY 時，系統讀取 getCurrentTime()，再反推 master time。

### Source → Master 的反向換算

給定：

- pov_id；
- video_id；
- source_time；

adapter 尋找符合該 video 的 segment，計算：

    master_time
    =
    segment.master_start
    +
    (source_time - segment.source_start)

如果同一 video 在多個 segment 出現，候選會依「離目前 master time 最近」排序，以減少 ambiguous mapping。

### Clock fallback

如果當下無法從 owner player 得到可靠 mapped master time，但 session 被視為正在播放，clock policy 會依 wall-clock elapsed 前進 master time。

因此模型是：

    mapped media clock preferred
    else running wall-clock progression
    else hold current master time

這避免短暫無法讀 player time 時 master timeline 完全停止。

### Drift detection

系統會把本次 player 反推的 master candidate 與上一個 clock sample 推估值比較。

若差距超過：

    2500 ms

則標記 resync pending。

這個 2.5 秒是目前 implementation threshold，不是物理上「同步誤差一定小於 2.5 秒」的保證。

### Resync

當 resync pending 時，其他非 clock POV 會重新計算 target source time。

如果目前 player time 與 target 差距超過：

    1.2 seconds

才執行 seekTo()。

這個 threshold 是避免非常小的播放器 jitter 造成持續 seek。

因此：

    detect large master drift > 2.5s
        ↓
    recalc other POV target
        ↓
    seek only if source drift > 1.2s

### Reconcile cadence

timeline runtime 目前每：

    500 ms

執行一次 reconcile，前提是 document 沒有 hidden。

這不代表每 500 ms 都 seek。

大多數 tick 只是：

- sample clock；
- resolve coverage；
- 確認目前 video segment；
- 在必要時才 replace / seek / pause。

### Gap handling

如果 POV 進入 NO_COVERAGE：

- 記錄它處於 timeline gap；
- 若 player 正在 PLAYING，將它 pause；
- 不對該 POV 猜測 source position。

當之後重新進入 READY：

- seek 到新的 target source time；
- 如果 session 有 run intent，再 resume play。

因此 gap 是 timeline 的一級狀態，不是 error。

### Segment 切換 / 斷線重開

如果 plan 顯示目前 POV 應該使用不同 video_id：

    resolved.replace = true

viewer 會：

1. 讀取原 player playing / mute 狀態；
2. destroy 原 player；
3. 更新 stream.videoId；
4. 建立新的 player host；
5. mount 新 video；
6. seek 到新的 source_time；
7. 恢復合理的 playing / mute 狀態。

這讓同一 POV 可以跨影片持續存在。

### Coverage 也會影響 UI

在 VOD collab timeline mode 中，只有目前 READY 的 POV 才被視為 visible。

如果目前 primary POV 進入 gap，viewer 會選下一個有 coverage 的 POV 當 primary，並同步更新 audio master。

也就是 timeline 不只控制 seek，也控制「此時間點哪些視角實際存在」。

### Play / pause 與 timeline 的關係

player state change 仍會維持 session run intent。

但 timeline synchronization 與 Chapter 06 的簡單 linked transport 不同：

- linked transport：傳播 PLAYING / PAUSED；
- timeline：決定每個 POV 此刻應該是哪支 video、哪個 source second、是否有 coverage。

兩者可以同時存在，但責任不同。

### 為什麼 share-link 不直接保存 master time

目前 timeline master-time share restore 被刻意停用。

原因是 browser autoplay / user gesture policy 可能造成：

    URL says master time = X
    but actual YouTube clock did not start there

如果頁面一載入就相信 URL master time，internal timeline 可能與真實 player clock 分離。

因此目前 runtime 從自己的 session origin 建立狀態，不把 share URL 當 clock authority。

這是一個已明確 parked 的功能，而不是缺少實作。

### Schema validation

Timeline 在使用前會 fail closed 檢查：

- schema version；
- session_id 格式；
- absolute_start 非負整數；
- master_end > 0；
- POV ID 唯一；
- segment ID 唯一；
- video ID 合法；
- master range 合法；
- source_start 非負；
- segment 不 overlap；
- segment 不超過 session end。

無效 timeline 不應進入同步 runtime。

### 已確認失敗／風險

#### F-022 — 相同 source second 當成相同真實時間
Status: explicitly avoided.

修正：使用 master / absolute / source 三層時間。

#### F-023 — Timeline gap 時繼續播放上一段
Status: explicitly avoided.

修正：NO_COVERAGE 時 pause 該 POV，等待重新進入 READY。

#### F-024 — 每次微小誤差都 seek
Status: explicitly avoided.

修正：使用 drift threshold，只有顯著偏差才 resync。

#### F-025 — 用 URL restore 的 master time 當實際 player clock
Status: parked after identifying browser-policy risk.

問題：autoplay / gesture policy 可能讓 URL time 與 player 實際 clock 分離。

目前不序列化／恢復 timeline master time。

### Trade-offs

- 第一個 POV 作為 clock owner 是簡單策略，不代表永遠最穩；
- 500 ms reconcile 有一定 CPU 成本；
- wall-clock fallback 只是短期 continuity，不能取代 media clock；
- seek threshold 太小會震盪，太大則 drift 可見；
- YouTube getCurrentTime 精度與 buffering 行為不完全由 HoloDocchi 控制；
- segment mapping 正確性依賴 upstream actual_start / actual_end evidence。

### 可替代方案

#### Dynamic clock-owner election

依 player state、buffer health、visibility 或最近誤差動態選最可靠 POV。

#### Median clock

同時讀多個 POV，把可映射的 master candidates 做 median / robust estimate，降低單一 player 抖動影響。

#### PID / gradual correction

不是直接 seek，而是對小 drift 使用 playbackRate 微調，大 drift 才 hard seek。

但 YouTube iframe 對 rate control 的可用性與 UX 需要另外驗證。

#### Explicit uncertainty

timeline segment 可加入 timing confidence / uncertainty，讓 UI 或 sync policy 依證據強度調整。

目前 HoloDocchi 選擇較簡單、可解釋的 hard mapping + bounded correction，歡迎其他開發者提出更穩定的方法。

---

## English

### Problem

True multi-perspective synchronization cannot compare source seconds directly.

If POV A starts at 19:00 and POV B starts at 19:07, then A at 10:00 and B at 10:00 represent different real-world times.

HoloDocchi therefore uses a session master timeline that maps every POV segment into one event coordinate system.

### Session model

Current schema:

    holoviewer-viewing-timeline-v1

A session contains a session ID, absolute start, master duration and one or more POVs. Each POV contains zero or more segments.

Each segment contains:

- segment_id;
- video_id;
- master_start_ms;
- master_end_ms;
- source_start_ms.

### Three time domains

#### Absolute time

Real-world epoch time.

#### Master time

Time relative to the session origin:

    absolute_time
    =
    session.absolute_start_ms
    +
    master_time

#### Source time

Playback time inside a specific video:

    source_time
    =
    segment.source_start_ms
    +
    (master_time - segment.master_start_ms)

This is the core mapping formula.

### Example

If the session begins at 19:00 and POV B starts at 19:07, B has:

    master_start = 7 min
    source_start = 0

At master time 12 min:

    source_time_B = 5 min

A may be at source 12:00 and B at source 05:00 while both represent the same absolute event time.

### Segments allow one POV to span multiple videos

A POV can contain multiple segments when a stream reconnects, splits into parts or changes source.

Segments may not overlap, must stay inside session bounds, and have unique IDs.

When master time enters a new segment, the viewer can replace the video source and seek to the segment's mapped source time.

Therefore:

    POV identity != video identity

### NO_COVERAGE is a first-class state

If a POV has no segment at the current master time, the resolver returns NO_COVERAGE.

It does not guess the nearest video, clamp to zero, keep playing the previous segment, or pretend content exists.

### READY resolution

When coverage exists, resolution returns POV ID, segment ID, video ID, master time, source time and absolute time.

The viewer does not need to reimplement segment math.

### Master clock owner

Runtime selects a clock POV whose observable media time can anchor the master clock.

Current initialization uses the first POV in the session.

When that player is READY and in PLAYING, PAUSED or BUFFERING, getCurrentTime() is mapped back into master time.

### Reverse mapping: Source to Master

Given POV ID, video ID and source time:

    master_time
    =
    segment.master_start
    +
    (source_time - segment.source_start)

If the same video appears in multiple segments, candidates are ranked by proximity to the current master time to reduce ambiguity.

### Clock fallback

If no reliable mapped media time is available but the session is considered running, wall-clock elapsed time advances the master clock.

Policy:

    mapped media clock preferred
    else running wall-clock progression
    else hold master time

This provides short-term continuity without claiming wall clock is the media authority.

### Drift detection

The system compares a newly mapped master candidate with the expected value derived from the previous sample.

If the difference exceeds:

    2500 ms

resynchronization is marked pending.

This is an implementation threshold, not a guarantee that synchronization error is always below 2.5 seconds.

### Resynchronization

For non-clock POVs, target source time is recalculated.

A seek occurs only when source drift exceeds:

    1.2 seconds

This avoids repeated seeks for small player jitter.

### Reconcile cadence

Timeline reconciliation currently runs every:

    500 ms

while the document is visible.

Most ticks only sample the clock and resolve coverage; they do not automatically seek every 500 ms.

### Gap handling

When a POV enters NO_COVERAGE:

- record the gap;
- pause it if currently playing;
- do not invent a source position.

When it later returns to READY:

- seek to the newly mapped source time;
- resume if the session has run intent.

A gap is therefore a valid timeline state, not an error.

### Segment replacement and reconnects

When the resolved video ID differs from the currently mounted source, the viewer:

1. preserves relevant playing/mute intent;
2. destroys the old player;
3. updates video identity;
4. mounts a new player;
5. seeks to the mapped source time;
6. restores appropriate playback/audio state.

This allows one logical POV to span multiple source videos.

### Coverage also controls visibility

In VOD collaboration timeline mode, only READY POVs are visible.

If the current primary POV enters a gap, the viewer can move primary/audio ownership to another covered POV.

Timeline state therefore controls both temporal alignment and which perspectives exist at a given event time.

### Play/pause versus timeline synchronization

Linked transport and timeline synchronization have different responsibilities:

- linked transport propagates PLAYING / PAUSED;
- timeline synchronization decides which video, which source second and whether coverage exists.

They can coexist, but they are not the same mechanism.

### Why share links do not currently restore master time

Master-time share restoration is intentionally parked.

Browser autoplay and user-gesture policy can create:

    URL master time = X
    actual YouTube clock != X

Trusting the URL as clock authority could separate internal timeline state from real player state.

The runtime therefore initializes from session state rather than restoring serialized master time from the share URL.

### Schema validation

Timeline input is fail-closed for:

- schema version;
- session ID;
- nonnegative absolute start;
- positive master duration;
- unique POV IDs;
- unique segment IDs;
- valid video IDs;
- valid master ranges;
- nonnegative source starts;
- non-overlapping segments;
- segments inside session bounds.

Invalid timelines do not enter synchronization runtime.

### Failed / risky approaches

#### F-022 — Equal source seconds treated as equal event time
Status: explicitly avoided.

Correction: separate master, absolute and source time.

#### F-023 — Continuing the previous segment through a timeline gap
Status: explicitly avoided.

Correction: NO_COVERAGE pauses that POV until valid coverage resumes.

#### F-024 — Seeking on every tiny error
Status: explicitly avoided.

Correction: bounded drift thresholds.

#### F-025 — Treating URL-restored master time as actual player clock
Status: parked after identifying browser-policy risk.

Autoplay/user-gesture behavior can make URL state diverge from the actual media clock, so master-time serialization/restoration is currently disabled.

### Trade-offs

- using the first POV as clock owner is simple but not necessarily always most stable;
- 500 ms reconciliation has CPU cost;
- wall-clock fallback is continuity assistance, not a media authority;
- seek thresholds balance jitter against visible drift;
- YouTube clock precision and buffering behavior are externally controlled;
- mapping quality depends on upstream start/end evidence.

### Alternatives

Possible improvements include dynamic clock-owner election, robust median clocks across multiple POVs, gradual playback-rate correction for small drift, and explicit timing uncertainty/confidence in segments.

The current design favors explainable hard mapping with bounded correction rather than claiming optimal synchronization.

[回目錄 / Index](README.md)
