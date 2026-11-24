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

### Upstream discovery：今日直播怎麼被發現

前端看到的 `/today` catalog 不是直接從 browser 呼叫 YouTube 產生。

目前 lifecycle 設計將「完整發現」與「低延遲事件證據」分開：

```text
Uploads playlist head ─┐
WebSub / Today evidence ├─→ candidate video_id union
Stream Catalog ─────────┘
                         ↓
                 bounded videos.list
                         ↓
              canonical history store
                         ↓
             rebuildable static history
```

各來源責任不同。

#### Uploads playlist：完整發現

Uploads playlist 是 completeness discovery。

steady state 對每個 active tracked channel 先讀 playlist head：

- 正常情況只需要 page 1；
- 如果上一個成功 head 已經出現在 page 1，就停止；
- 如果沒有看到 previous head，才繼續沿 nextPageToken 往後追；
- catch-up 有 fail-closed page bound，避免無限制掃描。

因此 uploads playlist 的角色是：

> 即使低延遲通知漏掉，也要有一條可追溯、可補洞的 discovery path。

#### WebSub / Today evidence：低延遲 seen-before / lifecycle evidence

WebSub 的角色不是取代完整歷史 discovery，而是讓新影片／狀態改變可以更快進入 Today evidence。

工程紀錄中的 WebSub 設計包含：

- 只接受 approved roster 的 channel；
- subscription lease 必須有效；
- callback delivery 必須通過簽章驗證；
- duplicate callback 必須 idempotent；
- stale duplicate notification 不得把已 ended 的直播重新復活；
- WebSub coverage 不完整時，不應把 primary mode 視為 ready；
- deleted-entry 類事件需要 bounded reconciliation，而不是直接猜測資料已消失。

這些是「如何安全使用 WebSub」的設計原則。

**重要證據狀態：** 過去驗收紀錄曾達到舊 85-channel roster 的 85/85 active lease coverage；目前 lifecycle roster 已演進為 86 tracked channels，其中 1 個 retired、85 個 active。此 handbook 尚未重新讀取當下 live lease state，因此不宣稱現在仍是 85/85。

#### Stream Catalog：seen-before 與 lifecycle 補充證據

既有 Stream Catalog 會被 lifecycle reconcile 讀取，提供已看過的 video identity / lifecycle evidence。

它不是長期歷史資料的第二份 authority，而是 candidate union 的一部分。

#### videos.list：metadata / current-state verification

candidate video IDs 不直接被當成完整影片資料。

fresh 或 retry-eligible candidate 會進 bounded `videos.list` verification：

- 一次最多 50 個 video IDs；
- fresh priority lane 優先；
- historical retry lane 有 bounded size 與 backoff；
- provider 暫時回傳空值不能抹掉已知較強 metadata；
- provider omission 不代表 canonical row 應被刪除。

這避免把「發現某個 video ID」和「確認它目前 metadata/state」混成同一件事。

---

### 追蹤哪些頻道

目前 versioned lifecycle roster 有：

```text
86 tracked channel identities
- 1 retired
= 85 active for steady-state discovery
```

roster 的完整 channel IDs 以 versioned source data 為準，而不是散落在 frontend title heuristic 中。

它由兩層組成：

- 既有 historical baseline：66 channels；
- activation-only additions：20 channels。

activation-only channel 不代表獲得完整歷史 backfill 權限；它們只從各自核准的 activation boundary 之後開始 lifecycle ingestion。

這個設計避免「今天新增一個追蹤頻道」就無意間觸發大量舊歷史重抓。

對外文件應以 **versioned roster + activation policy** 描述，而不是把每個 channel 寫死在演算法裡。

---

### 更新頻率：Today 與 History 是兩個 cadence

#### Today

Today 的低延遲性主要依賴事件證據（如 WebSub）與既有 Today / Stream Catalog 更新。

因此它不是「每 6 小時才更新首頁」。

WebSub 的價值就是讓新 upload / livestream event 不必等待完整 historical reconcile 才被看到。

#### Historical lifecycle reconcile

目前歷史 lifecycle scheduler 的預設週期是：

```text
6 hours
```

也就是：

```text
21600 seconds
```

這個週期負責：

1. reconcile uploads heads；
2. 合併 Stream Catalog candidate evidence；
3. bounded `videos.list` verification；
4. 更新 canonical history；
5. rebuild / publish current historical static projection；
6. readback 驗證。

因此：

```text
WebSub / Today = low-latency evidence
6-hour lifecycle reconcile = completeness + history convergence
```

兩者是互補，而不是二選一。

這也是 HoloDocchi 從 Today 變成 History 的核心：

```text
real-time / near-real-time evidence
        ↓
canonical lifecycle reconciliation
        ↓
ended + temporally complete VOD
        ↓
monthly historical static data
        ↓
History reader
```

當直播真正結束並取得可信 `actual_start` / `actual_end`，它才符合歷史頁所要求的 ended archive contract。

---

### 為什麼不是只用 WebSub

只靠 WebSub 有幾個風險：

- lease 可能過期；
- subscription coverage 可能不完整；
- callback 可能遺失或延遲；
- duplicate callback 必須去重；
- deleted entry 仍需要 reconciliation；
- WebSub 是 event evidence，不是完整 historical metadata authority。

所以 uploads-head catch-up 與 periodic reconcile 是必要的補洞機制。

### 為什麼不是只 polling uploads playlist

只靠固定 polling uploads playlist 雖然容易理解，但：

- 新直播被發現的 latency 取決於 polling interval；
- 頻率提高會增加 provider request / quota；
- 頻率降低則 Today freshness 變差。

因此目前架構採：

```text
event-driven fast path
+
bounded periodic reconciliation
```

而不是把所有 freshness 都壓在高頻 polling 上。

---

### 目前尚未完成公開鑑識的部分

這一章目前只描述 **公開 reader 的 lifecycle interpretation**。

尚未在本 handbook 完成核對：

- lifecycle transition 的完整 server-side state machine；
- stale threshold 的實際時間參數；
- concurrent viewer 的採樣頻率；
- 目前 live WebSub lease coverage 與當下 roster version 是否完全一致；
- 直播刪除、轉私人或重開台的所有 source-side edge-case 規則。

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

### Upstream discovery: how Today's streams are discovered

The `/today` catalog shown by the frontend is not generated by the browser calling YouTube directly.

The lifecycle design separates completeness discovery from low-latency event evidence:

```text
Uploads playlist head ─┐
WebSub / Today evidence ├─→ candidate video_id union
Stream Catalog ─────────┘
                         ↓
                 bounded videos.list
                         ↓
              canonical history store
                         ↓
             rebuildable static history
```

Each source has a different responsibility.

#### Uploads playlist: completeness discovery

The uploads playlist is the completeness path.

In steady state, each active tracked channel begins from its playlist head:

- normally page 1 is sufficient;
- if the previous successful head is present, stop;
- otherwise follow nextPageToken until the previous head is crossed;
- catch-up has a fail-closed page bound rather than scanning without limit.

The uploads path therefore provides a recoverable discovery path even when low-latency notifications are missed.

#### WebSub / Today evidence: low-latency seen-before and lifecycle evidence

WebSub is not treated as the sole historical discovery authority. Its role is to get new-video or lifecycle evidence into the Today path quickly.

Engineering records describe safeguards including:

- only approved-roster channels are accepted;
- subscription leases must be active;
- callback deliveries require signature validation;
- duplicate callbacks must be idempotent;
- stale duplicate notifications must not resurrect an ended stream;
- incomplete WebSub coverage must not be considered ready for primary mode;
- deleted-entry events require bounded reconciliation rather than guessed deletion state.

These are design principles for using WebSub safely.

**Evidence status:** historical acceptance records reached 85/85 active lease coverage for the previous 85-channel roster. The lifecycle roster has since evolved to 86 tracked identities, with one retired and 85 active. This handbook has not re-read current live lease state, so it does not claim present-day 85/85 coverage.

#### Stream Catalog: seen-before and lifecycle evidence

The existing Stream Catalog is read during lifecycle reconciliation to contribute previously seen video identity and lifecycle evidence.

It is not a second long-term historical authority; it contributes to the candidate union.

#### videos.list: metadata and current-state verification

Candidate video IDs are not automatically treated as complete video records.

Fresh or retry-eligible candidates enter bounded `videos.list` verification:

- up to 50 video IDs per request;
- fresh-priority work runs first;
- historical retry work is bounded and backoff-controlled;
- null/empty provider observations cannot erase stronger known metadata;
- provider omission does not automatically delete an existing canonical row.

This separates “we discovered this video ID” from “we verified its current metadata/state.”

---

### Which channels are tracked

The current versioned lifecycle roster contains:

```text
86 tracked channel identities
- 1 retired
= 85 active for steady-state discovery
```

The exact channel IDs are versioned source data rather than frontend title heuristics.

The roster consists of:

- a historical baseline of 66 channels;
- 20 activation-only additions.

An activation-only channel is not automatically authorized for full historical backfill. Lifecycle ingestion begins at its approved activation boundary.

This prevents adding a newly tracked channel from unintentionally triggering a large historical crawl.

Public documentation should therefore describe a **versioned roster + activation policy**, not hard-code channel identities into discovery logic.

---

### Update cadence: Today and History use different cadences

#### Today

Today's low-latency behavior primarily depends on event evidence such as WebSub plus existing Today / Stream Catalog updates.

It does **not** mean the homepage waits six hours between updates.

The purpose of WebSub is to allow new uploads or livestream events to become visible without waiting for the full historical reconciliation cycle.

#### Historical lifecycle reconciliation

The current historical lifecycle scheduler defaults to:

```text
6 hours
```

or:

```text
21600 seconds
```

The cycle performs:

1. uploads-head reconciliation;
2. Stream Catalog candidate merge;
3. bounded `videos.list` verification;
4. canonical-history update;
5. rebuild/publication of the current historical static projection;
6. readback validation.

Therefore:

```text
WebSub / Today = low-latency evidence
6-hour lifecycle reconcile = completeness + history convergence
```

They complement one another.

The transition from Today to History is conceptually:

```text
real-time / near-real-time evidence
        ↓
canonical lifecycle reconciliation
        ↓
ended + temporally complete VOD
        ↓
monthly historical static data
        ↓
History reader
```

A stream becomes a valid historical archive entry only when it has trustworthy ended-state timing such as valid `actual_start` and `actual_end`.

---

### Why not use only WebSub

WebSub alone has failure modes:

- leases expire;
- subscription coverage can be incomplete;
- callbacks can be delayed or missed;
- duplicate callbacks require deduplication;
- deleted entries still require reconciliation;
- event notification is not a complete historical metadata authority.

Uploads-head catch-up and periodic reconciliation are therefore the completeness backstop.

### Why not use only uploads polling

Fixed uploads polling is simpler, but:

- discovery latency becomes the polling interval;
- raising frequency increases provider request/quota cost;
- lowering frequency reduces Today freshness.

The current architecture therefore uses:

```text
event-driven fast path
+
bounded periodic reconciliation
```

rather than pushing all freshness requirements onto high-frequency polling.

---

### Parts not yet forensically documented

This chapter currently describes the **public reader's lifecycle interpretation**.

The handbook has not yet completed source review for:

- the complete server-side lifecycle transition state machine;
- the actual stale-threshold parameter;
- concurrent-viewer sampling frequency;
- whether current live WebSub lease coverage exactly matches the current roster version;
- all source-side edge-case rules for deletion, privatization or stream restarts.

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
