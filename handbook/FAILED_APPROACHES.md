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

| F-026 | Generic game title means same collab / 同遊戲標題即視為同場連動 | Risk explicitly avoided / 已明確避免 | [08](08-collab-identification.md) |
| F-027 | Similar start time means same event / 相近開播時間即視為同一事件 | Risk explicitly avoided / 已明確避免 | [08](08-collab-identification.md) |
| F-028 | Candidate group enables timeline sync / 候選群組直接啟用時間同步 | Forbidden by design / 設計上禁止 | [08](08-collab-identification.md) |
| F-029 | Ambiguous candidate chooses first match / 模糊候選直接選第一組 | Risk explicitly avoided / 已明確避免 | [08](08-collab-identification.md) |
| F-030 | Watchalong source time equals host time / 同時視聽 source time 直接等於 host time | Risk explicitly avoided / 已明確避免 | [09](09-watchalong.md) |
| F-031 | Advance immediately when source ends / 片源結束立即跳下一段 | Risk explicitly avoided / 已明確避免 | [09](09-watchalong.md) |
| F-032 | Static Watchalong subtitles follow source timeline / 靜態同時視聽字幕跟 source 時間軸 | Rejected contract / 已拒絕 | [09](09-watchalong.md) |
| F-033 | Ignore transcript-translation provenance / 不驗證原文與翻譯 provenance | Risk explicitly avoided / 已明確避免 | [09](09-watchalong.md) |
| F-034 | Seek on every sync-loop tick / 每次同步迴圈都 seek | Risk explicitly avoided / 已明確避免 | [09](09-watchalong.md) |
| F-035 | URL checkpoint treated as media truth / URL checkpoint 當播放器真實時間 | Parked / 已暫停 | [09](09-watchalong.md) |

| F-036 | Second polling loop for concurrent viewers / 為同接新增第二條 polling | Risk explicitly avoided / 已明確避免 | [10](10-concurrent-viewers.md) |
| F-037 | Unchunked large D1 CASE update / D1 大型 CASE update 未切批 | Failed / corrected | [10](10-concurrent-viewers.md) |
| F-038 | Concurrent viewers as lifecycle authority / 同接作為 lifecycle authority | Risk explicitly avoided / 已明確避免 | [10](10-concurrent-viewers.md) |
| F-039 | Null treated as zero / 缺值視為零 | Risk explicitly avoided / 已明確避免 | [10](10-concurrent-viewers.md) |
| F-040 | Current snapshot treated as historical metric / 即時 snapshot 當歷史統計 | Intentionally not implemented / 刻意未實作 | [10](10-concurrent-viewers.md) |
| F-041 | Viewer count as homepage popularity truth / 同接當首頁人氣真相 | Risk explicitly avoided / 已明確避免 | [11](11-highlights.md) |
| F-042 | Generic keywords without guards / 泛用關鍵字無 guard | Partially mitigated / 部分緩解 | [11](11-highlights.md) |
| F-043 | Merge highlight events from title/date guesses / 以標題日期猜測合併事件 | Risk explicitly avoided / 已明確避免 | [11](11-highlights.md) |
| F-044 | Client re-ranks finalized digest / Client 重排已完成日報 | Forbidden by contract / 契約禁止 | [11](11-highlights.md) |

| F-045 | Video ID alone as translation identity / 只用 video_id 當翻譯 identity | Risk explicitly avoided / 已明確避免 | [12](12-source-transcripts.md) |
| F-046 | Conflicting source artifact overwritten / 衝突原文 artifact 被覆寫 | Risk explicitly avoided / 已明確避免 | [12](12-source-transcripts.md) |
| F-047 | Missing public captions means whole transcript system failed / 無公開字幕即視為整個 transcript 失敗 | Risk explicitly avoided / 已明確避免 | [12](12-source-transcripts.md) |
| F-048 | Provider failure weakens credential boundary / provider 失敗後弱化憑證邊界 | Rejected / 已拒絕 | [12](12-source-transcripts.md) |
| F-049 | Whole-VOD means one giant request / 整支影片等於單次超大請求 | Rejected / 已拒絕 | [13](13-ai-translation.md) |
| F-050 | Progressive 10-cue route treated as final quality / 10-cue progressive 當最終品質 | Product-level failure / 產品層失敗 | [13](13-ai-translation.md) |
| F-051 | Blame model alone for quality gap / 品質差全部歸因模型 | Unverified hypothesis avoided / 避免未驗證假說 | [13](13-ai-translation.md) |
| F-052 | 50/100 cues treated as proven stable / 50/100 cues 當已驗證穩定值 | Rejected / 已拒絕 | [13](13-ai-translation.md) |
| F-053 | Repair partial model attempt in place / 原地修補 partial attempt | Forbidden / 禁止 | [13](13-ai-translation.md) |
| F-054 | AI scans corpus and chooses queue / AI 自行掃 corpus 與排隊 | Forbidden / 禁止 | [13](13-ai-translation.md) |
| F-055 | Structurally valid output auto-accepted / 結構正確就自動 accepted | Risk explicitly avoided / 已明確避免 | [13](13-ai-translation.md) |
| F-056 | Later batch failure discards prior progress / 後段失敗丟掉前面進度 | Design flaw corrected / 已修正 | [14](14-translation-quality.md) |
| F-057 | Initial checkpoint implies whole-pipeline resumability / initial checkpoint 被誤當完整可續跑 | Confirmed limitation / 已確認限制 | [14](14-translation-quality.md) |
| F-058 | Blind retry after unknown provider outcome / provider outcome 不明時盲重試 | Blocked / 已阻擋 | [14](14-translation-quality.md) |
| F-059 | Shift mapping after response-count mismatch / 少回段落後位移對應 | Forbidden / 禁止 | [14](14-translation-quality.md) |
| F-060 | QE becomes broad stylistic rewrite / QE 變成全篇風格重寫 | Guarded against / 已防範 | [14](14-translation-quality.md) |
| F-061 | 10 cues treated as quality-optimal / 10 cues 被當品質最佳值 | Unproven / 未證實 | [14](14-translation-quality.md) |
| F-062 | Larger batch automatically improves quality / 大 batch 一定更好 | Unproven / risky / 未證實且有風險 | [14](14-translation-quality.md) |
| F-063 | Punctuation grouping equals true sentence boundary / 標點分組當真實句界 | Rejected / 已拒絕 | [14](14-translation-quality.md) |
| F-064 | Proportional retiming equals semantic alignment / 比例 retiming 當語意對齊證據 | Rejected / 已拒絕 | [14](14-translation-quality.md) |
| F-065 | Third-party fansub as ground truth / 第三方字幕當 ground truth | Rejected / 已拒絕 | [14](14-translation-quality.md) |
| F-066 | Same model ID means fair A/B / 同模型 ID 就算公平 A/B | Rejected / 已拒絕 | [14](14-translation-quality.md) |
| F-067 | Reviewer/post-editor treated as free quality / reviewer/post-edit 當免費品質提升 | Rejected / 已拒絕 | [14](14-translation-quality.md) |
| F-068 | Retranslate when artifact exists but UI fails / artifact 存在但 UI 看不到就重翻 | Rejected / 已拒絕 | [14](14-translation-quality.md) |
