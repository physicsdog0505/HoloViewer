# 08 — 多人連動識別 / Collaboration identification

## 繁體中文

### 問題

多人連動最容易犯的錯，不是漏掉一場合作，而是把**其實沒有共同事件關係的直播誤合併**。

例如兩支直播可能：

- 同時開播；
- 都寫「ARK」；
- 都有相似遊戲名稱；
- 都出現在同一天；
- 都屬於 Hololive；

但這些條件本身仍不能證明它們是同一場多人連動。

因此 HoloDocchi 把：

    candidate detection

和：

    verified event identity

明確分開。

---

### 1. Candidate 不是 proof

早期 prototype 的 candidate detector 已明確註記：

> Candidate grouping is NOT proof of an actual collab.

也就是：

    candidate group
    !=
    verified collab event

這個 distinction 很重要，因為只有 verified event 才能安全啟用跨 POV 的 event-clock / timeline synchronization。

---

### 2. 明確事件詞的候選偵測

對某些已知大型活動，例如 Hololive ARK 類型，prototype 使用比較保守的規則：

- title / source label 必須同時命中 ARK 與明確活動詞；
- generic「ARK」本身不夠；
- 至少兩個不同 channel；
- lifecycle 必須在 live / ended / upcoming；
- 必須有 start time，或至少有可解釋的 fallback start label；
- 同一 event day 才會聚類。

這是「候選群組」產生器，不是 verified sync generator。

---

### 3. 為什麼活動日不是午夜切換

某些大型遊戲活動會跨午夜。

prototype 對 ARK 類活動使用 Taipei time 的：

    06:00 rollover

也就是 00:00–05:59 仍視為前一個 event day。

這不是通用規則，而是特定活動 domain policy。

這個例子說明：

> event day 不一定等於 calendar day。

如果活動本身跨夜，直接用 YYYY-MM-DD 午夜切割可能把同一場活動拆成兩群。

---

### 4. 缺少 verified start 時的 fallback evidence

如果某個 POV 的正式 start metadata 尚未補齊，但 UI 已有：

    MM/DD HH:MM

這類 start label，prototype 可以拿它作為 discovery evidence。

但這個 fallback 有明確限制：

- 只能幫助 candidate grouping；
- 不能升級為 verified YouTube actual_start；
- 不能直接拿去做 timeline sync。

因此：

    presentation/discovery evidence
    !=
    timing authority

---

### 5. Generic shared-topic candidate

對非特定活動，prototype 曾使用較保守的 shared-topic 規則：

- 兩個不同 channel；
- start time 相差不超過約 20 分鐘；
- title/source label 經 tokenization 後至少有一個 shared token；
- generic stopwords 會排除。

符合的 pair 會進一步做 overlap merge，形成較大的 candidate group。

但 confidence 仍是：

    shared-topic

而不是 verified。

---

### 6. 為什麼不把所有相似標題都當連動

如果只做 title similarity：

- 同遊戲的獨立直播容易被誤合併；
- 「Minecraft」「ARK」「歌回」等熱門詞會產生大量 false positive；
- 同時間開播也可能只是巧合；
- 同一天活動很多時，事件 identity 會漂移。

因此 current public frontend 明確採取更保守策略：

> 不從標題或日期自行發明 verified collab identity。

前端只 consume 已發布的 collab event data。

---

### 7. Current public event contract

目前 public frontend 只接受符合公開 collab schema 的事件集合。

事件至少需要：

- event_id；
- 兩個以上 streams；
- 每個 stream 有合法 video_id；
- 若要啟用 verified VOD sync，event 必須明確宣告 sync.available = true。

如果 event 只有一支 stream，就不當成多人連動。

---

### 8. Live collab 和 historical VOD collab

#### Live

對 live event：

- 初始畫面優先掛載 lifecycle = live 的 POV；
- 如果目前沒有 live，但有 upcoming / waiting，可先顯示等待中的 roster；
- viewer 會持續 reconcile active POV。

Live event 不會因為「同標題」就臨時把新影片塞進 verified event。

#### VOD

對 historical collab：

- 可以載入完整 roster；
- 若 sync.available = true，才啟用 Chapter 07 master timeline；
- 若沒有 verified sync，仍可以多人觀看，但不能宣稱時間軸已對齊。

因此：

    multi-view available
    !=
    sync verified

---

### 9. Event identity 必須唯一

candidate resolver 對使用者要求的 video set，只在：

    exactly one candidate contains all requested videos

時才回傳結果。

如果同一支影片同時屬於多個候選群組，單靠該影片無法唯一決定 event，就返回 unresolved。

這是避免 ambiguous event identity 的基本原則。

---

### 10. Current public frontend 的保守選擇

首頁近期焦點的程式碼甚至有明確註解：

> Public does not currently expose verified collab-candidate IDs; dedupe by video ID only, never invent shared event identity from titles or dates.

這代表 HoloDocchi 現在寧願：

- 少自動合併一些 event；

也不要：

- 把兩場不相關直播誤標成同一連動。

這是一個 precision > recall 的選擇。

---

### 已確認失敗／風險

#### F-026 — Generic game title = same collab
Status: explicitly avoided.

Generic ARK / Minecraft / collab wording 不足以證明同一 event。

#### F-027 — Same time = same event
Status: explicitly avoided.

相近開播時間只能當 weak evidence。

#### F-028 — Candidate group 直接啟用 timeline sync
Status: explicitly forbidden by design.

Candidate 不是 timing authority。

#### F-029 — Ambiguous candidate 強行選第一個
Status: explicitly avoided.

如果 requested stream set 同時落入多個候選群組，resolver 返回 unresolved。

---

### Trade-offs

保守策略會漏掉一些真正合作：

- 標題完全不同；
- 沒使用共同 hashtag；
- start metadata 不完整；
- event 沒事先建立 canonical identity。

這是 precision 與 recall 的取捨。

對「只是顯示多人入口」可能可以接受較高 recall；對「啟用時間同步」則必須要求更高 confidence。

---

### 可改進方案

#### Explicit event registry

最可靠的方法仍是由 event producer 建立：

- event_id；
- participant roster；
- source evidence；
- sync verification status。

#### Evidence scoring

candidate 可以改成：

    title evidence
    + hashtag evidence
    + start-time proximity
    + participant overlap
    + schedule/event-page evidence

形成 confidence score。

但 score 仍不應自動等同 verified sync。

#### Human-assisted confirmation

高 confidence candidate 可進 review queue，由人工確認 event identity。

#### Graph clustering with explainability

可將 stream 建成 graph，edge 保存「為什麼兩支被認為相關」，避免黑箱 clustering。

HoloDocchi 目前最重要的原則是：

> Event identity 不應由方便的 heuristic 悄悄升級成事實。

---

## English

### Problem

The most dangerous collaboration-identification error is not missing a collab, but merging streams that do not actually belong to the same event.

Two streams can start at similar times, mention the same game, occur on the same day and both belong to Hololive without sharing one event identity.

HoloDocchi therefore separates:

    candidate detection

from:

    verified event identity

### 1. Candidate is not proof

The early prototype explicitly documented:

> Candidate grouping is NOT proof of an actual collab.

A candidate group must not automatically enable event-clock or timeline synchronization.

### 2. Explicit-event candidate detection

For known event families such as Hololive ARK, the prototype used conservative rules:

- title/source label must include ARK plus explicit event wording;
- generic ARK alone is insufficient;
- at least two different channels;
- lifecycle in live / ended / upcoming;
- a start time or limited fallback start label;
- same event day.

This creates candidates, not verified synchronization.

### 3. Event day can differ from calendar day

For cross-midnight ARK-style events, the prototype used a Taipei 06:00 rollover, so 00:00–05:59 remains part of the previous event day.

This is event-specific domain policy, not a universal date rule.

### 4. Fallback start labels are discovery evidence only

An MM/DD HH:MM label can help cluster a stream whose verified start metadata has not hydrated yet.

It is not promoted to verified YouTube actual_start and must not directly become timeline authority.

### 5. Generic shared-topic candidates

For non-explicit events, the prototype required different channels, start times within roughly 20 minutes, and at least one meaningful shared title/source token after stopword removal.

Overlapping pairs could be merged into larger candidate groups, but confidence remained shared-topic rather than verified.

### 6. Why title similarity is insufficient

Pure title similarity can incorrectly merge independent streams of popular games or topics.

The current public frontend therefore does not invent verified collab identity from titles or dates. It consumes already-published collab event data.

### 7. Current public event contract

A usable collab event must contain an event identity and at least two valid stream entries.

Verified historical synchronization requires an explicit sync.available=true declaration.

### 8. Live versus historical collab

Live events mount currently live POVs and can wait on upcoming/waiting roster entries.

Historical events can load the full roster, but master-timeline synchronization is enabled only when synchronization is explicitly verified.

Therefore:

    multi-view available
    !=
    sync verified

### 9. Event resolution must be unambiguous

A candidate resolver returns an event only when exactly one candidate contains the entire requested video set.

If multiple candidates match, the result remains unresolved rather than choosing the first one.

### 10. Conservative public behavior

The current public frontend explicitly avoids inventing shared event identity from titles or dates when verified candidate IDs are not available.

This is a precision-over-recall choice.

### Failed / risky approaches

- F-026 — Generic game title means same collab: explicitly avoided.
- F-027 — Similar start time means same event: explicitly avoided.
- F-028 — Candidate group directly enables timeline sync: forbidden by design.
- F-029 — Ambiguous candidate chooses the first match: explicitly avoided.

### Trade-offs and alternatives

Conservative identification can miss real collaborations with different titles, no shared hashtag or incomplete timing metadata.

Better approaches include explicit event registries, explainable evidence scoring, human-assisted confirmation and graph clustering whose edges record why streams are related.

The core principle is:

> Convenient heuristics must not silently become event truth.

[回目錄 / Index](README.md)
