# Failed approaches / 失敗與淘汰紀錄

本索引只將有證據的失敗標為 Failed。被替換的設計不一定曾經失敗。未完成調查的項目不寫成結論。

Only evidence-backed failures are labeled Failed. Replaced designs are not necessarily failures. Uninvestigated items are not conclusions.

| ID | Topic / 主題 | Evidence status / 證據狀態 | Record / 紀錄 |
|---|---|---|---|
| F-001 | Early preview / 早期預覽 | Deprecated design / 舊設計 | [01](01-architecture.md) |
| F-002 | Subtitle month contract / 字幕月份契約 | Rejected legacy contract / 已拒絕舊契約 | [01](01-architecture.md) |
| F-003 | Long translation truncation / 長翻譯截斷 | Pending evidence review / 待查證 | Chapters 13–14 |
| F-004 | Translation batching and recovery / 翻譯分批與恢復 | Pending evidence review / 待查證 | Chapters 13–14 |
| F-005 | Duplicate writes / 重複寫入 | Pending evidence review / 待查證 | Chapters 02, 19 |
| F-006 | Historical source gaps / 歷史來源缺漏 | Pending evidence review / 待查證 | Chapter 05 |
| F-007 | Player lifecycle / 播放器生命週期 | Pending evidence review / 待查證 | Chapters 06–09 |
| F-008 | Stale live treated as live / 過期 live 狀態誤當即時 | Risk explicitly avoided / 已明確避免 | [03](03-live-discovery.md) |
| F-009 | Inferring live from schedule alone / 僅憑預定時間判定直播 | Risk explicitly avoided / 已明確避免 | [03](03-live-discovery.md) |
| F-010 | Search only visible daily page / 只搜尋單日可見頁 | Risk explicitly avoided / 已明確避免 | [04](04-historical-streams.md) |
| F-011 | Alias substring everywhere / 所有別名一律 substring | Risk explicitly avoided / 已明確避免 | [04](04-historical-streams.md) |
| F-012 | Pure calendar-month partitioning / 僅按曆月切分 | Edge case explicitly handled / 已處理邊界案例 | [04](04-historical-streams.md) |

## Record template / 紀錄格式

- Goal / 目標
- Method, version, input size, parameters / 方法、版本、輸入規模、參數
- Expected and observed results / 預期與實際結果
- Reproduction procedure and frequency / 重現步驟與頻率
- Confirmed cause versus hypothesis / 確認根因與假說
- Correction and measured outcome / 修正與量測結果
- Limitations and open questions / 限制與開放問題

歡迎提供反例與替代解法。/ Counterexamples and alternative solutions are welcome.

| F-013 | Tail treated as complete history / tail 當完整歷史 | Failed / corrected | [05](05-ptt-data.md) |
| F-014 | Empty result treated as verified zero / 空結果當完整零筆 | Risk explicitly avoided / 已明確避免 | [05](05-ptt-data.md) |
| F-015 | Web load-all click assumed complete / 點擊載入全部即視為完成 | Failed / hardened | [05](05-ptt-data.md) |
| F-016 | Import-order winner / 匯入順序決定 canonical | Risk explicitly avoided / 已明確避免 | [05](05-ptt-data.md) |
| F-017 | Gap-free means complete / 無 gap 即視為完整 | Risk explicitly avoided / 已明確避免 | [05](05-ptt-data.md) |
| F-018 | Minute timestamps treated as exact seconds / 分鐘時間當精確秒 | Risk explicitly avoided / 已明確避免 | [05](05-ptt-data.md) |

| F-019 | Moving iframe nodes for layout / 搬動 iframe 排版 | Risk explicitly avoided / 已明確避免 | [06](06-multi-view-player.md) |
| F-020 | Recursive linked-playback events / 連動播放事件遞迴 | Risk explicitly avoided / 已明確避免 | [06](06-multi-view-player.md) |
| F-021 | Equal source seconds treated as synchronized / 相同影片秒數視為已同步 | Risk explicitly avoided / 已明確避免 | [06](06-multi-view-player.md) |
| F-022 | Equal source time treated as equal event time / 相同 source time 當同一事件時間 | Risk explicitly avoided / 已明確避免 | [07](07-master-timeline.md) |
| F-023 | Playing through timeline gaps / gap 期間繼續上一段 | Risk explicitly avoided / 已明確避免 | [07](07-master-timeline.md) |
| F-024 | Seek on every small drift / 每個微小誤差都 seek | Risk explicitly avoided / 已明確避免 | [07](07-master-timeline.md) |
| F-025 | URL master time trusted as media clock / URL master time 當 player clock | Parked / 已暫停 | [07](07-master-timeline.md) |
