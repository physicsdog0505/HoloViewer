# 12 — 原文字幕與 Transcript / Source transcripts

## 繁體中文

### 角色

翻譯品質的第一個前提不是模型，而是「翻譯到底綁在哪一份原文」。

HoloDocchi 將 transcript identity 與 translation identity 分離。翻譯不能只靠 video_id 判斷是否可重用。

Canonical source artifact 至少綁定：

    video_id
    transcript_id
    content_hash
    source_language
    ordered segments
    start_ms / end_ms
    source_text

### Source export

Transcript Corpus 先選出 canonical normalized record，再輸出 deterministic source artifact。

export 只複製 corpus 已確立的 identity、hash、時間與原文；它不重新抓字幕、不呼叫 AI、不翻譯，也不建立第二套 transcript identity。

因此：

    Transcript Corpus = transcript authority
    Translation source export = immutable translation input projection

### 為什麼 translation 不能只綁 video_id

同一支影片可能：

- 重新取得更完整字幕；
- provider 改變；
- normalization 改版；
- segment 內容修正。

如果 translation 只看 video_id，就可能把舊 transcript 的翻譯錯配到新 transcript。

目前 job identity 因此綁：

    video_id + transcript_id + content_hash

existing output 若 identity/hash 不同，必須 conflict，而不是 overwrite。

### Segment invariants

Translation input 要保留：

- segment ID；
- segment order；
- start/end timestamp；
- Japanese source text。

翻譯層不得默默 merge、delete、reorder、invent segment。

這讓 deterministic validator 可以檢查：

    VIDEO_ID_MATCH
    TRANSCRIPT_ID_MATCH
    CONTENT_HASH_MATCH
    SEGMENT_COUNT_MATCH
    IDS_MATCH
    ORDER_MATCH
    TIMESTAMPS_MATCH
    SOURCE_TEXT_PRESERVED

### Public caption first，不代表永遠有字幕

Public-caption acquisition 是一個 provider path，不是 guaranteed capability。

若某 VOD 沒有可取得的 Japanese captions，正確狀態是 provider unavailable / no caption，而不是：

- 產生空 transcript；
- 把錯誤當零段；
- 偷偷啟動未授權 ASR；
- 用其他影片字幕替代。

Acceptance runner 遇到 public captions unavailable 會停止；ASR fallback 是另一條需要獨立驗證的 provider route。

### Source acquisition 與翻譯分離

這個邊界的好處是：

    acquire once
    normalize once
    identify once
    translate many experiments

不同翻譯模型、prompt、review pipeline 都可以使用同一份 immutable source，比較才有意義。

### 已知失敗／風險

#### F-045 — 只用 video_id 當 translation cache key
Status: explicitly avoided.

風險：新 transcript 可能誤用舊翻譯。

修正：綁 transcript_id + content_hash。

#### F-046 — Existing source artifact 不同就直接覆寫
Status: explicitly avoided.

不同 identity/hash 必須 conflict；source artifact 不做 silent overwrite。

#### F-047 — Public captions unavailable 就當整個 transcript system failed
Status: explicitly avoided.

provider-specific failure 應保留，後續 ASR 是獨立 fallback 設計。

#### F-048 — 來源字幕取得失敗後自動弱化 credential boundary
Status: explicitly rejected.

不能因 yt-dlp/provider 失敗就開始使用 cookies、login state 或 secrets。

### 限制

- public captions 品質取決於 YouTube/provider；
- canonical normalization 可能仍保留 ASR/caption segmentation 缺陷；
- timestamp correctness 與 semantic sentence boundary 是不同問題；
- source segment preservation 有利於 reproducibility，但未必是最佳中文閱讀 segmentation。

最後一點會直接影響 Chapter 14。

---

## English

Translation quality begins with binding the translation to the correct source transcript.

HoloDocchi separates transcript identity from translation identity. A translation is not reusable merely because the video ID matches.

The canonical source artifact binds video ID, transcript ID, content hash, language, ordered segment IDs, timestamps and source text.

The Transcript Corpus remains transcript authority; the exported source JSON is an immutable translation-input projection and does not refetch captions, call AI or define a second transcript identity.

Translation jobs are bound to:

    video_id + transcript_id + content_hash

so a changed transcript cannot silently reuse an old translation.

The translation layer preserves IDs, order, timestamps and Japanese source exactly, enabling deterministic validation of identity, counts, ordering, timing and source-text integrity.

Public captions are a provider path rather than a guaranteed capability. Missing Japanese captions remain a provider-specific unavailable state; the system does not silently emit an empty transcript, substitute another source or start an unauthorized ASR path.

This separation allows one normalized transcript to support many translation experiments using the same source evidence.

### Failed / risky approaches

- F-045 — video ID alone as translation cache identity: explicitly avoided.
- F-046 — silently overwriting a conflicting source artifact: explicitly avoided.
- F-047 — treating missing public captions as failure of the whole transcript architecture: explicitly avoided.
- F-048 — weakening credential/security boundaries after provider failure: explicitly rejected.

### Limitations

Public-caption quality remains provider-dependent. Timestamp validity and semantic sentence boundaries are separate problems. Preserving original segments improves reproducibility but does not prove those segments are optimal units for Chinese subtitle reading.

[回目錄 / Index](README.md)
