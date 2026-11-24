# 02 — 資料工程 / Data engineering

## 繁體中文

### 問題

HoloDocchi 同時處理即時直播狀態、歷史影片、PTT、字幕、Watchalong 與 Daily Digest。這些資料不只更新頻率不同，錯誤型態也不同：可能是來源延遲、重複資料、缺漏、schema 漂移、發布時漏檔、索引與實體不一致，或同一筆資料被歸到錯誤月份。

因此資料工程的目標不只是「把資料抓回來」，而是讓公開資料具有：

- 可辨識的 schema；
- 可檢查的完整性；
- 明確的資料權威；
- 可重建性；
- 可獨立驗證的 publication candidate；
- 發生缺漏或不一致時能 fail closed，而不是靜默猜測。

### 目前可從公開程式碼確認的資料流程

不同資料面的來源不同，但公開 publication tooling 大致遵循：

```text
source authority
  ↓
normalization / projection
  ↓
schema validation
  ↓
candidate tree
  ↓
manifest + inventory
  ↓
byte/hash verification
  ↓
public artifact
```

這不是所有資料面的唯一實作細節，而是從 YouTube static、VOD subtitle、Daily Digest 等公開程式碼可觀察到的共同模式。

### 1. Canonical JSON 與 deterministic output

多個 builder 會將 JSON 以固定排序、固定 separators 產生 canonical bytes，再計算 SHA-256。

這個做法的目的不是密碼學安全本身，而是讓：

- 相同輸入可產生相同輸出；
- manifest 可以指向 exact bytes；
- publication candidate 可以做 tree-level 比對；
- 無意義的 JSON key 順序差異不會造成不必要的版本漂移。

例如公開的 YouTube static builder 與 Daily Digest normalizer 都使用 canonical JSON 與 SHA-256。

### 2. Manifest 不只列檔名，也描述預期內容

YouTube static 的 manifest entry 會保存至少：

- logical path；
- bytes；
- sha256；
- count 或 video_count；
- channel identity / month identity 等必要欄位。

驗證時不是只檢查「檔案存在」，而是同時確認：

```text
path exists
AND byte length matches
AND SHA-256 matches
AND schema matches
AND declared count matches payload
AND declared inventory matches actual inventory
```

如果其中任何一項不一致，驗證會直接失敗。

### 3. Inventory equality

一個常見問題是 manifest 看起來正確，但目錄裡多出舊檔或少了一個檔。

公開 verifier 會比較：

```text
declared inventory == actual inventory
```

而不是只驗證 manifest 裡列出的檔案。

這可以避免「舊版本殘留檔仍被 CDN 或使用者讀到」這類錯誤。

### 4. Cross-index coverage

在 YouTube current release builder 中，月份檔中的 video IDs 必須被 channel indexes 覆蓋。

也就是：

```text
month video IDs ⊆ indexed video IDs
```

缺少 coverage 時 candidate 會被拒絕。

這類檢查的目的，是避免主資料存在，但搜尋／索引層無法找到。

### 5. Authority 不重複

VOD 字幕是一個很重要的例子。

字幕 publication 不重新複製影片標題、縮圖、成員名稱等 metadata。字幕層只維護：

- video identity；
- subtitle payload；
- translation provenance identity；
- availability index。

影片月份與影片 metadata 仍由既有 VOD catalog 決定。

因此：

```text
Video catalog = video metadata authority
Subtitle asset = subtitle authority
```

而不是建立兩份可以互相漂移的影片資料庫。

### 6. 月份是資料語意，不是 publication 日期

假設：

- VOD 發生於 2026-01；
- 翻譯於 2026-02 完成。

字幕的月份索引仍應是 **2026-01**，因為那是影片自己的月份。

這避免「翻譯時間」污染「內容時間」。

現行 subtitle validator 會從 VOD catalog lookup 影片月份，並拒絕舊的模糊月份 contract。

### 7. Fail closed

公開 validation code 多處採 fail-closed。

例如：

- schema 不符 → fail；
- hash 不符 → fail；
- bytes 不符 → fail；
- duplicate identity → fail；
- 同一影片出現在兩個 VOD 月份 → fail；
- subtitle cue 數量不一致 → fail；
- COMPLETE translation cue 是空字串 → fail；
- public candidate 混入不應公開的 receipt / Watchalong tree → fail。

這和「盡量顯示資料」是兩種不同哲學。

對 publication candidate，我們寧願拒絕不一致的資料，也不希望自動猜測正確值。

### 8. Public prose normalization

Daily Digest normalizer 不是直接把模型或來源輸出原封不動發布。

公開程式碼可確認它會：

- 清理多餘 whitespace；
- 驗證 schema 與允許的 enum；
- 對標題、摘要與 editorial prose 套用長度 contract；
- 從公開 prose 中移除已知裸 video IDs 等內部識別痕跡；
- 將來源格式投影成 public schema。

這代表「生成結果」與「公開 artifact」是兩個不同層級。

### 9. Partitioning

大型歷史資料不一定適合放成一個巨大 JSON。

目前可看到的 partition strategy 包括：

- YouTube：月份 + channel index；
- PTT：月份；
- VOD subtitles：per-video + global availability + by-VOD-month index；
- Daily Digest：月份 + date-specific related clips；
- Watchalong：manifest + per-event。

這些 partition 不只是效能優化，也讓驗證與修正可以局部進行。

---

### 可重現的最小驗證模型

其他專案可以從一個非常簡單的 manifest 開始：

```json
{
  "schema_version": 1,
  "files": [
    {
      "path": "data/2026-01.json",
      "bytes": 12345,
      "sha256": "...",
      "count": 100
    }
  ]
}
```

Reader / verifier 至少檢查：

1. path 安全，不允許 `..`；
2. file exists；
3. byte length；
4. SHA-256；
5. payload schema；
6. payload row count；
7. actual directory inventory 是否多檔或少檔。

如果還有 secondary indexes，再加上 cross-index coverage。

這種方法不依賴 HoloDocchi，可以直接移植到其他 static-first 專案。

---

### 曾經失敗或被拒絕的做法

#### F-002 — 模糊的 subtitle month contract
**狀態：Deprecated / Rejected**

舊格式使用月份 manifest，但沒有把「這個月份究竟代表影片月份還是翻譯／發布月份」做成足夠明確的 contract。

目前 validator 明確拒絕舊路徑，月份由 VOD catalog 的影片身份推導。

**已確認：** contract 已被新格式替代。  
**未確認：** 尚未有完整統計可以量化舊格式曾導致多少實際錯誤。

#### Pending — 重複寫入與 idempotency
過去工程紀錄顯示曾出現資料寫入放大與重複提交風險，但這屬於動態 ingestion / publisher 路線。公開 handbook 尚未完成 source-level forensic review，因此目前只列為待查證，不在本章宣稱根因。

---

### Trade-offs

目前資料工程方法也有成本：

- manifest 與 hash 需要額外 build time；
- static data 更新不如單一 mutable database 即時；
- partition 太細會增加檔案與 request 數；
- partition 太粗則會增加更新 blast radius；
- 多個 publication surfaces 可能產生跨版本不一致；
- deterministic build 只能保證相同輸入產出一致，不能保證來源本身正確。

因此 manifest / hash 是 integrity mechanism，不是 truth oracle。

---

### 驗證與未解問題

後續應補充量測：

- build time 與資料量關係；
- 單一大檔 vs month partition 的 request / cache trade-off；
- publication surface 間版本 skew 的實際頻率；
- recovery 時重新 build 全量 vs partial rebuild 的成本；
- source correctness 與 publication integrity 應如何分層驗證。

如果有人認為 relational DB、object storage index、content-addressable store、Parquet/Arrow 或其他架構更適合，歡迎提出可比較的 benchmark 與 migration model。

---

## English

### Problem

HoloDocchi handles live stream state, historical videos, PTT data, subtitles, Watchalong definitions and Daily Digest content. These datasets not only update at different rates; they fail differently: source delay, duplicates, missing records, schema drift, incomplete publication, index/payload mismatch, or incorrect temporal partitioning.

The data-engineering goal is therefore not merely to “fetch data,” but to make public data:

- schema-identifiable;
- integrity-checkable;
- explicit about authority;
- rebuildable;
- independently verifiable before publication;
- fail-closed when inconsistent instead of silently guessed.

### Data flow confirmed in public source

Different surfaces have different source authorities, but public publication tooling shows a recurring pattern:

```text
source authority
  ↓
normalization / projection
  ↓
schema validation
  ↓
candidate tree
  ↓
manifest + inventory
  ↓
byte/hash verification
  ↓
public artifact
```

This is not the only implementation detail of every dataset. It is the common pattern observable in public YouTube static, VOD subtitle, Daily Digest and related tooling.

### 1. Canonical JSON and deterministic output

Several builders serialize JSON with deterministic key ordering and separators before computing SHA-256.

The purpose is not cryptographic security by itself, but to ensure:

- identical inputs can yield identical bytes;
- manifests can identify exact payloads;
- candidate trees can be compared;
- meaningless JSON key-order changes do not create unnecessary artifact drift.

Public YouTube static tooling and Daily Digest normalization both demonstrate this pattern.

### 2. Manifests describe expected content, not merely filenames

A YouTube static manifest entry records information such as:

- logical path;
- bytes;
- sha256;
- count or video_count;
- channel/month identity where required.

Validation checks more than existence:

```text
path exists
AND byte length matches
AND SHA-256 matches
AND schema matches
AND declared count matches payload
AND declared inventory matches actual inventory
```

Any inconsistency rejects the candidate.

### 3. Inventory equality

A manifest may be correct while an old extra file remains in the directory or a declared file is missing.

The public verifier compares:

```text
declared inventory == actual inventory
```

rather than validating only listed files.

This helps prevent stale artifacts from remaining accessible through a CDN or static origin.

### 4. Cross-index coverage

For the current YouTube release builder, video IDs in the month payload must be represented by channel indexes:

```text
month video IDs ⊆ indexed video IDs
```

Missing coverage rejects the candidate.

The goal is to avoid a state where primary data exists but discovery/index layers cannot find it.

### 5. Avoid duplicate authorities

VOD subtitles are an important example.

The subtitle publication layer does not duplicate titles, thumbnails, member names or other catalog metadata. It maintains:

- video identity;
- subtitle payload;
- translation provenance identity;
- availability indexes.

Video month and general video metadata remain authoritative in the existing VOD catalog.

Therefore:

```text
Video catalog = video metadata authority
Subtitle asset = subtitle authority
```

instead of maintaining two drifting video databases.

### 6. Month is domain semantics, not publication time

Suppose:

- a VOD happened in January 2026;
- its translation completed in February 2026.

The subtitle month index should still be **January 2026**, because that is the video's month.

This prevents translation time from contaminating content time.

The current subtitle validator derives video month from the VOD catalog and rejects the older ambiguous month contract.

### 7. Fail closed

Public validation code uses fail-closed behavior in many places.

Examples:

- schema mismatch → fail;
- hash mismatch → fail;
- byte-count mismatch → fail;
- duplicate identity → fail;
- one video appearing in multiple VOD months → fail;
- subtitle cue-count mismatch → fail;
- an empty cue in a COMPLETE translation → fail;
- private receipt or Watchalong trees exposed in a subtitle candidate → fail.

This is different from “display as much as possible.”

For publication candidates, HoloDocchi prefers rejecting inconsistent data rather than inventing a correction.

### 8. Public prose normalization

The Daily Digest normalizer does not publish model/source output verbatim.

Public source confirms steps including:

- whitespace cleanup;
- schema and enum validation;
- length contracts for titles, summaries and editorial prose;
- removal of known raw video IDs from public prose;
- projection from source format into a public schema.

“Generated output” and “public artifact” are therefore distinct layers.

### 9. Partitioning

Large historical datasets are not necessarily suitable as one giant JSON file.

Visible partition strategies include:

- YouTube: month + channel index;
- PTT: month;
- VOD subtitles: per-video + global availability + by-VOD-month index;
- Daily Digest: month + date-specific related clips;
- Watchalong: manifest + per-event asset.

Partitioning is not only a performance optimization. It also makes validation and corrections more local.

---

### Minimal reproducible validation model

Another project can start with a simple manifest:

```json
{
  "schema_version": 1,
  "files": [
    {
      "path": "data/2026-01.json",
      "bytes": 12345,
      "sha256": "...",
      "count": 100
    }
  ]
}
```

A verifier should at least check:

1. path safety, rejecting `..`;
2. file existence;
3. byte length;
4. SHA-256;
5. payload schema;
6. payload row count;
7. whether actual directory inventory contains extras or omissions.

If secondary indexes exist, add cross-index coverage checks.

This method is not HoloDocchi-specific and can be reused in other static-first projects.

---

### Failed or rejected approaches

#### F-002 — Ambiguous subtitle month contract
**Status: Deprecated / Rejected**

The former month-manifest format did not make it sufficiently explicit whether the month represented VOD time or translation/publication time.

The current validator rejects the old path and derives month identity from the VOD catalog.

**Confirmed:** the contract has been replaced.  
**Unverified:** there is not yet a complete measurement of how many real errors the former contract caused.

#### Pending — Duplicate writes and idempotency
Past engineering records indicate write amplification / duplicate-submission risks in a dynamic ingestion/publisher path. The handbook has not yet completed a source-level forensic review, so this remains pending evidence review rather than a claimed root cause.

---

### Trade-offs

The current approach also has costs:

- manifests and hashes add build time;
- static updates are less immediate than a single mutable database;
- overly fine partitioning increases file/request count;
- overly coarse partitioning increases update blast radius;
- multiple publication surfaces can drift in version;
- deterministic builds prove identical transformation of identical inputs, not that the source itself is correct.

A manifest/hash system is an integrity mechanism, not a truth oracle.

---

### Validation and open questions

Future documentation should measure:

- build time versus dataset size;
- single large file versus monthly partition request/cache trade-offs;
- real frequency of version skew between publication surfaces;
- cost of full rebuild versus partial rebuild during recovery;
- how source correctness and publication integrity should be validated as separate layers.

If a relational database, object-storage index, content-addressable store, Parquet/Arrow or another architecture is superior for a comparable workload, benchmarks and migration proposals are welcome.

[回目錄 / Index](README.md)
