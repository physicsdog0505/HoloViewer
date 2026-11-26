# 00 — 專案介紹 / Project scope

## 繁體中文

### 問題與目標
觀看直播常需在影片、不同成員視角、討論串、歷史列表及翻譯間切換。HoloDocchi 將這些資訊整合為單一觀看介面，但不取代原始影片平台。影片播放主要透過 YouTube 官方嵌入播放器；第三方內容不因被索引而改變權利歸屬。

### 設計需求
- 即時資訊與歷史資料分別處理，避免將過期狀態當作即時事實。
- 多視角播放必須區分各影片的相對時間與共同事件時間。
- 討論與字幕須有可解釋的時間對應；未知對應不能冒充已確認。
- 資料修正應盡量不牽連不相關功能。
- 公開方法應可由其他人自行實作，不依賴 HoloDocchi 的營運資源。

### 已實作範圍與證據
公開網站程式包含今日直播、歷史瀏覽、自訂觀看、多人連動、同時視聽、PTT 閱讀、字幕與日報介面。證據為公開原始碼；本章未獨立檢查各功能即時部署狀態或資料覆蓋率。

### 限制與開放問題
第三方影片可能不可嵌入，來源資料可能延遲或缺漏。整合介面不能保證來源永久可用。歡迎提出更好的時間模型、資料架構、無障礙設計及資料品質方法。

## English

### Problem and goals
Watching streams often requires switching between videos, member perspectives, discussion threads, historical listings and translations. HoloDocchi integrates these into one viewing interface without replacing the original video platform. Playback primarily uses YouTube's official embedded player; indexing third-party content does not change its ownership.

### Design requirements
- Handle live information separately from historical data so stale state is not presented as current fact.
- Distinguish each video's relative time from the shared event time when synchronizing perspectives.
- Provide explainable time mappings for discussions and subtitles; do not present unknown mappings as verified.
- Correct data without unnecessarily affecting unrelated features.
- Make public methods independently implementable without relying on HoloDocchi's operational resources.

### Implemented scope and evidence
Public website source includes interfaces for today's streams, history, custom viewing, collaborations, watchalong, PTT, subtitles and daily digest. This is source-code evidence; this chapter does not independently verify live deployment status or coverage of each feature.

### Limitations and open questions
Third-party videos may be unavailable for embedding, and source data may be delayed or incomplete. An integrated interface cannot guarantee permanent source availability. Improvements to time models, data architecture, accessibility and data quality are welcome.

[回目錄 / Index](README.md)
