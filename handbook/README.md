# HoloDocchi Technical Handbook / 技術手冊

[HoloDocchi](https://holodocchi.com) · [Project README](../README.md)

## Purpose / 目的

公開可重現的工程方法、設計取捨、失敗實驗與開放問題，讓其他開發者能沿用、驗證或提出更好的解法。中文與英文必須具有相同資訊量。只描述公開產品與可移植的技術方法，不披露維運環境、帳號、憑證或內部服務位置。

Document reproducible engineering methods, design trade-offs, failed experiments and open questions so others can reuse, verify or improve them. Chinese and English must have equivalent information. Describe only the public product and portable technical methods, not operational environments, accounts, credentials or internal service locations.

## Evidence labels / 證據標記

- **Production / 正式採用:** verified deployment evidence / 有正式部署證據。
- **Implemented / 已實作:** verified source code, not necessarily deployed / 已核對原始碼，不代表已部署。
- **Validated / 已驗證:** recorded experiment with stated conditions / 有條件與結果的實驗紀錄。
- **Experimental / 實驗中:** not established as stable / 尚未確立穩定性。
- **Deprecated / 已淘汰:** documented replacement or retirement / 有替換或退役紀錄。
- **Failed / 失敗:** observed failure under stated conditions / 特定條件下有失敗證據。
- **Unverified / 未確認:** insufficient evidence / 證據不足。
- **Proposal / 建議:** alternative not yet evaluated / 尚未評估的替代方案。

## Chapter map / 章節總覽

| ID | 繁體中文 | English | Status |
|---|---|---|---|
| 00 | 專案介紹 | [Project scope](00-project.md) | Draft |
| 01 | 整體架構 | [Architecture](01-architecture.md) | Draft |
| 02 | 資料工程 | [Data engineering](02-data-engineering.md) | Draft |
| 03 | 直播資訊 | [Live discovery](03-live-discovery.md) | Draft |
| 04 | 歷史直播 | [Historical streams](04-historical-streams.md) | Draft |
| 05 | PTT 資料系統 | PTT data | Planned |
| 06 | 多視角播放器 | Multi-view player | Planned |
| 07 | 共同時間軸 | Master timeline | Planned |
| 08 | 多人連動識別 | Collaboration identification | Planned |
| 09 | 同時視聽 | Watchalong | Planned |
| 10 | 同接數據 | Concurrent viewers | Planned |
| 11 | 精選與熱門內容 | Highlights | Planned |
| 12 | 原文字幕 | Source transcripts | Planned |
| 13 | AI 翻譯 | AI translation | Planned |
| 14 | 翻譯品質工程 | Translation quality | Planned |
| 15 | 字幕播放 | Subtitle rendering | Planned |
| 16 | Docchi News | Daily digest | Planned |
| 17 | 搜尋與名稱辨識 | Search and aliases | Planned |
| 18 | 前端設計 | Frontend design | Planned |
| 19 | 靜態資料架構 | Static publication | Planned |
| 20 | 資料完整性 | Data integrity | Planned |
| 21 | 測試與驗證 | Testing | Planned |
| 22 | 限制與技術債 | Limitations | Planned |
| 23 | 開源與貢獻 | Open source and contributions | Planned |

[失敗紀錄 / Failed approaches](FAILED_APPROACHES.md) · [架構決策 / Architecture decisions](ARCHITECTURE_DECISIONS.md) · [安全檢查 Gate / Security review gate](SECURITY_REVIEW_GATE.md)

## Chapter acceptance / 章節驗收

每章應交代問題、需求、輸入輸出、處理流程、演算法、實際參數及適用條件、可重現範例、例外處理、設計理由、失敗歷史、根因與假說、驗證方法、限制和替代方案。不適用或未知的欄位需說明。翻譯 Web 與 API 的參數不得混用；不得把研究設定當成正式採用或通用穩定值。

Each chapter should cover the problem, requirements, inputs and outputs, pipeline, algorithm, measured parameters and applicability, reproducible examples, edge cases, rationale, failures, confirmed causes versus hypotheses, validation, limitations and alternatives. Explain unknown or inapplicable fields. Web and API translation settings must be distinguished; research settings must not be presented as production settings or universally stable values.


## Security gate / 安全 Gate

每完成一章或一批公開文件，必須另外通過 [Documentation Security Review Gate](SECURITY_REVIEW_GATE.md)，再進入下一批。技術正確性通過不等於安全性通過。

Every completed public documentation chapter or batch must separately pass the [Documentation Security Review Gate](SECURITY_REVIEW_GATE.md) before the next batch. Technical correctness does not imply security acceptance.
