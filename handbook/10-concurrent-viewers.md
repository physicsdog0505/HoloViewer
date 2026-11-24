# 10 — 同接數據 / Concurrent viewer metrics

## 繁體中文

### 狀態先說清楚

目前 HoloDocchi **有顯示 live concurrent viewers**，但**沒有啟用歷史同接 time-series 採樣、趨勢、peak 或長期分析 pipeline**。

因此必須區分：

    current live concurrent viewer display
    !=
    historical concurrent-viewer sampling system

前者目前存在；後者目前沒有正式啟用。

---

### 1. 目前 live concurrent viewers 的資料來源

目前資料來自既有 YouTube lifecycle refresh 使用的：

    videos.list(part=snippet,liveStreamingDetails)

而不是另外增加一條只為同接存在的 polling loop。

從同一批 response 讀取：

    liveStreamingDetails.concurrentViewers

因此導入這個欄位時的設計要求是：

    NEW_YOUTUBE_API_CALLS = 0
    NEW_QUOTA_COST = 0
    REFRESH_CADENCE_CHANGED = NO

也就是同接只是既有 live metadata refresh 的一個 additional projection。

---

### 2. 語意是 ephemeral，不是歷史統計

目前 concurrent_viewers 的 contract：

- 正整數才是有效值；
- missing / hidden / invalid / non-positive → null；
- upcoming / ended → null；
- stale live → null；
- 不用它判定 lifecycle；
- 不把它當 VOD viewCount；
- 不寫入 historical VOD statistics。

因此：

    null != 0

以及：

    concurrent_viewers != lifecycle authority

都是明確設計。

---

### 3. 目前 refresh cadence

Production lifecycle refresh 保留既有：

    every 5 minutes

也就是 server-side lifecycle refresh 的既有 cadence。

這個 5 分鐘不是為同接特別增加的 polling。

同接數值只是搭便車使用這次 metadata refresh 的結果。

因此 frontend 顯示的是：

> 最近一次 lifecycle refresh 時 YouTube 提供的 concurrent viewer observation。

不是秒級即時 telemetry。

---

### 4. 為什麼沒有開歷史採樣

最初設計就把以下項目列為 later extension：

- per-stream trend samples；
- peak concurrent viewers；
- large-collab comparison；
- historical analysis。

而 historical analysis 明確要求：

> only after storage / retention requirements are explicitly designed.

原因不是單一因素，而是至少包含：

1. 需要決定 sampling cadence；
2. 每支 live stream 每隔 N 分鐘持久化會產生大量 rows；
3. retention policy 尚未定義；
4. peak 對缺樣本、hidden count、provider delay 很敏感；
5. D1 write / read amplification 必須先量測；
6. 沒必要為顯示「現在多少人看」建立第二條高成本 polling system。

---

### 5. D1 amplification 曾經真的發生

這不是純理論風險。

當 concurrent_viewers 首次加入既有 Today canonical update 時，Production 的 5 分鐘 refresh 曾出現：

    D1_ERROR: too many SQL variables

原因是 unchanged-row update 使用 CASE expression。

45 rows 會展開成：

    1 checked_at
    + 2 × 45 CASE binds
    + 45 WHERE-IN binds
    = 136 SQL variables

這超過該 statement 可接受的 variable limit。

後來修正成每批最多 30 IDs：

    1 + 2 × 30 + 30 = 91 binds

50-row worst case 會拆成：

    30 + 20
    → 91 + 61 binds

這個事故很重要，因為它說明：

> 就算只是把一個 ephemeral live field 寫進既有 refresh path，批次 SQL shape 都可能造成放大問題。

所以如果要再加：

    every N minutes
    × every live stream
    × historical sample row

就不能只看 YouTube quota，而必須同時估 D1 write volume、index cost、retention、query pattern 與 rollup strategy。

---

### 6. 為什麼這不等於「D1 不適合存同接」

目前不能下這個結論。

已確認的是：

- 某個 CASE update shape 曾超過 SQL variable limit；
- chunking 可以修正該特定 regression；
- current ephemeral field 可以在既有 5-minute path 中運作；
- historical time-series 尚未設計與驗收。

因此正確說法是：

> D1 寫入放大與 statement batching 曾是實際風險，這強化了「先不要直接開高頻歷史採樣」的決策；但尚未有 benchmark 證明 D1 永遠不適合這個 workload。

---

### 7. 為什麼不用 concurrent_viewers 當熱門排行

current count 有很多不可控因素：

- YouTube 可能隱藏數值；
- sample cadence 是 5 分鐘級；
- 不同直播開播長度不同；
- 短時間 spike 可能被漏掉；
- 時區／活動規模差異很大；
- missing value 不是 zero；
- 一個 snapshot 不是 trend。

所以目前首頁 highlight 不把同接當 ranking authority。

---

### 8. 如果未來要做歷史同接，至少要先定義

#### Sampling

    sample interval = ?

不能只因為 lifecycle 每 5 分鐘 refresh，就自動決定每 5 分鐘永久保存一次。

#### Storage model

可以考慮：

    raw samples
    rollups
    peak-only
    change-only
    bucketed aggregates

#### Retention

例如 raw sample 保留多久、是否只保存 peak / percentile / hourly rollup。

#### Missing semantics

要區分：

    hidden
    unavailable
    stale
    not-live
    fetch-failed

不能全部寫成 0。

#### Peak definition

Peak 至少要說清楚：

    max(observed samples)

而不是宣稱「真實 peak」。

若 sampling 是 5 分鐘：

    observed peak
    !=
    true instantaneous peak

#### Write amplification budget

需要實測：

- rows written / hour；
- SQL statements / hour；
- index writes；
- compaction / retention writes；
- read cost of trend queries；
- concurrent live-stream worst case。

---

### 已確認失敗／風險

#### F-036 — 為同接增加第二條 polling loop
Status: explicitly avoided.

現行 live count 重用既有 videos.list refresh。

#### F-037 — D1 large CASE update 不切批
Status: Failed / corrected.

45-row update 曾產生 136 bind variables 並使 lifecycle refresh 失敗。

修正：最多 30 IDs / statement。

#### F-038 — concurrent viewers 當 lifecycle authority
Status: explicitly avoided.

缺值／hidden 不代表不是 live。

#### F-039 — null 當 0
Status: explicitly avoided.

Unavailable viewer count 是 unknown，不是零人。

#### F-040 — current snapshot 直接當 historical metric
Status: intentionally not implemented.

歷史 sampling / peak / trend 尚未啟用。

---

### 目前結論

HoloDocchi 現在做的是：

    existing lifecycle refresh
        ↓
    read concurrentViewers
        ↓
    ephemeral Today projection
        ↓
    live card display

目前**沒有**：

    persistent sample series
    historical peak
    trend chart
    ranking by viewer count

這是一個刻意受限的 MVP，而不是尚未完成但偷偷在收資料。

---

## English

### Current status

HoloDocchi currently displays live concurrent viewer counts, but it does **not** run a production historical concurrent-viewer time-series, trend, peak, or long-term analytics pipeline.

Therefore:

    current live concurrent viewer display
    !=
    historical concurrent-viewer sampling system

### 1. Current source

The count is extracted from the existing YouTube lifecycle refresh:

    videos.list(part=snippet,liveStreamingDetails)

using:

    liveStreamingDetails.concurrentViewers

No second polling loop was added.

The implementation boundary was:

    NEW_YOUTUBE_API_CALLS = 0
    NEW_QUOTA_COST = 0
    REFRESH_CADENCE_CHANGED = NO

### 2. Ephemeral semantics

Current contract:

- positive integer only;
- missing / hidden / invalid / non-positive → null;
- upcoming / ended → null;
- stale live → null;
- not lifecycle authority;
- not historical VOD viewCount;
- not persisted as historical VOD statistics.

Thus:

    null != 0

and concurrent viewers are informational live metadata only.

### 3. Refresh cadence

The existing production lifecycle refresh remains approximately every five minutes.

The concurrent count reuses that refresh rather than creating its own polling cadence.

It is therefore an observation from the most recent lifecycle refresh, not second-level telemetry.

### 4. Why historical sampling is not enabled

The original product design explicitly deferred:

- per-stream trend samples;
- peak concurrent viewers;
- large-collab comparisons;
- historical analytics.

Historical analysis was to begin only after storage and retention requirements were explicitly designed.

Reasons include sampling cadence, row growth, retention, missing-value semantics, provider delay and D1 read/write amplification.

### 5. D1 amplification occurred in practice

When concurrent_viewers was first added to the existing Today canonical update path, the five-minute production refresh hit:

    D1_ERROR: too many SQL variables

An unchanged-row CASE update for 45 rows expanded to:

    1 checked_at
    + 2 × 45 CASE binds
    + 45 WHERE-IN binds
    = 136 SQL variables

The correction chunked updates to at most 30 IDs:

    1 + 2 × 30 + 30 = 91 binds

A 50-row worst case becomes 30 + 20 with 91 + 61 binds.

This demonstrated that even one ephemeral field can materially change the write shape.

A persistent N-minute × N-live-stream sample series therefore requires explicit write-volume and retention design rather than being enabled casually.

### 6. This does not prove D1 is inherently unsuitable

The evidence supports a narrower conclusion:

- one SQL update shape exceeded a variable limit;
- chunking corrected that regression;
- current ephemeral data works on the existing cadence;
- historical time-series storage has not been designed or accepted.

D1 write amplification is therefore a real design constraint, not proof that D1 can never support the workload.

### 7. Why current viewer count is not a popularity authority

Counts can be hidden, delayed or missing; sampling is coarse; streams have different durations; spikes can fall between observations; and null is not zero.

The homepage highlight system therefore does not use viewer count as ranking authority.

### 8. Requirements before enabling historical metrics

A future design must explicitly define:

- sampling interval;
- raw versus rollup storage;
- retention;
- missing-value states;
- observed-peak semantics;
- write/read amplification budgets;
- worst-case concurrent live-stream volume.

A five-minute sampled maximum must be labeled an observed peak, not the true instantaneous peak.

### Failed / risky approaches

- F-036 — adding a second polling loop for concurrent viewers: explicitly avoided.
- F-037 — unchunked large D1 CASE update: Failed / corrected.
- F-038 — concurrent viewers as lifecycle authority: explicitly avoided.
- F-039 — null treated as zero: explicitly avoided.
- F-040 — current snapshots treated as historical metrics: intentionally not implemented.

### Current conclusion

HoloDocchi currently implements:

    existing lifecycle refresh
        ↓
    concurrentViewers extraction
        ↓
    ephemeral Today projection
        ↓
    live-card display

It does not currently implement persistent samples, historical peaks, trend charts or viewer-count ranking.

[回目錄 / Index](README.md)
