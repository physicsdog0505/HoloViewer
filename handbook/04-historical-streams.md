# 04 — 歷史直播系統 / Historical stream browsing

## 繁體中文

### 問題

歷史直播不是把「今天直播列表」換一個日期就完成。

系統需要同時處理：

- 直播實際開始時間與使用者所在產品日界線；
- 跨 UTC 月份但屬於同一台北日期的影片；
- 已刪除、私人或不可用影片；
- 同一影片重複出現在不同資料來源；
- 單日瀏覽與跨月份搜尋的不同讀取成本；
- 成員名稱、粉絲暱稱、多語別名；
- 日期搜尋與文字搜尋混合輸入；
- 多成員／連動搜尋；
- 中文字幕是否可用；
- 大量搜尋結果的逐步顯示。

因此歷史頁不是單一 API query，而是一個「靜態歷史目錄 + 搜尋意圖解析 + client-side projection」系統。

### 資料權威與讀取順序

目前 reader 優先讀取已發布的 YouTube historical static assets。

概念流程：

```text
history manifest
  ↓
published month lookup
  ↓
monthly video payload
  ↓
normalize / validate rows
  ↓
Taipei-day projection
  ↓
dedupe + sort
  ↓
search / subtitle / channel filters
  ↓
render
```

如果 static request 發生一般技術錯誤，reader 可以 fallback 到既有 History API。

但如果 manifest 明確表示該月份**尚未公開**，則不會假裝 static 失敗而偷偷 fallback；這種狀態被視為 publication availability，而不是 transient server error。

這個差異很重要：

```text
unpublished != temporarily broken
```

### 為什麼歷史資料使用 static-first

歷史 VOD 一旦結束，其 lifecycle 不需要像直播中資料一樣高頻更新。

使用月份 static assets 的好處：

- 不需要每次搜尋都重新查遠端來源；
- 可以對月份做完整性驗證；
- 可以獨立發布月份；
- browser 可以重用月份 payload；
- 搜尋可在已發布資料上直接運算；
- 大量歷史讀取不必全部進動態 API。

代價則是 publication latency：新結束影片必須先進入正式歷史資料面，不能假設「YouTube 已存在」就代表 HoloDocchi historical static 已可讀。

---

### 時間與日期歸屬

#### Taipei day 是產品語意

歷史頁以 **Asia/Taipei** 計算影片屬於哪一天。

日期來源依序使用：

```text
actual_start
→ scheduled_start
→ start_at
→ published_at
```

這代表同一個 UTC timestamp 在不同時區可能屬於不同日期，但 HoloDocchi 歷史頁使用固定產品時區，確保不同使用者看到相同的日期分類。

#### 為什麼月初可能需要讀前一個月份

假設影片的 UTC timestamp 還在前一個月，但轉成 Taipei time 已經是新月份 1 日。

如果只讀「選取日期字串的月份檔」，就可能漏掉跨時區邊界的影片。

目前 reader 在處理月份第一天時，會同時考慮前一個月份 payload，再依 Taipei day 過濾。

這是一個很容易在 static month partition 中忽略的 edge case。

---

### 哪些影片可以進入歷史列表

公開 reader 會先 normalize historical video row。

至少需要：

- 合法 YouTube video ID；
- 被標記為直播 archive；
- 有可解析的 actual start；
- 有可解析的 actual end；
- end > start；
- availability 不是 private / unavailable。

符合後才投影成：

```text
lifecycle_state = ended
```

這裡不是單純相信來源寫了 ended，而是要求歷史用途所需的基本時間完整性。

### 去重與排序

多個月份或不同 projection 合併時，以 `video_id` 去重。

排序主要使用：

```text
actual_start DESC
→ scheduled_start DESC
→ video_id stable tie-break
```

也就是較新的歷史直播先顯示，並提供 deterministic tie-break。

---

### 單日瀏覽

沒有搜尋字串時，reader 以單日模式工作。

目前 page size：

```text
50 videos
```

回傳／顯示模型：

```text
offset = (page - 1) × 50
page = rows[offset : offset + 50]
```

並依 `total` 或 `has_more` 判斷是否提供上一頁／下一頁。

這個模式適合「我想看某一天發生什麼」。

---

### 搜尋模式與單日瀏覽不同

有搜尋字串時，系統不只對當天 50 筆做 filter。

目前行為會依輸入意圖選擇：

- 指定日期／日期區間 → 載入區間涵蓋月份；
- 一般搜尋 → 載入選取月份；
- 再於完整候選集合執行成員／文字搜尋。

因此：

```text
day browsing != search candidate scope
```

這個差異是為了避免搜尋「百鬼」時只搜尋目前畫面那 50 筆。

---

### 搜尋文字正規化

搜尋字串會：

1. Unicode NFKC normalize；
2. 轉小寫；
3. 非 Unicode letter / number 轉成空白；
4. collapse 重複 whitespace。

因此全形／半形及部分格式差異不需要使用者自行處理。

---

### 日期意圖解析

搜尋框支援日期或日期區間意圖。

可辨識的概念包括：

```text
YYYY/MM/DD
MM/DD
YYYY-MM-DD
MM-DD
start ~ end
start ～ end
```

若只輸入月／日，會使用目前選取年份作為 year hint。

日期區間的終點如果是今天，會 clamp 到目前 historical latest，也就是昨天，避免歷史搜尋混入今天尚未完全結束的 lifecycle。

### 混合搜尋

日期可以和文字一起輸入。

概念：

```text
11/01 ~ 11/15 百鬼
```

會拆成：

```text
date intent = 11/01 ~ 11/15
text query = 百鬼
```

然後先決定資料範圍，再執行文字／成員搜尋。

---

### 成員別名搜尋

HoloDocchi 不只直接比對影片 title。

成員 alias registry 將 alias 分成至少：

- strong alias；
- weak alias。

#### Strong alias

只有在 alias 唯一指向一位成員時，才直接轉成 member identity。

多 token alias 會優先於較短 alias，以避免短詞先把長稱呼拆掉。

概念上，粉絲暱稱可以被解析成 channel identity，而不是只做 title substring search。

#### Weak alias

weak alias 不直接當成同等強度的身份判定。

它會作為 hint，降低過度匹配常見詞的機率。

這個 strong / weak 分層是避免 alias 系統「越加越多，誤判越嚴重」的重要設計。

---

### CJK 與 Latin 搜尋差異

對日文／中文等 CJK alias，匹配可以使用去空白後 substring。

對 Latin token，單一詞更偏向 token exact match，多詞則可使用 normalized phrase match。

原因是：

- CJK 通常沒有空白分詞；
- 英文短詞若隨意 substring matching，容易產生大量 false positive。

---

### 多成員搜尋

當 query 解析出多位成員時，搜尋結果會優先排列「同時符合所有成員」的結果，再列出只符合部分成員的相關影片。

UI 也會明確顯示：

- 已辨識成員；
- 額外關鍵字；
- 完整多人匹配與部分匹配的差異。

這是一種 intent ranking，而不是把每個名字當互相獨立的 OR query。

---

### Channel facets

搜尋完成後，如果結果涉及多個 channel，會建立 channel facet。

每個 facet 顯示：

- channel identity；
- 該 channel 在目前結果中的筆數。

使用者可以再進一步縮小結果。

facet 是在目前搜尋結果上做 projection，不會重新改寫底層資料。

---

### 大量結果如何載入

目前搜尋結果採：

```text
HISTORY_SEARCH_BATCH_SIZE = 200
```

也就是先 render 200 筆。

若還有更多：

- 顯示「載入更多」；
- 每次再增加最多 200；
- 若 browser 支援 IntersectionObserver，當按鈕進入距 viewport 約 600 px 的區域時，自動觸發 load more。

因此搜尋結果的「往下滑繼續出現」目前主要是：

```text
all candidate rows already loaded
→ progressive rendering in batches of 200
```

而不是每滑到底才去 server 取下一個更大的歷史日期範圍。

這是非常重要的實作差異。

---

### 中文字幕篩選

中文字幕不是從影片 title 猜。

系統會先載入 subtitle availability index，形成可用 video ID set。

篩選本質是：

```text
history video_id ∈ subtitle availability set
```

如果 subtitle index 不可用，filter 會被 disabled／取消，而不是把所有影片誤判為「沒有字幕」。

這也是「unknown availability」與「confirmed no subtitle」需要區分的例子。

---

### Manifest cache 與 month cache

history manifest 有短期 memory cache；目前公開程式設定：

```text
manifest TTL = 60 seconds
```

月份 payload 則依 path 在 browser page lifetime 中 cache。

目的：

- manifest 需要相對新，因為 published month inventory 可能改變；
- 已讀取的 month payload 不需要每次搜尋重新下載。

這是 metadata freshness 與 large-payload reuse 的折衷。

---

### 已知失敗／風險做法

#### F-010 — 只搜尋目前單日頁面的 50 筆
**狀態：目前搜尋架構已避免**

若搜尋只是對畫面上目前載入的 50 筆做 filter，使用者搜尋成員時會錯過同月份其他影片。

目前搜尋候選範圍與單日分頁解耦。

#### F-011 — 把所有 alias 都當 substring
**狀態：目前設計明確避免**

大量暱稱、短詞與多語名稱若全部 substring matching，false positive 會快速增加。

目前透過 strong / weak alias、唯一性要求，以及 CJK / Latin 不同匹配策略降低風險。

#### F-012 — 月份 partition 只看 UTC/calendar month
**狀態：目前 reader 明確處理 edge case**

如果產品日期使用 Taipei time，月初只讀同名月份可能漏掉前一 UTC 月份、但在 Taipei 已屬新月的影片。

目前月份第一天會額外考慮前月 payload。

#### Legacy fallback 的風險

Static 技術錯誤時 fallback API 提升可用性，但也可能使兩套來源短時間呈現不同資料。

目前 fallback 僅在 static 發生技術性錯誤時使用；manifest 明確「尚未發布」不視為技術故障。

---

### 目前限制

#### 1. 搜尋候選資料與 progressive rendering 是兩件事

目前 200 筆 load-more 是 UI rendering batch，不是逐步擴大搜尋日期範圍。

因此對「不知道日期、只知道成員」的全歷史搜尋，仍需要更好的 candidate-window strategy。

#### 2. 中文字幕入口仍可改善

目前 subtitle filter 是 availability filter。

從產品 UX 角度，「我要找有中文字幕的影片」可能更適合作為獨立 discovery mode，而不是一般搜尋上的 tag/filter。

這是已知 UX 改善方向，不應描述成已完成。

#### 3. Member search initial window

目前一般 query 以選取月份為主要候選範圍；若目標是「搜尋某成員最近 20–50 支影片，再向下自動擴張時間窗」，需要另一層 incremental historical search strategy。

這個方案目前屬於**設計方向，不是現行實作**。

#### 4. Static + legacy fallback consistency

fallback 可以提升 availability，但沒有保證 static 與 legacy API 在每個時刻內容完全相同。

#### 5. Alias registry 需要治理

alias 是資料，不是免費的搜尋能力。新增 alias 必須考慮：

- collision；
- common-word false positives；
- multilingual ambiguity；
- retired / renamed member identity；
- fan nickname 的區域差異。

---

### 可改進方案

對更大型的歷史系統，可以考慮：

#### Incremental search window

成員搜尋先讀最近 N 支／最近 M 天，使用者繼續向下時再擴大：

```text
recent window
→ older window
→ older window
```

而不是一開始載入整月或整年。

#### Dedicated inverted search index

為 member、keyword、subtitle availability 建獨立 index，避免 browser 掃描完整月份 payload。

#### Cursor-based history search

server 或 static index 提供：

```text
query + cursor → next N matches
```

可將「資料範圍擴張」與「UI render batch」真正統一。

#### Search confidence

對 strong / weak alias、keyword、collab match 顯示 confidence 或 matched reason，使搜尋結果更可解釋。

目前 HoloDocchi 的 client-side static search 適合現階段資料規模，但不應假設它是資料量持續成長後的最佳解。

---

## English

### Problem

Historical browsing is not simply “today's livestream list with a different date.”

The system must handle:

- actual start time versus the product's date boundary;
- videos that cross UTC month boundaries while belonging to the same Taipei date;
- deleted, private or unavailable videos;
- duplicate videos across source projections;
- different access costs for daily browsing and cross-month search;
- member names, fan nicknames and multilingual aliases;
- mixed date and text search;
- multi-member / collaboration intent;
- Traditional Chinese subtitle availability;
- progressive rendering of large result sets.

The history page is therefore a system combining a static historical catalog, search-intent parsing and client-side projection rather than a single API query.

### Data authority and read order

The reader currently prefers published YouTube historical static assets.

Conceptually:

```text
history manifest
  ↓
published month lookup
  ↓
monthly video payload
  ↓
normalize / validate rows
  ↓
Taipei-day projection
  ↓
dedupe + sort
  ↓
search / subtitle / channel filters
  ↓
render
```

If static access fails for a general technical reason, the reader can fall back to an existing History API.

However, if the manifest explicitly says that a month is **not published**, the reader does not disguise that state as a transient static failure and silently fall back.

The distinction is:

```text
unpublished != temporarily broken
```

### Why historical data is static-first

Once a VOD has ended, its lifecycle does not require the same high-frequency updates as a live stream.

Month-scoped static assets provide:

- no need to refetch/recompute source data on every search;
- month-level integrity validation;
- independently publishable months;
- reusable browser payloads;
- local search over published data;
- lower dynamic-service read load.

The trade-off is publication latency: a video existing on YouTube does not automatically mean it is already available in HoloDocchi's historical publication surface.

---

### Time and date ownership

#### Taipei day is product semantics

History assigns videos to days using **Asia/Taipei**.

Timestamp precedence is:

```text
actual_start
→ scheduled_start
→ start_at
→ published_at
```

The same UTC timestamp can belong to different local dates, but HoloDocchi uses a fixed product timezone so all users see the same historical date classification.

#### Why the first day of a month may require the previous month's payload

A video's UTC timestamp can still belong to the previous month while its Taipei-local date is already the first day of the new month.

Reading only the month named by the selected date would therefore miss some videos.

The current reader considers the previous month payload around this boundary and then filters by Taipei day.

This is an easy edge case to miss in month-partitioned static datasets.

---

### Which videos qualify for history

The public reader normalizes each historical row.

At minimum it requires:

- a valid YouTube video ID;
- a live-archive marker;
- a parseable actual start;
- a parseable actual end;
- end > start;
- availability not marked private or unavailable.

Only then is the row projected as:

```text
lifecycle_state = ended
```

The history view therefore requires basic temporal completeness rather than merely trusting an “ended” label.

### Deduplication and ordering

When projections or month payloads are combined, rows are deduplicated by `video_id`.

Ordering primarily uses:

```text
actual_start DESC
→ scheduled_start DESC
→ video_id stable tie-break
```

so newer history appears first with deterministic tie-breaking.

---

### Daily browsing

Without a search query, the reader operates in daily mode.

Current page size:

```text
50 videos
```

The model is:

```text
offset = (page - 1) × 50
page = rows[offset : offset + 50]
```

Previous/next pagination is determined from `total` or `has_more`.

This mode answers “what happened on this day?”

---

### Search mode differs from daily browsing

With a search query, filtering is not limited to the currently visible 50 rows.

Candidate scope depends on intent:

- explicit day/range → load the months covering that range;
- ordinary query → load the selected month;
- then perform member/text search across the candidate set.

Therefore:

```text
day browsing != search candidate scope
```

This prevents a member query from searching only the currently displayed page.

---

### Search normalization

Search input is:

1. Unicode NFKC-normalized;
2. lowercased;
3. non-letter/non-number characters converted to spaces;
4. repeated whitespace collapsed.

Users therefore do not need to manually handle many full-width/half-width formatting differences.

---

### Date-intent parsing

The search field can recognize dates and ranges conceptually such as:

```text
YYYY/MM/DD
MM/DD
YYYY-MM-DD
MM-DD
start ~ end
start ～ end
```

Month/day input uses the currently selected year as a hint.

If a range requests today as its end, the reader clamps it to the latest historical date (yesterday), avoiding incomplete current-day lifecycle data.

### Mixed search

A date expression can appear with text.

For example:

```text
11/01 ~ 11/15 Ayame
```

is conceptually split into:

```text
date intent = 11/01 ~ 11/15
text query = Ayame
```

The data range is resolved first, then member/text matching is applied.

---

### Member alias search

HoloDocchi does not search only by raw title substring.

The member alias registry distinguishes at least:

- strong aliases;
- weak aliases.

#### Strong aliases

A strong alias is converted directly into member identity only when it uniquely identifies one member.

Longer multi-token aliases are considered before shorter aliases so a shorter token does not consume part of a longer name.

A fan nickname can therefore resolve to channel identity rather than remaining only a title substring.

#### Weak aliases

Weak aliases are not treated with equal identity confidence.

They act as hints, reducing the risk that common words become aggressive identity matches.

The strong/weak distinction helps prevent a growing alias registry from creating an increasing number of false positives.

---

### CJK versus Latin matching

For CJK aliases, normalized whitespace-insensitive substring matching can be appropriate because those scripts generally do not rely on spaces for tokenization.

For Latin input, single terms are closer to exact token matching, while multi-term aliases can use normalized phrase matching.

This avoids excessive false positives from short Latin substrings.

---

### Multi-member search

When a query resolves to multiple members, results that match all recognized members are prioritized before partially related results.

The UI also exposes:

- recognized members;
- remaining keywords;
- the difference between complete and partial multi-member matches.

This is intent ranking rather than a simple OR across every name.

---

### Channel facets

When search results span multiple channels, the client constructs channel facets.

Each facet contains:

- channel identity;
- the number of results for that channel.

Filtering is a projection over the existing search result set and does not rewrite source data.

---

### Loading large result sets

Current search rendering uses:

```text
HISTORY_SEARCH_BATCH_SIZE = 200
```

The first 200 rows are rendered.

If more remain:

- a “load more” control is shown;
- each activation increases the render limit by up to 200;
- when IntersectionObserver is available, entering roughly 600 px before the control automatically triggers the next batch.

The current “keep scrolling to see more” behavior is therefore primarily:

```text
candidate rows already loaded
→ progressive rendering in batches of 200
```

It is **not** currently a server request that expands into an older date window every time the user reaches the bottom.

That distinction matters when evaluating future search architecture.

---

### Traditional Chinese subtitle filtering

Subtitle availability is not inferred from video titles.

The reader loads a subtitle availability index and builds a set of video IDs.

The filter is effectively:

```text
history video_id ∈ subtitle availability set
```

If the subtitle index is unavailable, the filter is disabled/reset rather than treating every video as confirmed to have no subtitles.

This is another case where “unknown availability” differs from “confirmed absent.”

---

### Manifest and month caching

The history manifest has a short in-memory cache. Current public source specifies:

```text
manifest TTL = 60 seconds
```

Month payloads are cached by path for the lifetime of the page.

The rationale is:

- manifest inventory can change and should remain relatively fresh;
- already retrieved month payloads should not be repeatedly downloaded for every search.

This balances metadata freshness with payload reuse.

---

### Failed / risky approaches

#### F-010 — Searching only the visible daily page
**Status: avoided by the current search architecture**

Filtering only the currently visible 50 rows would miss other videos from the candidate month or date range.

Search candidate scope is therefore separated from daily pagination.

#### F-011 — Treating every alias as a substring
**Status: explicitly avoided by the current design**

A growing set of nicknames and short multilingual terms would create increasing false positives if every alias were substring-matched.

The current design uses strong/weak aliases, uniqueness requirements and different CJK/Latin matching behavior.

#### F-012 — Treating month partitions as pure UTC/calendar months
**Status: edge case explicitly handled by the reader**

A Taipei-local first-of-month video can still belong to the previous UTC month.

The reader accounts for the previous payload near that boundary.

#### Legacy fallback risk

Falling back from static history to an API can improve availability but can also expose temporary differences between two data sources.

The current reader falls back for technical static failures, not for an explicitly unpublished month.

---

### Current limitations

#### 1. Candidate loading and progressive rendering are different

The 200-row load-more behavior controls UI rendering, not date-range expansion.

A true “search this member's recent 20–50 videos and progressively go further back” mode would need a separate candidate-window strategy.

#### 2. Subtitle discovery can be improved

The current subtitle control is an availability filter.

From a product perspective, “show me videos with Traditional Chinese subtitles” may deserve a dedicated discovery mode rather than appearing only as a tag/filter.

That is a known design direction, not current implementation.

#### 3. Initial member-search window

Ordinary queries currently use the selected month as the primary candidate scope.

A member-centric mode that begins with the most recent N matching videos and expands backward on demand requires an incremental historical search layer.

That is a **proposal**, not current behavior.

#### 4. Static + legacy fallback consistency

Fallback improves availability, but static and legacy API data are not guaranteed to be perfectly identical at every moment.

#### 5. Alias governance

Aliases are data and require governance. Adding an alias can introduce:

- collisions;
- common-word false positives;
- multilingual ambiguity;
- retired/renamed identity issues;
- regional variation in fan nicknames.

---

### Alternative approaches

For a larger historical corpus, alternatives include:

#### Incremental search windows

Start member search with the most recent N videos or M days and expand backward:

```text
recent window
→ older window
→ older window
```

rather than loading an entire month or year up front.

#### Dedicated inverted search index

Build member, keyword and subtitle-availability indexes so the browser does not scan full month payloads.

#### Cursor-based history search

Provide:

```text
query + cursor → next N matches
```

so candidate expansion and UI pagination become one model.

#### Search confidence

Expose why a result matched: strong alias, weak hint, keyword, collaboration, subtitle availability, etc.

The current client-side static search is suitable for the present architecture, but it should not be assumed to remain optimal as the corpus grows.

[回目錄 / Index](README.md)
