# 05 — PTT 資料系統 / PTT data system

## 繁體中文

### 問題

PTT 專串資料表面上只是文章與推文，但要把它變成可搜尋、可回放、可與影片時間同步的歷史資料，需要同時回答：

- 即時 Collector 實際看到了什麼；
- 歷史期間是否有缺漏；
- Web mirror 可以補回什麼；
- 兩個來源對同一樓內容不同時如何處理；
- floor、source line、PTT 時間與影片時間如何區分；
- 如何證明一篇文章真的完整；
- 為什麼「現在讀得到」不能等同「歷史完整」；
- 為什麼 source data、canonical archive 與 public static projection 必須分層。

目前概念流程為：

    Collector source ─┐
                      ├─→ provenance-preserving Unified Archive
    Web recovery ─────┘
                               ↓
                     completeness / coverage
                               ↓
                     public historical projection
                               ↓
                       playback / timeline

### 1. 兩種來源不是互相取代

#### Collector / BBS source

Collector 保留 article identity、source line、source page、push type、author、content、PTT date/time 與 collection observation。

它接近原始 BBS chronology，也能保留 source-line evidence；但「Collector 有資料」不等於已證明完整。即使已觀測區間沒有中間 gap，也可能沒有證據證明文章尾端已完全取得。

因此 Collector coverage 可以是 verified_complete、partial、unknown 或 missing，而不是只用 true/false。

#### Web recovery source

Web recovery 使用公開 Web mirror 補歷史資料，並獨立保存 web_articles 與 web_pushes，而不是直接修改 Collector source tables。

這個隔離讓兩個來源可以先獨立 audit，再建立 canonical read model；recovery source 不會無痕蓋掉原始 evidence。

### 2. Web recovery 不能「抓到多少算多少」

Web importer 先取得網站宣告的推文總數，再展開完整推文。

正數推文文章要被視為完整，至少要求：

    declared_push_count
    ==
    parsed_push_count
    ==
    stored_push_count

而且樓層必須嚴格是：

    1, 2, 3, ... N

少一樓、重複一樓、實際數量超過 declared count、或無法完整展開，都 fail closed。

核心經驗是：

> 網頁看起來載入完成，不是完整性證據。

### 3. 零推文是特殊案例

如果得到 declared=0、parsed=0、stored=0，仍不能單靠這三個零宣稱文章真的完整且沒有推文。

同樣的結果也可能來自：

- 網頁載入失敗；
- parser 沒抓到；
- mirror 回應不完整；
- source 暫時異常。

因此只有另外存在 trusted verified-zero evidence 時，零推文文章才提升為 verified_complete；否則維持 unknown。

通用原則：

> Empty result is not completeness evidence.

### 4. Unified Archive 是可重建 read model

Unified Archive 不是單純把兩個 SQLite concatenate。

建置會：

1. 以 read-only / immutable 方式開啟來源；
2. 驗證來源 schema；
3. 記錄 source SHA-256；
4. 記錄 source file size；
5. 記錄 schema fingerprint 與 user version；
6. 匯入 article/push provenance；
7. 建立 canonical rows；
8. 記錄每個來源的 coverage；
9. 建立 completion manifest；
10. 在結束前再次驗證 source 未在建置途中改變。

目標是：

    build a reproducible read model from immutable source evidence

而不是：

    merge whatever is currently in two databases

### 5. Canonical source priority

目前 source priority 是：

    Collector = 30
    Web       = 10

當兩個來源可以對應到相同 canonical identity，且 Collector evidence 有效時，canonical selection 優先 Collector。

但 Web evidence 不會被刪除，而是保留在 provenance。

所以系統仍能回答：

- canonical 現在選哪個值；
- Collector 當時看到什麼；
- Web 當時看到什麼；
- 兩個來源是否衝突。

Priority 是目前 read-model policy，不代表宣稱 Web 永遠錯。

### 6. 為什麼不能 last-write-wins

如果 canonical winner 由「最後匯入的 row」決定：

- import order 會改變結果；
- rebuild 不再 deterministic；
- recovery source 可能意外覆蓋較強 evidence；
- 很難解釋 canonical row 為什麼如此。

目前測試會刻意交換 Collector → Web 與 Web → Collector 的 import order，確認 canonical outcome 不依賴順序。

### 7. 推文 identity：floor 與 source line 不同

若來源具有可信 canonical floor，identity 可以是 floor:N。

Collector 若尚無可信 floor，只能使用 collector-line:source_line。

兩者語意不同：

- floor 是文章內 canonical comment order；
- source_line 是 Collector 在來源證據中的 line identity。

不能因為數字接近就當作同一種 identifier。

### 8. 為什麼 author + content + minute 不是唯一 ID

系統可對 kind、author、content、ptt_date、ptt_time 建 content hash，用於 integrity / comparison。

但它不應取代 canonical floor identity。

同一使用者可以在同一分鐘連續發出相同內容。如果只使用 author + content + minute，兩個不同樓層可能被錯誤 dedupe。

### 9. Coverage state

目前 coverage state：

    verified_complete
    partial
    unknown
    missing

#### Web

正數文章：

    declared == parsed == stored
    AND floors == 1..N
    → verified_complete

零推文則需要另外的 verified-zero evidence。

否則維持 partial 或 unknown。

#### Collector

若已知 screen/source coverage 中間存在 gap，標示 partial。

若從開頭連續但沒有證據證明 tail 完整，仍維持 unknown。

所以：

> 沒觀察到 gap，不代表已證明完整。

### 10. Source conflict

若同一 floor：

    Collector content = A
    Web content       = B

目前 canonical selection 選 Collector，但 A 與 B 都保留在 provenance。

未來如果有證據顯示特定歷史時期 Web 更可靠，可以改成：

- time-dependent source trust；
- field-level priority；
- confidence scoring；
- explicit conflict review。

目前固定 priority 是可解釋 default，不宣稱為普遍最佳解。

### 11. Source manifest 與 immutability

每個來源會記錄：

- SHA-256；
- byte size；
- schema fingerprint；
- schema user version；
- article count；
- push count；
- completion status。

建置結束前再次檢查來源沒變，避免一份 archive 實際混合：

    first half from source version A
    second half from source version B

只有 required sources 的 completion manifest 都完整，archive reader 才接受結果。

### 12. Atomic build

Archive 先建立 staging output。

只有 source preflight、imports、unchanged-source verification、completion manifest 與 archive validation 全部通過，才形成 accepted output。

如果 Web source 損壞，即使 Collector 已匯入成功，也不能把半套 archive 當成完成品。

### 13. Historical static publication

瀏覽器不需要直接讀完整 Unified Archive。

公開層應該是 projection：

    Unified Archive
          ↓
    month/article selection
          ↓
    public schema
          ↓
    manifest / hashes
          ↓
    static assets
          ↓
    browser

好處：

- 不暴露 source/operational database；
- 只公開 UI 真正需要的欄位；
- 歷史月份可獨立發布；
- 大量唯讀 PTT 不必依賴 mutable DB query；
- public schema 可以與內部 schema 解耦。

### 14. PTT 時間與影片時間

歷史 PTT 常只有 MM/DD HH:MM，也就是 minute-level resolution。

播放器同步必須基於：

    push offset = push timestamp - verified video actual_start

而不是：

    push offset = push timestamp - page load time

如果同一分鐘需要穩定秒級排序，可以做 deterministic second allocation，但必須保留「估計值」語意，不能把它宣稱為 PTT 原始精確秒數。

完整 timeline 演算法會在 Chapter 07 / Chapter 15 詳述。

### 15. Live feed 和 historical archive 的 completeness 不同

Live PTT 優先低 latency；Historical PTT 優先 coverage + reproducibility。

latest-window / tail query 即使回報該 window 沒有更多頁，也不能推論「整篇歷史完整」。

完整 retained-history traversal 必須從明確 cursor origin 逐頁讀取。

### 16. 已確認失敗：Tail is not history

過去 independent review 發現，portable adapter 以 newest tail 初始化時會靜默漏掉較舊但仍 retained 的 pushes。

修正後：

    history mode:
    after_cursor = 0
    → sequential pages
    → commit cursor only after successful ingestion

而 explicit recent mode 才使用 tail，且 coverage 必須標為 recent-only。

核心經驗：

> No more rows in this query window，不代表 source history complete。

### 17. Cursor commit rule

歷史 cursor 只有在 page validated 且 rows successfully ingested 後才 commit。

如果先 advance cursor 再處理：

    fetch page
    → advance cursor
    → processing fails
    → retry starts after lost page

就可能造成永久資料洞。

所以 schema invalid、malformed page 或 ingest callback failure 都必須保留上一個 committed cursor。

### 18. history_gap 不等於可以忽略

即使從 cursor origin 走完整個 retained dataset，也不代表已重建原始 PTT 全歷史。

如果舊資料曾被 purge，history_gap 必須保留 incomplete-history warning。

因此：

    full walk of retained data
    !=
    complete original history

### 19. Web recovery 的 UI automation 踩雷

Web recovery 曾遇到「載入全部」按鈕事件送出，但應用沒有真的展開所有留言。

不能使用：

    click()
    → sleep()
    → assume complete

目前做法是：

- 觀察實際已展開 floor count；
- 與 declared count 比較；
- 必要時只做 bounded native DOM click retry；
- timeout 時回報 observed count 與按鈕狀態；
- observed count 大於 declared 也 fail。

Browser automation lesson：

> Successfully dispatching a UI event does not prove application state convergence.

### 20. URL contract 踩雷

曾經有 reader 依錯誤的 URL suffix 假設解析 Web mirror article，導致合法 historical URL 無法正確處理。

修正後 parser 接受 source 真正的 URL contract。

通用原則：

> 不要用「看起來像這個平台的 URL」取代 formal parser contract。

## Failed / risky approaches

### F-013 — Tail 當完整 history
Status: Failed / corrected.

### F-014 — Empty result 當 verified zero
Status: explicitly avoided.

### F-015 — Web UI click 成功就當完整載入
Status: Failed / hardened.

### F-016 — Import order 決定 canonical winner
Status: explicitly avoided.

### F-017 — Gap-free Collector coverage 就宣稱 complete
Status: explicitly avoided.

### F-018 — Minute timestamp 當原始精確秒
Status: explicitly avoided.

## Trade-offs

目前做法的代價：

- provenance retention 增加儲存；
- rebuildable archive 比 query 單一 mutable DB 複雜；
- source priority 需要治理；
- Web mirror 可能消失或改版；
- Collector source-line chronology 與 canonical floor 不天然等價；
- minute-resolution timestamps 帶來不可消除的同步不確定性；
- static publication 提高可重建性，但不是即時來源。

## Open questions

值得外部開發者挑戰的方向：

- fixed priority 是否應改成 confidence-based merge；
- 是否能公開合規的 Collector vs Web conflict statistics；
- 是否存在更可靠的秒級 historical timestamp source；
- 大型 historical PTT 是否適合 content-addressed object pool；
- field-level source authority 是否比 whole-source priority 更合理。

HoloDocchi 現在的核心原則是：保留 provenance，且不要把 unknown 包裝成 complete；但目前 merge policy 不被視為唯一正解。

---

## English

### Problem

PTT looks like “articles plus comments,” but a replayable historical system synchronized with video must distinguish:

- what a live Collector actually observed;
- whether historical coverage contains gaps;
- what a Web mirror recovered;
- how conflicts on the same floor are handled;
- how canonical floor, source line, PTT time and video time differ;
- how completeness is proven;
- why “readable now” is different from “historically complete”;
- why source data, canonical archive and public static projection remain separate.

The conceptual pipeline is:

    Collector source ─┐
                      ├─→ provenance-preserving Unified Archive
    Web recovery ─────┘
                               ↓
                     completeness / coverage
                               ↓
                     public historical projection
                               ↓
                       playback / timeline

### 1. The two sources are complementary

Collector preserves article identity, source lines/pages, push type, author, content, PTT date/time and collection observation.

Its chronology is close to original BBS evidence, but observed data is not automatically complete. Continuous observed screens do not necessarily prove a complete tail.

Web recovery is stored independently in web_articles and web_pushes instead of silently modifying Collector source tables.

This allows source comparison and audit before canonical selection.

### 2. Web recovery must prove completeness

For a positive-count article:

    declared_push_count
    ==
    parsed_push_count
    ==
    stored_push_count

and floors must be exactly 1 through N.

Missing floors, duplicates, counts beyond the declaration, or incomplete expansion are rejected.

Lesson:

> A page that looks finished is not completeness evidence.

### 3. Zero comments require separate evidence

declared=0, parsed=0 and stored=0 can also be caused by page or parser failure.

Therefore zero-comment content becomes verified_complete only with separate trusted verified-zero evidence. Otherwise it remains unknown.

> Empty result is not completeness evidence.

### 4. Unified Archive is a rebuildable read model

The archive opens sources read-only, validates schema, records source hashes/sizes/schema fingerprints, imports provenance, constructs canonical rows, records coverage and completion manifests, and rechecks source immutability before acceptance.

The goal is to build a reproducible read model from immutable evidence, not to concatenate two mutable databases.

### 5. Canonical source priority

Current priority:

    Collector = 30
    Web       = 10

Collector wins canonical selection when both sources map to the same identity and Collector evidence is valid.

Web evidence is still retained in provenance, so source disagreement remains inspectable.

### 6. Priority must not depend on import order

A last-write-wins merge makes rebuild output depend on import order.

Tests intentionally reverse Collector/Web import order and verify equivalent canonical results.

### 7. Push identity

Trusted canonical-floor sources can use floor:N.

Collector data without trusted floor capability may use collector-line:source_line.

A floor and a source line are different semantic identifiers and must not be conflated.

### 8. Content is not a unique identity

A hash of kind, author, content, date and minute is useful for integrity/comparison, not as a unique floor identity.

A user can post identical content multiple times in one minute, so author + content + minute can incorrectly collapse distinct pushes.

### 9. Coverage states

Coverage is represented as:

    verified_complete
    partial
    unknown
    missing

For Web, positive counts require declared==parsed==stored and floors 1..N. Zero comments require separate verified-zero evidence.

For Collector, a known gap means partial. Gap-free observed coverage without complete-tail evidence remains unknown.

### 10. Source conflicts

If Collector says A and Web says B for the same canonical floor, current policy selects Collector while retaining both observations.

This does not assert that Web is always wrong. Future designs could use time-dependent trust, field-level authority, confidence scoring or explicit conflict review.

### 11. Source manifests and immutability

Each source manifest records SHA-256, byte size, schema fingerprint, schema version, article count, push count and completion state.

Sources are rechecked before acceptance so one archive cannot silently combine two different source versions.

### 12. Atomic build

An archive begins as staging output.

Only successful source preflight, complete imports, source immutability checks, completion manifests and archive validation produce an accepted build.

A corrupt Web source prevents publishing a half-complete Collector-only archive.

### 13. Historical static publication

The public browser layer should consume a projection rather than the full operational archive:

    Unified Archive
          ↓
    month/article selection
          ↓
    public schema
          ↓
    manifest / hashes
          ↓
    static assets
          ↓
    browser

This decouples public schema from operational storage and allows independently publishable historical partitions.

### 14. PTT time versus video time

Historical PTT commonly provides minute-level timestamps.

Playback alignment uses:

    push offset = push timestamp - verified video actual_start

not page-load time.

If deterministic second allocation is needed for stable playback ordering within one minute, it must remain explicitly estimated rather than being presented as original PTT precision.

### 15. Live and historical completeness are different

Live feeds optimize latency; historical archives optimize coverage and reproducibility.

A newest-tail query cannot be treated as complete history merely because that selected window has no additional page.

### 16. Confirmed failure: tail is not history

An independent review found that newest-tail initialization omitted older retained pushes.

Corrected history mode walks from cursor origin sequentially and commits progress only after successful ingestion. Explicit recent mode remains recent-only.

### 17. Cursor commit rule

Advance the historical cursor only after page validation and successful ingestion.

Advancing first and failing processing can create a permanent gap.

### 18. history_gap remains meaningful

Walking all retained data does not prove complete original history if earlier data was purged.

Therefore:

    full walk of retained data
    !=
    complete original history

### 19. Web UI automation failure

A “load all” click can be dispatched without the application actually expanding every comment.

The importer therefore watches actual floor count, compares it with declared count, uses only bounded retry, and fails on timeout or impossible counts.

> Dispatching a UI event does not prove application-state convergence.

### 20. URL contract failure

A historical parser once assumed the wrong URL suffix pattern for the Web mirror.

The correction was to parse the source's actual URL contract rather than rely on a visual/platform assumption.

## Failed / risky approaches

- F-013 — Tail treated as complete history: Failed / corrected.
- F-014 — Empty result treated as verified zero: explicitly avoided.
- F-015 — Successful UI click treated as complete expansion: Failed / hardened.
- F-016 — Import order decides canonical winner: explicitly avoided.
- F-017 — Gap-free Collector coverage treated as complete: explicitly avoided.
- F-018 — Minute timestamp presented as original exact seconds: explicitly avoided.

## Trade-offs and open questions

Provenance retention increases storage and rebuild complexity. Source priority requires governance. Web mirrors can change. Source lines and floors are not inherently equivalent. Minute-resolution timestamps create irreducible uncertainty.

Possible improvements include confidence-based merges, conflict statistics, better timestamp evidence, content-addressed historical assets, and field-level source authority.

The current HoloDocchi principle is to retain provenance and never present uncertainty as completeness. The current merge policy is not claimed to be the only correct solution.

[回目錄 / Index](README.md)
