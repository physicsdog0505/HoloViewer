# 13 — AI 翻譯管線 / AI translation pipeline

## 繁體中文

### 先說結論：Whole-VOD 不等於 one-shot

HoloDocchi 所謂「整支影片翻譯」目前的工程語意是：

    bounded batches
    + checkpoints
    + complete-VOD acceptance gate

不是把整支幾小時直播一次丟進模型。

這個 distinction 是翻譯文件最重要的一點。

### 已驗證／曾使用的 quality-v2 形狀

品質路線的基本階段：

    Initial translation
        ↓
    QE review
        ↓
    selective post-edit when flagged
        ↓
    immutable TranslationArtifact

一個 acceptance 設定曾使用：

    initial batch = 20 segments
    QE batch = 20 segments
    neighboring QE context = 2 segments each side
    pacing = 4.2 seconds

另一方面，playback-centered progressive route 使用更保守的：

    normally 10 cues / batch

並保留 batch-local checkpoint。

這兩種 route 不能混成「Gemini 最穩定就是 N 段」。

它們的目的與 context 不同。

### Progressive 路線

Progressive mode 的設計目標是讓播放位置附近字幕先 ready。

scheduler priority：

1. current playhead batch；
2. near future；
3. recent past；
4. distant future；
5. old past。

預設 active window：

    forward = 120 s
    backward = 30 s

每次 runtime step 最多送一個 translation batch。

這條路線保留：
- existing completed batches；
- bounded retry；
- checkpoint；
- seek 後重新排序 pending work。

### 但 progressive route 曾被產品上隱藏

這不是因為它完全不能工作。

實際紀錄是：Roboco 測試中 progressive Gemini v2 能產生中文，但**主觀品質不足**。

研究當時推測，問題可能部分來自：

    10-cue batch
    +
    no cross-batch context

而不一定只是模型本身。

這個推測當時沒有被當成已證明根因。

後來產品決策是：

> 隱藏可見的 progressive translation UI，保留 dormant implementation；只顯示完整、review 通過的 whole-record artifact。

### Larger batch 的研究與保守決策

研究曾提出 50 / 100 cue batch 作為 controlled experiment。

但後續產品決策明確要求：

    keep conservative existing batch sizes
    do not raise to 50/100 yet

原因是 prior larger QE batches 有 failure risk，且尚未有 controlled benchmark 證明更大 batch 在完整率、品質與 request pressure 上更好。

因此 50/100 cues 是：

    experiment candidate

不是：

    proven stable production setting

### Gemini Web workspace 路線

後來另一條 production-oriented translation execution 使用 dedicated Gemini Web workspace。

核心不是「丟檔案給 Gemini 就完成」，而是 deterministic controller 先建立：

- immutable source；
- versioned rules；
- manifest；
- expected output quartet；
- active queue authority；
- attempt namespace。

Gemini Web 只處理明確 queue entry。

完整輸出必須有四份：

    translation.json
    zh-TW.srt
    translation-review.json
    receipt.json

### Partial attempt 為什麼不可原地修

Gemini scheduled run 如果 target attempt 已經有 1–3 份 output：

    partial immutable attempt

不能：
- overwrite；
- repair；
- rename；
- 補上剩餘檔案。

它必須留給 deterministic readback 判定，retry 使用新的 attempt namespace。

原因是原地修補會讓人無法知道：
- 哪些 bytes 屬於第一次生成；
- 哪些是 retry；
- review/receipt 是否真的對應同一 output。

### Active queue 與 historical throughput

scheduled Gemini 不自行掃完整 corpus。

它只讀 compact active queue，依 deterministic ordering 取第一個 pending job，每次最多處理一支。

terminal jobs 不留在 active queue。

這避免：
- scheduled slot 一直重新掃完成項目；
- AI 自己決定 P0/P1；
- month boundary queue 跑乾。

### Translation rules

Versioned rules 要求：
- natural Taiwan Traditional Chinese；
- 不發明 source 沒有的資訊；
- 保留 names/nicknames/community terminology；
- 不因語氣有趣就亂加 w/草/笑死；
- uncertain terminology 採 conservative rendering 並 flag review。

### Acceptance gate

結構合法不代表可接受。

狀態區分：

    completed_unvalidated
    accepted
    failed
    conflict

只有 deterministic validator PASS 且 review status=pass 才能 accepted。

needs_review 或 failed，即使 JSON structurally valid，也不能進 accepted。

---

### 已知失敗／風險

#### F-049 — Whole-VOD = one giant model request
Status: explicitly rejected.

整支影片是 acceptance scope，不是單次 prompt scope。

#### F-050 — Progressive 10-cue route 被當成最終品質
Status: product-level failure / hidden.

它能生成字幕，但實際 Roboco 試用的主觀品質不足，因此 visible progressive UX 被隱藏。

#### F-051 — 認定品質不足一定是模型問題
Status: unverified hypothesis avoided.

當時研究指出 batch/context policy 也可能是原因，未證明前不能把 root cause 全推給模型。

#### F-052 — 50/100 cues 當已驗證穩定值
Status: explicitly rejected.

它們是 benchmark candidate；較大 QE batch 有 failure risk 紀錄。

#### F-053 — Partial attempt 原地修補
Status: explicitly forbidden.

retry 使用新 immutable attempt。

#### F-054 — AI 自己掃 corpus / 決定 queue
Status: explicitly forbidden.

local deterministic controller 是 queue authority。

#### F-055 — Structurally valid output 自動 accepted
Status: explicitly avoided.

review must pass。

---

## English

### Whole-VOD does not mean one-shot

In HoloDocchi, whole-VOD translation means bounded batches, checkpoints and a complete-VOD acceptance gate. It does not mean sending a multi-hour stream to the model in one request.

The quality-v2 route uses initial translation, QE review and selective post-edit.

One full-VOD acceptance configuration used 20-segment initial and QE batches, two neighboring context segments per side and 4.2-second request pacing.

A separate playback-centered progressive route normally used 10 cues per batch and batch-local checkpoints. These settings serve different goals and must not be presented as one universal stable Gemini batch size.

Progressive scheduling prioritizes the current playhead, near future and recent past, with default forward/backward windows of 120/30 seconds.

The route worked technically, but a Roboco trial produced subjectively insufficient translation quality. Research hypothesized that 10-cue batches with no cross-batch context may contribute, but this was not established as the sole cause.

The product later hid visible progressive controls and preferred complete, reviewed whole-record artifacts.

50/100-cue batches were proposed as controlled experiments, not accepted stable settings. A later decision kept conservative existing sizes because larger QE batches carried failure risk.

Gemini Web execution is surrounded by a deterministic workspace: immutable source, versioned rules, manifest, expected output quartet, active queue and immutable attempt namespace.

A partial attempt with only some expected files is not repaired in place. A retry uses a new attempt namespace.

Only deterministic validation plus review status=pass can move an output to accepted.

### Failed / risky approaches

- F-049 — whole-VOD interpreted as one giant request: explicitly rejected.
- F-050 — progressive 10-cue translation treated as final product quality: product-level failure; visible UX hidden.
- F-051 — blaming the model alone for quality problems: unverified and avoided.
- F-052 — 50/100 cues presented as proven stable values: explicitly rejected.
- F-053 — repairing partial model attempts in place: forbidden.
- F-054 — letting the AI scan the corpus or choose queue order: forbidden.
- F-055 — accepting structurally valid output without quality review: explicitly avoided.

[回目錄 / Index](README.md)
