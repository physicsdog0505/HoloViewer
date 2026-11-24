# 03 — 直播資訊系統 / Live stream discovery

## 繁體中文

### 問題

「今天有哪些直播？」看似只是列一張清單，但實際上有幾個不同狀態：

- 尚未開始；
- 等待中；
- 正在直播；
- 已結束；
- 原本是 live，但資料已 stale；
- 有影片但缺乏足夠新證據；
- 已結束，但不是今天結束。

如果把所有不確定狀態都硬猜成 live / upcoming / ended，首頁就會顯示錯誤資訊。

因此前端採取保守分類。

### 已實作的前端 lifecycle model

公開前端的 `homeLifecycleBucket()` 將 lifecycle 映射成四個 reader buckets：

```text
live
upcoming
unknown
ended
```

目前可從原始碼確認：

| Input | Frontend bucket |
|---|---|
| lifecycle_state = live, stale != true | live |
| lifecycle_state = live, stale = true | unknown |
| lifecycle_state = upcoming | upcoming |
| lifecycle_state = waiting | upcoming |
| lifecycle_state = ended | ended |
| lifecycle_state = unknown | unknown |
| 其他未認識狀態 | unknown |

最重要的是：

```text
live + stale => unknown
```

系統不因為上一筆資料曾是 live，就永遠把它顯示為 live。

### 「今天已結束」的範圍

首頁還另外處理 ended stream 的日界線。

使用的是 **Asia/Taipei** 的今天。

判定優先使用：

```text
actual_end / end_at
```

如果沒有可信 end timestamp，才 fallback 使用：

```text
actual_start / start_at / scheduled_start
```

若 ended 影片不屬於今天的時間範圍，首頁的 today scope 會將它降為 unknown，而不是把舊直播永久堆在「已結束」。

這是 reader-side scope rule，不代表 upstream lifecycle authority 的完整判定方法。

### 時間排序

live、upcoming、unknown 主要依：

```text
actual_start
→ scheduled_start
→ start_at
→ video_id stable tie-break
```

排序。

ended 則優先使用 verified end timestamp，並以較新的結束時間排前面；沒有 end timestamp 時才 fallback 到 start time。

這樣的設計避免完全依 API 回傳順序顯示。

### Reader cache

首頁會把當日 catalog 暫存在 browser `sessionStorage`。

cache key 同時包含 Taipei date。

讀取邏輯是：

1. 如果同一 session 已有今天 cache，先 render；
2. 仍會重新向 public API request；
3. request 成功後更新畫面與 cache；
4. request 失敗但已有 cache 時，可保留已顯示資料。

因此 cache 是 UI responsiveness / fallback，不是 live truth authority。

### In-flight request deduplication

前端用一個共享 Promise 避免同時多處請求 today catalog 時重複打相同 API。

概念上：

```text
if request already in flight:
    reuse same promise
else:
    create request
```

這是一個 client-side dedupe，不是資料庫 idempotency。

### Concurrent viewers

如果 row 同時滿足：

- bucket 為 live；
- `concurrent_viewers` 是正整數；

首頁會顯示正在觀看人數。

前端不會因為 concurrent_viewers 存在就反推 lifecycle = live。

也就是 lifecycle 與 viewer count 是兩個不同訊號。

### Collaboration enrichment

today catalog 載入後，前端會另外讀取 live collaboration data。

這代表：

```text
base stream catalog
+
optional collab enrichment
```

而不是要求主 catalog 內嵌全部 collab 資料。

如果 collab request 失敗，基本直播列表仍可顯示。

---

### 目前尚未完成公開鑑識的部分

這一章目前只描述 **公開 reader 的 lifecycle interpretation**。

尚未在本 handbook 完成核對：

- upstream 如何發現新直播；
- polling / notification / WebSub 的實際權威關係；
- lifecycle transition 的 server-side state machine；
- stale threshold 的實際時間參數；
- concurrent viewer 的採樣頻率；
- upstream 如何處理 YouTube metadata 延遲；
- 直播刪除、轉私人或重開台的 source-side 規則。

在完成對應 authority code review 前，不應把 reader rule 說成完整 collector 演算法。

---

### Failed / risky approaches

#### 把 stale live 繼續當 live
**狀態：目前 reader 明確避免**

如果最後一次看到影片時是 live，但資料已經 stale，繼續顯示 LIVE 會製造假即時資訊。

目前 reader 選擇：

```text
stale live → unknown
```

這是一個保守的 UX trade-off：可能短時間少報 live，但避免把舊狀態當成新證據。

#### 只靠 scheduled start 推測現在狀態
目前 reader 不會因為 scheduled time 已過就自行判定 live。

這很重要，因為直播可能：

- 延遲；
- 取消；
- 改期；
- 已結束；
- metadata 尚未更新。

scheduled timestamp 可以排序，但不是足夠的 live truth。

---

### Limitations

- reader 仍依賴 upstream lifecycle evidence；
- stale threshold 若設定不合理，unknown 可能過多或過少；
- browser cache 不是 durable cache；
- client clock / timezone 實作仍需要測試；
- concurrent viewer 是觀測值，不應視為精確且連續的真實函數；
- today boundary 目前以 Taipei day 為產品語意，其他時區使用者看到的是同一產品日界線。

### 可替代方案

其他實作可以考慮：

- explicit finite-state machine with evidence timestamps；
- event-sourcing 保存每次 lifecycle transition；
- server-sent events / WebSocket 推送；
- client 使用 monotonic freshness age；
- 將 `UNKNOWN` 拆成 stale / incomplete / conflicting evidence。

HoloDocchi 目前的四 bucket 模型比較簡單；如果更多狀態能提升使用者理解而不造成 UI 過度複雜，這是一個值得改進的方向。

---

## English

### Problem

“What is live today?” appears to be a simple list, but the underlying state can include:

- not started;
- waiting;
- live;
- ended;
- previously live but stale;
- a discovered video without sufficiently fresh evidence;
- ended, but not within today's product scope.

If every uncertain case is forced into live/upcoming/ended, the homepage will present false certainty.

The frontend therefore classifies conservatively.

### Implemented frontend lifecycle model

Public frontend `homeLifecycleBucket()` maps lifecycle input into four reader buckets:

```text
live
upcoming
unknown
ended
```

Source confirms:

| Input | Frontend bucket |
|---|---|
| lifecycle_state = live, stale != true | live |
| lifecycle_state = live, stale = true | unknown |
| lifecycle_state = upcoming | upcoming |
| lifecycle_state = waiting | upcoming |
| lifecycle_state = ended | ended |
| lifecycle_state = unknown | unknown |
| unrecognized state | unknown |

The important rule is:

```text
live + stale => unknown
```

A stream is not kept LIVE forever merely because the previous observation was live.

### Scope of “ended today”

The homepage additionally scopes ended streams using the **Asia/Taipei** product day.

It prefers:

```text
actual_end / end_at
```

When no credible end timestamp exists, it falls back to:

```text
actual_start / start_at / scheduled_start
```

An ended stream outside today's scope is downgraded to unknown for the today view rather than accumulating permanently in the ended section.

This is a reader-side scope rule, not the complete upstream lifecycle authority.

### Time ordering

Live, upcoming and unknown rows are primarily sorted by:

```text
actual_start
→ scheduled_start
→ start_at
→ video_id stable tie-break
```

Ended rows prefer a verified end timestamp and show more recent endings first; if no end timestamp exists they fall back to start time.

The UI therefore does not rely on API return order.

### Reader cache

The homepage stores the day's catalog in browser `sessionStorage`.

The cache is keyed by the Taipei date.

The behavior is:

1. if today's cache exists in the same session, render it first;
2. still request fresh data from the public API;
3. on success, update UI and cache;
4. on request failure, previously rendered cached data can remain available.

The cache improves responsiveness and resilience; it is not the live truth authority.

### In-flight request deduplication

The frontend uses a shared Promise so multiple consumers requesting today's catalog do not issue duplicate simultaneous requests.

Conceptually:

```text
if request already in flight:
    reuse same promise
else:
    create request
```

This is client-side request deduplication, not database idempotency.

### Concurrent viewers

When a row is:

- classified as live; and
- has a positive integer `concurrent_viewers`;

the homepage displays the viewer count.

The frontend does not infer lifecycle = live merely because a viewer-count value exists.

Lifecycle and viewer count are separate signals.

### Collaboration enrichment

After the base today catalog is loaded, the frontend separately requests live collaboration data.

The model is:

```text
base stream catalog
+
optional collab enrichment
```

rather than embedding every collaboration field into the base catalog.

If collaboration enrichment fails, the core stream list can still render.

---

### Parts not yet forensically documented

This chapter currently describes the **public reader's lifecycle interpretation**.

The handbook has not yet completed source review for:

- how new streams are discovered upstream;
- the authority relationship between polling, notifications or WebSub;
- the server-side lifecycle transition state machine;
- the actual stale-threshold parameter;
- concurrent-viewer sampling frequency;
- how upstream handles delayed YouTube metadata;
- source-side rules for deletion, privatization or stream restarts.

Until the authority code is reviewed, reader rules should not be described as the complete collector algorithm.

---

### Failed / risky approaches

#### Treating stale live state as live
**Status: explicitly avoided by the current reader**

If the last observation was live but the evidence is stale, continuing to display LIVE creates false real-time information.

The current reader chooses:

```text
stale live → unknown
```

This is a conservative UX trade-off: it may temporarily under-report live state, but avoids presenting old evidence as fresh evidence.

#### Inferring live state from scheduled start alone
The current reader does not decide that a video is live simply because its scheduled time has passed.

This matters because a stream may be:

- delayed;
- cancelled;
- rescheduled;
- already ended;
- waiting for metadata refresh.

Scheduled time is useful for ordering, but not sufficient as live truth.

---

### Limitations

- the reader still depends on upstream lifecycle evidence;
- a poor stale threshold can create too many or too few unknown states;
- browser cache is not durable;
- client clock/timezone behavior still requires testing;
- concurrent viewers are observations, not an exact continuous truth function;
- the product day currently uses Taipei time, so users in other time zones still see the same product-day boundary.

### Alternative approaches

Other implementations could consider:

- an explicit finite-state machine carrying evidence timestamps;
- event sourcing for every lifecycle transition;
- server-sent events or WebSockets;
- monotonic freshness age on the client;
- splitting `UNKNOWN` into stale / incomplete / conflicting evidence.

HoloDocchi's current four-bucket model is intentionally simple. If richer states improve understanding without overwhelming the UI, that is a valid direction for improvement.

[回目錄 / Index](README.md)
