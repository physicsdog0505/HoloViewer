# 01 — 整體架構 / Architecture

## 繁體中文

### 問題與實作
直播狀態需要新鮮度，歷史目錄與已審核字幕則適合預先建立。公開程式將瀏覽器前端、動態讀取服務與不同靜態資料面分離。此為已核對原始碼的架構，不是即時部署驗收。

```text
Browser / HoloDocchi
  ├─ Live read service
  ├─ Historical video catalog
  ├─ PTT monthly archives
  ├─ Watchalong event data
  ├─ Per-video subtitle data
  └─ Daily digest data
```

### 資料責任與取捨
| 資料 | 更新及讀取方式 | 設計理由 |
|---|---|---|
| 直播狀態 | 動態讀取 | 狀態會變，需區分未知與已確認 |
| 歷史影片 | 靜態目錄 | 避免每次瀏覽重算 |
| PTT 歷史 | 月份索引及靜態資料 | 可分區更新 |
| Watchalong | 事件定義 | 對齊資訊與一般目錄分開 |
| 字幕 | 影片級資料與可用性索引 | 修正獨立，避免複製影片 metadata |
| 日報 | 月份資料與日期相關剪輯 | 編輯週期獨立 |

靜態化不是免費的：仍需要建置、傳輸、儲存與快取管理；跨資料面亦可能出現版本不一致。動態與靜態混合是目前選擇，不代表永遠優於單一後端。

### 公開資料流程
來源 → 正規化 → 驗證 → 建立候選資料 → 發布 → 瀏覽器讀取。每種資料的權威來源與驗證規則不同，後續章節分別定義。

### 可重現範例（概念）
假設影片 A 在一月開播、二月完成翻譯。字幕應由影片 ID 連結原影片，月份可用性索引使用影片目錄中的一月，而非二月翻譯完成日。字幕索引不需要再次保存標題、縮圖及成員名稱。這是已實作的字幕發布契約；例子為合成資料。

### 曾放棄的做法
**已確認的早期方案：** Streamlit 煙霧預覽只提供佔位介面，沒有實作完整公開觀看體驗；目前公開前端已採獨立 HTML/CSS/JavaScript 靜態資產。這證明產品架構已演進，不證明 Streamlit 本身無法支援此產品或曾經效能測試失敗。
**已拒絕的資料契約：** 舊字幕月份路徑未明確表達 VOD 月份，現行驗證拒絕舊路徑，採影片月份索引。尚無足夠證據量化舊契約造成的實際錯誤數。

### 開放問題與驗證
可比較單一 API、混合式與純靜態架構的讀取延遲、快取命中率、資料新鮮度、更新成本及跨版本一致性。目前沒有完整的對照基準，不能聲稱目前方案是效能最佳解。後續應用合成資料測試缺漏、錯誤版本和獨立更新。

## English

### Problem and implementation
Live state needs freshness, whereas historical catalogs and reviewed subtitles are suitable for prebuilding. Public source separates the browser frontend, dynamic read service and independent static data surfaces. This architecture is verified in source, not an acceptance test of the live deployment.

```text
Browser / HoloDocchi
  ├─ Live read service
  ├─ Historical video catalog
  ├─ PTT monthly archives
  ├─ Watchalong event data
  ├─ Per-video subtitle data
  └─ Daily digest data
```

### Data responsibilities and trade-offs
| Data | Update and access | Rationale |
|---|---|---|
| Live state | Dynamic reads | State changes; distinguish unknown from confirmed |
| Historical videos | Static catalog | Avoid recomputation on each browse |
| Historical PTT | Monthly indexes and static data | Update partitions independently |
| Watchalong | Event definitions | Keep alignment separate from general catalog |
| Subtitles | Per-video assets and availability indexes | Independent corrections; avoid duplicate metadata |
| Digest | Monthly data and date-specific related clips | Independent editorial cadence |

Static publication is not free: building, transfer, storage and caching still have costs; versions can diverge across surfaces. The hybrid approach is the current choice, not necessarily superior to a single backend in all circumstances.

### Public data flow
Source → normalization → validation → candidate construction → publication → browser consumption. Each data type has its own authority and validation rules, to be defined in later chapters.

### Reproducible example (conceptual)
Suppose video A streamed in January and its translation finished in February. Its subtitles should link to the video ID, and the monthly availability index should use January from the video catalog rather than the February translation date. The subtitle index need not repeat the title, thumbnail or member name. This is an implemented subtitle publication contract; the example uses synthetic data.

### Abandoned approaches
**Confirmed early approach:** the Streamlit smoke preview provided placeholders rather than the full public viewing experience; the current public frontend uses independent HTML/CSS/JavaScript static assets. This demonstrates architectural evolution, not that Streamlit is incapable of supporting the product or failed performance testing.
**Rejected data contract:** the former subtitle month path did not explicitly express VOD month; current validation rejects that path in favor of a video-month index. Evidence is insufficient to quantify actual errors caused by the former contract.

### Open questions and validation
Compare monolithic API, hybrid and fully static designs on read latency, cache hit rate, freshness, update cost and cross-version consistency. No complete comparative benchmark is established here; the current design cannot be claimed to be optimal. Future tests should use synthetic data to exercise missing records, incompatible versions and independent updates.

[回目錄 / Index](README.md)
