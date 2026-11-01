# Holodocchi Gemini Daily Digest Input v2

SCHEMA_VERSION=holodocchi.gemini.daily_digest.v2
TARGET_DAY: {{TARGET_DAY}}
TIMEZONE: Asia/Taipei

EXPECTED_OUTPUT_FILES:
- {{TARGET_DAY}}-holodocchi-gemini-digest-v2-validation.json
- {{TARGET_DAY}}-holodocchi-gemini-digest-v2-validation.md

## 任務

請逐一讀取下方列出的全部 YouTube 直播連結，製作 {{TARGET_DAY}}（Asia/Taipei）的 Hololive / HOLOSTARS 直播日報。

請直接使用 Gemini 環境中可取得的 YouTube 影片資訊、影片內容與逐字稿能力進行分析。本檔中的 channel、title、時間等 metadata 只用來確認直播身份與清單完整性；直播內容仍應由實際讀取各 YouTube 連結後判斷。

不要因為單一影片無法取得 transcript 就推測內容。不要因 transcript 不存在、會員限定、語言判斷或摘要品質而自行刪除清單項目。

## 讀取狀態

逐一將直播分類為：

1. 成功取得足以核實直播內容的資料
2. 只能取得標題／基本 metadata
3. 無法存取／無法驗證內容

無法驗證者必須明確標示「內容無法驗證」，不得只依標題杜撰直播細節。

## 輸出語言

全部使用自然的台灣繁體中文。人名、作品名、遊戲名與官方專有名詞可保留原文。避免使用「配信／告知／情報」等一般日文句法，也不要自行添加沒有內容證據的情緒性評價。

## 編輯責任與版面責任

先研究完當日全部直播，再做跨視角整併與全天相對判斷。

Gemini 負責：
- semantic editorial order；
- bounded public copy；
- supporting ordered video_ids；
- non-authoritative `presentation_hint` / `recommended_role`。

Gemini **不負責**：
- authoritative frontend layout；
- 任意 hero/secondary placement；
- CSS/template 實作；
- browser-side scoring。

`presentation_hint` 只能是 `compact | rail | lead` 的建議。後續 Holodocchi normalizer 會驗證並寫入 authoritative `overview_layout`。

## 今日概覽 overview

`overview.public_summary`：
- 3–4 個 semantic beats / 段落；
- 總長建議 260–520 CJK；
- 第一段建立當日 center of gravity；
- 不要把所有事件塞成一個巨型段落。

`overview.highlights`：
- 3–5 筆，依 editorial order；
- 每筆必須是 object，不得再輸出單純長字串；
- 欄位：
  - `title`：完整編輯標題；
  - `short_title`：卡片用短標題，target 12–32 CJK，hard 8–42；
  - `summary`：45–110 CJK；
  - `video_ids`：支持該 highlight 的 ordered evidence，至少 1 筆；
  - `recommended_role`：`lead_candidate | secondary_candidate | normal`。

overview shape：

```json
{
  "public_summary": "...",
  "presentation_hint": "compact | rail | lead",
  "highlights": [
    {
      "title": "...",
      "short_title": "...",
      "summary": "...",
      "video_ids": ["..."],
      "recommended_role": "lead_candidate | secondary_candidate | normal"
    }
  ]
}
```

## Stories

每筆 story 必須保留：
- 完整 `title`；
- optional bounded `short_title`；
- 完整 `public_summary`；
- ordered `video_ids`；
- `editorial_signals`；
- optional non-authoritative `presentation_hint`。

Detailed story 的完整 title 不得為了卡片寬度而破壞或截短。

## editorial_signals

對每筆 streams 與需要的 story 維持：

- `importance`: 1–5 integer
- `novelty`: 1–5 integer
- `announcement_strength`: 0–5 integer
- `community_relevance`: 1–5 integer
- `analysis_confidence`: 0.0–1.0
- `recommended_role`: `lead_candidate | secondary_candidate | normal`
- `rationale`: 可由內容證據支持的簡潔理由

`analysis_confidence` 是來源覆蓋與分析完整性的信心，不是真實機率。Production join key 維持 `video_id`。

## Announcements / categories

Announcements 保留完整 title + 完整 summary，不為版面做破壞性截斷。

Categories 維持 stable `key`、human `label`、ordered `video_ids`。

## JSON contract

JSON 頂層維持：

- `meta`
- `audit_stats`
- `overview`
- `stories`
- `streams`
- `announcements`
- `categories`
- `unverified`

另外在 `meta` 中明確寫入：

```json
{
  "schema_version": "holodocchi.gemini.daily_digest.v2"
}
```

不要自行輸出 authoritative `overview_layout`；這個欄位由 normalizer 決定。

## 最終檔案

完成後，將相同事實基礎的 JSON + MD 存回讀取本 input 的同一 Google Drive 資料夾，使用本檔指定的 validation output filename。

不要覆蓋原始 input，也不要覆蓋既有 v1 digest。若任一 sibling 檔案無法寫回，請明確回報。

## Stream List

{{STREAM_LIST}}
