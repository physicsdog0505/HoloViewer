# 14 — 翻譯品質工程與失敗紀錄 / Translation quality engineering and failure history

## 繁體中文

### 為什麼需要獨立一章

翻譯 pipeline 最大風險不是「模型回傳 error」而已。

更危險的是：

- 回傳看似成功但少段；
- segment 對錯行；
- context 不足造成語意錯；
- reviewer 重寫過頭；
- post-edit 中途失敗；
- API outcome 不明時盲目 retry；
- checkpoint 只存一部分 stage；
- 中文 timing 看似平順但 punchline 提前曝光；
- sentence reconstruction 其實切錯句；
- A/B 比較不是同一 source span。

因此 quality engineering 必須同時驗證 structure、meaning、context、timing、recovery 與 provenance。

---

### 1. Long transcript 必須可續跑

早期 resilient translation work 的直接目標就是：

> 後面 batch 失敗時，不要丟掉前面已成功的翻譯。

因此：
- completed batch 保留；
- failed batch bounded retry；
- partial/resume state explicit；
- response count mismatch fail；
- ordering 不可 shift。

這代表「後面一批失敗 → 整支重跑」本身就是應避免的設計。

### 2. Initial checkpoint 不等於完整 resumability

曾有 whole-record quality-v2 路線：

    initial translation = resumable

但：

    QE / post-edit = not independently resumable

這被明確列為 unsafe long-running whole-VOD UI 的 blocker。

如果 initial 已完成、QE 跑到一半發生 quota/error，而重新執行會重送已完成 provider stage，就可能：
- 浪費額度；
- 產生不同 output；
- provenance 變混亂。

因此 later design 要求 per-stage receipt / checkpoint。

### 3. Unknown provider outcome 最危險

遇到：
- timeout；
- 5xx；
- 429；
- connection loss；

最麻煩的不是「確定沒送成功」，而是：

> request 可能已經到 provider，但 client 不知道結果。

B forensic design 因此把 unknown provider outcome 視為：

    BLOCKED_UNKNOWN_OUTCOME

而不是自動 retry。

需要先對 receipt / ledger / checkpoint 做 reconciliation。

這避免同一段被多次計費或產生多份互相衝突的 translation。

### 4. Response schema 完整不代表語意正確

deterministic validator 能保證：
- segment count；
- IDs；
- order；
- timestamps；
- source text；
- target non-empty。

但它不能證明：
- 意義沒有反轉；
- joke/punchline 時機正確；
- 人名術語自然；
- 語氣沒有被過度改寫。

因此還需要 structured QE / human acceptance。

### 5. QE 也可能傷害品質

Quality-v2 acceptance 特別要求：

> QE 不應造成 widespread stylistic rewriting。

selective post-edit 的目的就是：

    only edit flagged issues

而不是 reviewer 看完整份後「順手全部重寫得更像自己」。

否則 QE 會失去可追蹤性，甚至讓原本正確字幕變差。

### 6. 10-cue context limitation

progressive route 的 10-cue batch 很適合低延遲與低 request scope，但 cross-batch context 較弱。

研究曾比較其他 open-source subtitle translators，發現它們常使用：
- synopsis；
- glossary；
- previous translated lines；
- 50/100+ bounded context。

這支持「context policy 值得測試」，但不是證明 HoloDocchi 的品質問題必然由 batch size 造成。

### 7. Sentence reconstruction 不是 ground truth

B prototype 曾嘗試先把原始 JA cues 重建為較完整句子，再翻譯。

使用：
- punctuation；
- gap；
- max duration。

但文件明確指出：

> punctuation grouping is a candidate segmentation only.

尤其 ASR 可能沒有 punctuation。

因此 uncertain boundary 必須 flag review，不能宣稱 heuristic 已找到真正日文句界。

### 8. Chinese-specific retiming 的風險

把完整中文句子重新分配到原始 sentence time window，可以改善中文閱讀節奏。

但 target-side proportional retiming 不是 force alignment。

已知風險：

- 結論可能太早顯示；
- punchline 提前曝光；
- 語意 anchor 不一定跟字數比例一致。

因此「時間都落在 source span 內」只能證明 structural timing safety，不能證明 semantic timing perfect。

### 9. A/B/C comparison 必須同 source span

Quality Lab 明確要求 A、B、C 都指回相同 original Japanese source span。

因為 fansub clip 可能：
- 剪輯；
- 改 timing；
- 少句；
- 合句。

不能直接拿時間戳相同的畫面就當成相同 source evidence。

第三方字幕也只是 reference，不是 ground truth。

### 10. Same-model A/B 仍可能不公平

即使 A/B 用同一 model ID：
- prompt 不同；
- context 不同；
- pipeline stages 不同；
- A 有 initial + QE + post-edit；
- B 可能 sentence-level multi-stage。

所以 benchmark 必須比較完整 token / request / stage cost，不能只看 model 名稱。

### 11. Selective reviewed B 的 call amplification

B reviewed pipeline 每個 sentence 最多：

    initial
    review
    post-edit

也就是最多三次 provider call。

五個 sentence 最壞可到：

    15 Gemini API calls

所以「多一個 reviewer」不是免費品質提升。

任何 multi-stage pipeline 都要把：
- flagged rate；
- post-edit rate；
- request count；
- token cost；
- failure surface

一起量。

### 12. Failed batch 不能 shift mapping

translation batching 必須維持 one-output-per-input。

如果 provider 少回一條，不可以把後面的 translation 往前補齊。

response count mismatch 應整批 fail。

這是 subtitle translation 特別重要的 structural invariant。

---

## 失敗與限制清單

### F-056 — 後面 batch 失敗就丟掉前面全部進度
Status: design flaw explicitly corrected by resilient batching.

### F-057 — Initial stage 有 checkpoint 就宣稱 whole pipeline resumable
Status: confirmed limitation.

QE/post-edit 曾不是 independently resumable。

### F-058 — Timeout / 5xx / 429 後直接 blind retry
Status: explicitly blocked in forensic recovery design.

Unknown provider outcome 必須 reconciliation。

### F-059 — Provider 少回一段時把後面結果 shift 上來
Status: explicitly forbidden.

response-count mismatch fail closed。

### F-060 — QE 變成全篇 stylistic rewrite
Status: explicitly guarded against.

QE 應 selective，不應大面積改寫無問題字幕。

### F-061 — 10 cues 被視為品質最佳 batch size
Status: unproven.

它最初主要是 progressive latency/reliability trade-off。

### F-062 — 大 batch 一定品質更好
Status: unproven / risky.

50/100 cues 尚需 controlled benchmark，較大 QE batch 有 failure-risk 紀錄。

### F-063 — punctuation segmentation 當日文真正句界
Status: explicitly rejected.

uncertain boundaries require review。

### F-064 — proportional Chinese retiming 當 semantic alignment proof
Status: explicitly rejected.

它只是 deterministic timing heuristic。

### F-065 — 第三方 fansub 當 ground truth
Status: explicitly rejected.

只能作為 reference，且必須確認 source-span mapping。

### F-066 — Same model ID = fair A/B comparison
Status: explicitly rejected.

prompt/context/stage policy 也必須一致或完整記錄。

### F-067 — Reviewer / post-editor 是免費附加品質
Status: explicitly rejected.

multi-stage call/token/failure amplification 必須計算。

### F-068 — 翻譯完成但 UI 看不到就重翻
Status: explicitly rejected by forensic playbook.

先 debug presentation / artifact read path，不重新呼叫 provider。

---

## 如何記錄未來失敗

每次 translation experiment 應至少保存：

- source transcript identity/hash；
- provider/model；
- route（Web / API / local experiment）；
- batch segment count；
- input chars/tokens；
- context policy；
- prompt/rules revision；
- stage；
- request attempt；
- provider outcome；
- response completeness；
- checkpoint state；
- retry reason；
- human quality result；
- cost / tokens if available；
- final disposition：accepted / failed / abandoned / needs_review。

Web 與 API 的穩定參數必須分開統計。

不能因為 Gemini Web 某個長度穩定，就推論 API 同樣穩定；反之亦然。

---

## English

Translation quality engineering must cover more than provider errors. A response can look successful while omitting segments, misaligning outputs, losing cross-batch context, over-editing in QE, failing mid-post-edit, duplicating unknown-outcome requests, or exposing punchlines too early through naive retiming.

Long transcripts therefore preserve completed batches and retry only bounded failed work instead of restarting the full VOD.

A historical whole-record route had resumable initial translation but not independently resumable QE/post-edit. This was explicitly treated as a blocker for exposing a long-running whole-VOD UI safely.

Timeouts, 429/5xx and connection loss can leave provider outcome unknown. The forensic recovery design blocks automatic replay until receipt/ledger/checkpoint reconciliation.

Structural validation proves identity, counts, order, timestamps and nonempty targets, but not semantic fidelity. QE and human review remain separate.

QE itself is constrained against widespread stylistic rewriting; post-edit should be selective.

The 10-cue progressive route is a latency/reliability choice, not a proven quality-optimal batch size. Larger 50/100-cue experiments remain unproven and carry recorded failure risk.

Sentence reconstruction by punctuation/gap/duration is a heuristic, not ground truth. Chinese proportional retiming is also a deterministic heuristic rather than semantic force alignment.

Third-party fansubs are references, not automatic truth, and A/B/C comparisons must map to the same original Japanese source span.

Even identical model IDs do not make an A/B test fair when prompts, context and stages differ.

A reviewed sentence pipeline can require up to three provider stages per sentence; five sentences can therefore reach 15 calls in the worst case. Multi-stage quality gains must be measured against request, token and failure amplification.

### Failure index

- F-056 — losing all prior progress when a later batch fails: corrected by resilient batching.
- F-057 — treating initial-stage checkpointing as whole-pipeline resumability: confirmed limitation.
- F-058 — blind retry after unknown provider outcome: blocked.
- F-059 — shifting outputs after a response-count mismatch: forbidden.
- F-060 — QE becoming whole-document stylistic rewriting: guarded against.
- F-061 — treating 10 cues as the quality-optimal batch size: unproven.
- F-062 — assuming larger batches automatically improve quality: unproven/risky.
- F-063 — punctuation grouping treated as true Japanese sentence boundaries: rejected.
- F-064 — proportional Chinese retiming treated as semantic alignment proof: rejected.
- F-065 — third-party fansubs treated as ground truth: rejected.
- F-066 — same model ID treated as sufficient for fair A/B: rejected.
- F-067 — reviewer/post-editor treated as free quality improvements: rejected.
- F-068 — retranslating when the artifact exists but the UI cannot display it: rejected; debug the presentation/read path first.

Future experiments should record transcript identity, provider/model, Web/API route, batch size, chars/tokens, context policy, prompt/rules revision, stage, attempts, outcomes, completeness, checkpoint state, retry reason, human quality, cost and final disposition.

Web and API stability parameters must be tracked separately.

[回目錄 / Index](README.md)
