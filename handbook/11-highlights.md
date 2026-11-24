# 11 — 精選與熱門內容 / Highlights and featured content

## 繁體中文

### 問題

首頁的「近期焦點」容易被誤解成：

- 同接排行榜；
- AI 推薦；
- 熱度模型；
- engagement ranking。

目前都不是。

現行 highlight 是一套**可解釋的規則式 editorial heuristic**。

---

### 1. Candidate scope

只有：

    lifecycle = live
    OR
    lifecycle = upcoming

的影片才進入近期焦點候選。

ended 不進這個 carousel。

每個 video_id 只保留一次。

---

### 2. 規則式事件類型

目前公開前端有一組 explicit rules。

主要類型包括：

- 三期生告知；
- 重大告知；
- 初配信 / debut；
- 周年；
- 新衣裝；
- 生日；
- 3D LIVE；
- 大型聯動；
- 歌回；
- 新造型 / model reveal。

每種類型有固定 score。

例如較高優先度會給重大告知、debut、周年、新衣裝、生日等。

如果候選目前是 live，會再得到一個小幅 live bonus。

---

### 3. 為什麼是可解釋規則

對每一張 highlight，系統可以回答：

> 它命中了哪個類型？

而不是只能說：

> 模型覺得它很熱門。

這對目前資料量與產品需求有幾個優點：

- 不需要訓練資料；
- 不需要收集使用者行為；
- 不依賴歷史同接；
- ranking 可 audit；
- 錯誤時容易調整；
- 不會讓 hidden viewer count 影響曝光。

---

### 4. Score 不是 popularity score

這個 score 代表：

    editorial event priority

不是：

    audience popularity

也不是：

    predicted engagement

因此文件與 UI 不應把它稱為「人氣分數」。

---

### 5. live bonus

如果一個已命中類型的候選現在是 live，score 會增加小幅 bonus。

這只是讓「現在正在發生」的事件稍微優先於同類 upcoming event。

它不代表 live 自動比高價值 upcoming announcement 更重要。

---

### 6. 三期生告知有額外 guard

「三期生」本身太容易誤配。

因此該 rule 除了命中三期生詞彙之外，還要求同時存在告知／重大／結束／announcement 類語意。

這是一個降低 false positive 的 rule-specific guard。

---

### 7. 排序與 tie-break

候選依：

    score DESC
    → video_id stable tie-break

排序。

最後只取固定數量的 top picks。

目前上限：

    6 highlights

這個數字是首頁 presentation contract，不代表資料最多只有六支值得注意。

---

### 8. Announcement subset

部分 highlight type 另外進「最新提醒」：

- 生日；
- 重大告知；
- 三期生告知。

也就是 carousel 與 announcement strip 共享 candidate，但有不同 presentation role。

---

### 9. 為什麼目前不用 concurrent viewers

Chapter 10 已說明，current concurrent_viewers 是 coarse ephemeral observation，而且沒有歷史 sampling pipeline。

因此首頁 highlight 不用：

    concurrent_viewers
    peak viewers
    trend
    viewer growth

作 ranking signal。

這避免把：

    missing viewer count

錯當：

    low popularity

也避免 5-minute snapshot 對曝光產生過度權重。

---

### 10. 為什麼不靠 collab candidate 去重

現行 public frontend 有明確限制：

> 不在沒有 verified collab identity 時，靠 title/date 自己推斷 shared event。

所以 highlight dedupe 目前只以：

    video_id

為單位。

如果同一大型 event 有多個 POV，而 public event identity 尚未 verified，首頁可能看到多個各自符合 rule 的影片。

這是保守 precision policy 的副作用。

---

### 11. 這套規則的限制

#### Keyword brittleness

如果 title 不用我們預期的詞，就可能漏掉。

#### Language coverage

中文／日文／英文詞彙需要人工維護。

#### False positives

即使有 guard，keyword-based classification 仍可能誤判。

#### No audience signal

規則不知道觀眾實際反應。

#### No personalization

所有使用者看到相同 ranking logic。

#### Event duplication

沒有 verified event identity 時，多 POV 可能分別上榜。

---

### 已知失敗／風險

#### F-041 — 把同接當 homepage popularity truth
Status: explicitly avoided.

目前 viewer count 不足以成為穩定 ranking authority。

#### F-042 — generic keyword 無 guard
Status: partially mitigated.

例如三期生規則額外要求 announcement-like 語意。

#### F-043 — 由 title/date 自行合併 highlight event
Status: explicitly avoided.

沒有 verified collab identity 時只按 video_id dedupe。

#### F-044 — Client 自己重排 Daily Digest
Status: forbidden by separate contract.

Daily Digest 的 ordering / role 若由 artifact 提供，client 必須保留 artifact authority，不應拿首頁 highlight score 重新排序。

---

### 為什麼 Highlight 與 Daily Digest 要分開

Highlight 是：

    real-time-ish homepage heuristic

Daily Digest 是：

    finalized editorial artifact

兩者的 authority 不同。

Highlight 可以因 live/upcoming 狀態變化而改變。

Daily Digest 一旦產生，frontend 應 deterministic render，不在 browser 重新做 ranking。

這避免同一份 digest 在不同裝置因當下 viewer count 或時間變化而順序不同。

---

### 可改進方案

#### Event-aware dedupe

有 verified event_id 後，可以選：

- 每個 event 只出一張代表卡；
- 或顯示 event card + POV count。

#### Explainable multi-signal ranking

未來若真的有可靠 metrics，可以考慮：

    event priority
    + verified event identity
    + freshness
    + optional audience signal

但每個 signal 都應可解釋。

#### Separate “important” and “popular”

可以把：

    Important / Editorial
    Popular / Audience

拆成兩個區域。

這比把兩種價值硬壓成一個總分更誠實。

#### User-controlled ranking

例如：
- 活動優先；
- 正在直播優先；
- 成員偏好；
- 時間排序。

目前 HoloDocchi 的 highlight system 重點是簡單、可 audit，而不是假裝有一個精準的「熱門度真相」。

---

## English

### Problem

The homepage “recent highlights” can easily be mistaken for a viewer-count ranking, AI recommender, popularity model or engagement score.

It is currently none of those.

The current system is an explainable rule-based editorial heuristic.

### 1. Candidate scope

Only live or upcoming streams are eligible.

Ended streams are excluded, and each video ID is considered once.

### 2. Explicit event-type rules

Public frontend rules include categories such as major announcements, debuts, anniversaries, new outfits, birthdays, 3D live events, large collaborations, karaoke and model reveals.

Each category has a fixed editorial score.

### 3. Why explicit rules

For every highlighted item the system can explain which rule matched.

This avoids requiring training data, behavioral tracking, historical concurrent-viewer sampling or opaque recommendation models.

### 4. Score is not popularity

The score represents editorial event priority, not audience popularity or predicted engagement.

### 5. Live bonus

A matched candidate receives a small bonus while currently live, allowing active events to rank slightly above otherwise similar upcoming events.

### 6. Rule-specific guard

The generation-specific announcement rule requires both generation wording and announcement-like context, reducing false positives.

### 7. Ordering

Candidates are ordered by score descending with a stable video-ID tie-break.

The current presentation takes up to six highlights.

### 8. Announcement subset

Birthday, major-announcement and generation-announcement entries can also appear in the announcement strip.

### 9. Why concurrent viewers are not a ranking signal

Current viewer count is a coarse ephemeral observation and HoloDocchi does not run historical viewer sampling.

Missing counts must not become a proxy for low popularity, and a five-minute snapshot should not dominate editorial exposure.

### 10. Why collab candidates are not used for unverified deduplication

Without verified event identity, the frontend does not infer shared events from title/date heuristics.

Highlight deduplication therefore remains video-ID based.

### 11. Limitations

The system is keyword-dependent, multilingual rules require maintenance, false positives and false negatives remain possible, there is no audience or personalization signal, and unverified multi-POV events can produce multiple entries.

### Failed / risky approaches

- F-041 — treating concurrent viewers as homepage popularity truth: explicitly avoided.
- F-042 — generic keywords without guards: partially mitigated.
- F-043 — merging highlight events from title/date guesses: explicitly avoided.
- F-044 — client re-ranking of finalized Daily Digest artifacts: forbidden by separate contract.

### Highlight versus Daily Digest

Highlights are a changing homepage heuristic.

Daily Digest is a finalized editorial artifact whose ordering and roles should be rendered deterministically by the client.

These are separate authorities.

### Alternatives

Future designs could add verified event-aware deduplication, explainable multi-signal ranking, separate “important” and “popular” surfaces, or user-selectable ordering modes.

The current system prioritizes simplicity and auditability over pretending to know a single objective popularity truth.

[回目錄 / Index](README.md)
