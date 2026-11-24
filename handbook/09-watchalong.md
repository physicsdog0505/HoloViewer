# 09 — 同時視聽系統 / Watchalong synchronization

## 繁體中文

### 問題

Watchalong 與一般多人連動不同。

多人連動是多個 POV 對應同一現場事件；Watchalong 則是：

    Hololive host video
    +
    external/source video
    +
    alignment mapping

Host 與 source 的影片時間通常不同，而且 source 可能：

- 比 host 晚開始；
- 中間有廣告／等待；
- 分成多支影片；
- 某一段 source 已結束，但 host 還在聊天；
- 下一個 source segment 尚未開始。

因此 Watchalong 不能只用：

    source_time = host_time

---

### 1. Host timeline 是 authority

Static Watchalong event 明確要求：

    subtitle_timeline = "host"

也就是：

- host 是主要播放時間軸；
- PTT 跟 host；
- HoloDocchi 翻譯字幕跟 host；
- source 只是被映射到 host timeline。

這避免主片源切換時字幕 clock 跟著跳掉。

---

### 2. Segment model

每個 source segment 至少包含：

- segment_id；
- source_video_id；
- host_start_ms；
- source_start_ms。

Segments 必須依 host_start_ms 遞增，且 source order 必須與 event source_video_ids 一致。

對某 segment：

    base_offset
    =
    source_start
    -
    host_start

因此：

    expected_source_time
    =
    host_time
    +
    base_offset
    +
    user_offset

這是 Watchalong 的核心換算。

---

### 3. user offset 與 base offset 分離

系統分開保存：

- segmentBaseOffsetSeconds；
- userOffsetSeconds。

#### Base offset

來自已驗證 segment alignment。

#### User offset

使用者手動微調，用 0.1 秒粒度保存。

因此人工微調不會破壞原始 approved alignment。

概念上：

    effective offset
    =
    approved segment offset
    +
    personal correction

---

### 4. 多集／多片源切換

一個 Watchalong event 可以包含多個 source video。

當 host time 進入下一個 segment：

1. 找到新的 active segment；
2. 更新 base offset；
3. 若 source_video_id 改變：
   - load / cue 新 source video；
   - 從映射後的 source time 開始；
4. subtitle timeline 不變，仍然跟 host。

因此：

    source video changes
    but host clock remains continuous

---

### 5. Source gap 是正式狀態

如果目前 source segment 已播完，但下一個 segment 的 host_start 還沒到，代表 host 正在經歷：

- 中場聊天；
- 換片等待；
- source pause；
- 下一集尚未開始。

這段不應把 source 拉回 0 秒後繼續播放，也不應跳到下一集太早。

系统會進入 standby：

    source gap active

直到 host time 到達下一段 host_start。

這和 Chapter 07 的 NO_COVERAGE 概念相似：沒有 source coverage 是有效狀態，不是 error。

---

### 6. linked playback

Host state change 會驅動 source：

- host PLAYING → source play；
- host PAUSED → source pause。

但只有在：

- linked playback 開啟；
- timeline 已 aligned；
- 不在 source gap；
- expected source time >= 0；

時才執行。

如果 source 還沒正式開始：

    expected source time < 0

則 source 保持 standby，host 可以先播放。

---

### 7. Runtime drift correction

Watchalong sync loop 目前每：

    500 ms

檢查一次。

對目前 host time 計算 expected source time。

若：

    abs(actual_source - expected_source) > 2.5 seconds

才 hard seek source。

這避免每個小 jitter 都 seek。

因此這是：

    host-driven source correction

而不是雙向互相拉扯。

---

### 8. Segment 切換與 source ended

如果 source player 進入 ENDED，而下一個 segment 尚未到 host start，系統會 latch source gap。

這比看到 ENDED 就立刻播放下一支 source 更安全。

只有 host clock 到達下一 segment boundary，才解除 gap 並切換。

---

### 9. Static event validation

Watchalong static reader 不直接信任 event JSON。

先驗證 manifest：

- schema；
- event_id；
- master_video_id；
- path；
- event SHA-256；
- cue_count；
- source_count；
- transcript hash；
- translation artifact identity。

再 fetch event，對 bytes 計算 SHA-256，比對 manifest。

Event 本身再驗證：

- event/master identity 一致；
- subtitle_timeline 必須是 host；
- source count 一致；
- source video IDs 唯一且合法；
- segment count 一致；
- segment order 一致；
- host/source starts 合法；
- transcript hash 一致；
- translation transcript hash 一致；
- translation artifact ID 一致；
- transcript cue count；
- translated cue count；
- subtitle cue count；
- cue IDs 唯一；
- cue timing 合法且排序；
- COMPLETE translation 不允許空翻譯。

任一不一致就 fail closed，不 mount static event。

---

### 10. Translation artifact 與 Watchalong event 的關係

Watchalong event 不只引用「某份字幕文字」。

它同時綁定：

    transcript_hash
    +
    translation_artifact_id
    +
    cue_count

這避免：

- 原文 transcript 更新了但翻譯沒更新；
- translation 來自另一版 transcript；
- cue 數量不一致；
- event manifest 指向錯誤 artifact。

因此字幕 provenance 是 event integrity 的一部分。

---

### 11. Subtitle clock

Static Watchalong 會把 subtitle timeline 設為：

    host

字幕 cue 使用：

- start_ms；
- end_ms；
- cue_id；
- original；
- translation；
- optional speaker metadata。

Reader 用 host current time 查找 cue。

因此 source video 切換不會改變字幕 clock。

---

### 12. PTT clock

PTT 也跟 host。

目前對 host video window：

    absolute_time
    =
    host actual_start
    +
    host playback seconds

再顯示 occurred_at <= absolute_time 的 PTT pushes。

所以：

    source offset adjustment
    does not change PTT time

這很重要，因為 PTT 是觀眾對 host 直播的討論，而不是對外部 source 的原始發佈時間。

---

### 13. YouTube Chat clock

如果 host 已 ended，YouTube Chat replay 也依 host player current time 同步。

因此 Watchalong 中三個內容層的 clock authority是：

    Host video
      ├─ PTT
      ├─ YouTube Chat replay
      └─ HoloDocchi subtitles

Source video 是被 host clock 驅動的 secondary timeline。

---

### 14. Local A/B subtitle comparison

Watchalong 允許載入本機字幕 A / B 做比較。

安全與一致性要求：

- 檔案只在目前 page 使用；
- 不上傳；
- A/B 必須對應相同 video ID；
- A/B 必須使用相同 timeline；
- 若 static event 使用 host timeline，本機字幕比較也必須與所選 target timeline 一致。

這避免拿 host 字幕和 source 字幕直接做錯位比較。

---

### 15. Progress resume

Watchalong 可以把 host playback progress 存在 browser localStorage。

儲存的是：

    host seconds

恢復時：

1. seek host；
2. 依 active segment 重建 base offset；
3. seek / cue source；
4. 驗證 host clock 是否真的到達 target。

驗證誤差目前使用約：

    ±2.5 seconds

並做 bounded delayed checks。

---

### 16. 為什麼 URL time restore 仍停用

和 Chapter 07 相同，URL 分享時間恢復被 parked。

原因是 browser autoplay / user gesture policy 可能讓：

    URL time
    !=
    actual YouTube player clock

因此 local progress resume 可以做 readback verification，而 URL 不被當成 clock authority。

---

### 17. Legacy manual alignment

在非 static event 模式，可以由使用者手動建立 offset。

例如使用者按「開始同步」時，如果尚未 aligned：

    user_offset
    =
    current_source
    -
    current_host
    -
    segment_base_offset

之後再由 host-driven loop 維持。

這個模式較方便，但 confidence 低於已驗證 static event alignment。

---

### 已確認失敗／風險

#### F-030 — source_time = host_time
Status: explicitly avoided.

Host 與 source 幾乎不會天然同秒。

#### F-031 — source ended 就立刻跳下一集
Status: explicitly avoided.

Host 中間可能有無 source coverage 的 gap。

#### F-032 — 字幕跟 source timeline
Status: rejected for static Watchalong events.

Static event contract 固定 subtitle_timeline = host，避免 source switch 使字幕 clock 斷裂。

#### F-033 — 不驗證 transcript / translation provenance
Status: explicitly avoided.

Watchalong event 以 transcript hash、translation artifact ID、cue count 綁定字幕版本。

#### F-034 — 每 500 ms 都 seek
Status: explicitly avoided.

500 ms 是 reconcile cadence，不是 seek cadence；只有 drift > 2.5 s 才 correction。

#### F-035 — URL checkpoint 當 media truth
Status: parked.

Browser policy 可能使 URL state 與實際 player clock 不一致。

---

### Trade-offs

- Host-driven model 假設 host 是使用者主要觀看 authority；
- 2.5 秒 hard-seek threshold 是 UX trade-off，不是唯一正解；
- 手動 user offset 可能修正個別使用者播放器差異，也可能被調錯；
- segment alignment 的品質依賴 upstream approved sync evidence；
- source provider 若禁止 embed，Watchalong 無法自行解決；
- 靜態 event verification 增加 publication complexity，但大幅提升 reproducibility。

---

### 可改進方案

#### Confidence per segment

每個 segment 可加入：

- alignment source；
- reviewer；
- uncertainty；
- confidence。

#### Soft drift correction

小誤差可研究 playback rate 微調，大誤差才 hard seek。

#### Automatic alignment proposals

可以用音訊 fingerprint、字幕對齊或 semantic events 產生 alignment candidate，但仍應進 review，而不是直接升級成 approved alignment。

#### External source abstraction

目前 source 以 YouTube 為主。更通用的模型可以把 source player 抽象成：

    getCurrentTime
    seek
    play
    pause
    ended

使合法且可嵌入的其他 provider 也能使用同一 timeline model。

HoloDocchi 目前的核心原則是：

> Host timeline 是唯一主 clock；source alignment 可以被修正，但不能反過來偷偷改寫 host truth。

---

## English

### Problem

Watchalong synchronization differs from ordinary multi-POV collaboration.

It combines:

    Hololive host video
    +
    external/source video
    +
    alignment mapping

The source can start later, contain gaps, span multiple videos, end before the host discussion ends, or wait for the next segment.

Therefore source_time cannot simply equal host_time.

### 1. Host timeline is authoritative

Static Watchalong events require:

    subtitle_timeline = "host"

The host drives PTT, YouTube Chat replay and HoloDocchi subtitles. The source is mapped onto the host clock.

### 2. Segment model

Each source segment contains a segment ID, source video ID, host start and source start.

For one segment:

    base_offset
    =
    source_start
    -
    host_start

and:

    expected_source_time
    =
    host_time
    +
    base_offset
    +
    user_offset

### 3. Base offset and user offset remain separate

The approved segment offset is preserved separately from the user's personal 0.1-second correction.

This prevents manual tuning from overwriting the reviewed alignment.

### 4. Multi-video source switching

When host time enters a new segment, the viewer updates the base offset and, when necessary, loads/cues the next source video at the mapped source time.

The host clock remains continuous across source changes.

### 5. Source gaps are first-class states

If the current source segment ends before the next host_start, the source enters standby.

It does not rewind and continue, nor jump prematurely into the next source video.

### 6. Linked playback

Host play/pause drives the source only when linked playback is enabled, alignment is active, no source gap is active, and expected source time is nonnegative.

The host can continue before the source begins.

### 7. Runtime drift correction

The sync loop runs every 500 ms.

The source is hard-seeked only when absolute drift from expected source time exceeds 2.5 seconds.

The model is host-driven rather than bidirectional.

### 8. Source ended behavior

A source ENDED state can latch an inter-segment gap when the host has not yet reached the next segment boundary.

### 9. Static event validation

The reader verifies manifest schema, identities, path, SHA-256, source/cue counts, transcript hash and translation artifact identity before accepting the event.

The event then validates host/source identities, unique source IDs, segment ordering, artifact provenance, cue counts, cue timing, unique cue IDs and nonempty COMPLETE translations.

Any mismatch fails closed.

### 10. Translation provenance is part of event integrity

Watchalong binds subtitles using transcript hash, translation artifact ID and cue count rather than only storing translated text.

This prevents mismatched transcript/translation versions.

### 11. Subtitle clock

Static Watchalong subtitles use the host timeline, so source-video switching does not change subtitle time.

### 12. PTT clock

PTT uses host actual start plus host playback seconds to derive absolute discussion time.

User source-offset adjustments do not change PTT timing.

### 13. YouTube Chat clock

For ended host videos, chat replay also follows host current time.

Thus the host clock drives PTT, chat replay and subtitles; the external source is secondary.

### 14. Local A/B subtitle comparison

Local subtitle files remain browser-local and are not uploaded.

A/B comparison requires the same video identity and timeline, preventing invalid host/source cross-comparison.

### 15. Progress resume

Local progress stores host seconds.

Resume seeks the host, reconstructs the active segment and source mapping, and verifies that the host clock actually reached the requested position within a bounded tolerance.

### 16. URL time restore remains parked

URL-restored time is not trusted as media truth because browser autoplay/user-gesture restrictions can prevent the player from reaching that position.

### 17. Legacy manual alignment

Without a reviewed static event, the user can establish a manual offset from current host/source positions.

This is convenient but lower-confidence than approved static alignment.

### Failed / risky approaches

- F-030 — source_time = host_time: explicitly avoided.
- F-031 — immediately advancing when source ends: explicitly avoided.
- F-032 — source-timeline subtitles for static events: rejected; host timeline is required.
- F-033 — ignoring transcript/translation provenance: explicitly avoided.
- F-034 — seeking every 500 ms: explicitly avoided; 500 ms is reconcile cadence only.
- F-035 — URL checkpoint treated as media truth: parked.

### Trade-offs and alternatives

The host-driven model assumes the host is the user's primary viewing authority. Hard-seek thresholds, user offsets and approved segment mappings all carry trade-offs.

Possible improvements include per-segment confidence, soft playback-rate correction, automatically proposed but human-reviewed alignments, and a provider-neutral source-player abstraction.

The core rule is:

> The host timeline is the authoritative clock; source alignment may be corrected, but must not silently redefine host truth.

[回目錄 / Index](README.md)
