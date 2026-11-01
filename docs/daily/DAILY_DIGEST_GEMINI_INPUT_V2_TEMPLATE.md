# Holodocchi Gemini Daily Digest Input v2

SCHEMA_VERSION=holodocchi.gemini.daily_digest.v2
TARGET_DAY: {{TARGET_DAY}}
TIMEZONE: Asia/Taipei

EXPECTED_OUTPUT_FILES:
- {{TARGET_DAY}}-holodocchi-gemini-digest-v2-validation.json
- {{TARGET_DAY}}-holodocchi-gemini-digest-v2-validation.md

## 任務

請逐一讀取下方 Stream List 列出的全部 YouTube 直播連結，製作 {{TARGET_DAY}}（Asia/Taipei）的 Hololive / HOLOSTARS 直播日報。

Stream List 是「當日直播 universe / identity」的權威清單。請直接使用 Gemini 環境中可取得的 YouTube 影片資訊、影片內容與逐字稿能力研究直播內容；本檔的 channel、title、時間等 metadata 只用來確認身份與完整性，不得用標題推測未讀到的內容。

請先完成全部直播的讀取狀態判定與全天研究，再做跨視角整併、重要性比較與日報撰寫。不要依 Stream List 順序逐支拼接成日報。

本輪不要使用 Holodocchi 本機 Daily Summary 作為主要內容來源；該資料會在產出後另外做 coverage / quality QA。Gemini 的內容判斷仍以它實際讀到的 YouTube / transcript 證據為準。

## 讀取狀態與完整性

每一筆 Stream List 都必須在 JSON 的 `streams` 中出現一次，不得靜默遺漏。依實際讀取結果標記：

- `verified_content`：取得足以核實直播內容的資料；
- `metadata_only`：只能取得標題／基本 metadata；
- `unverified`：無法存取／無法驗證內容。

無法驗證者不得只依標題杜撰摘要、topics、story 或 announcement。請同時放入 `unverified` 清單並說明原因。

`audit_stats.total_streams` 必須等於 Stream List 筆數，且 verified + metadata_only + unverified 必須完整覆蓋全部輸入。

## 輸出語言與品質

全部使用自然的台灣繁體中文。人名、作品名、遊戲名與官方專有名詞可保留原文。

避免：
- 「配信／告知／情報」等一般日文句法；
- 沒有內容證據的「精彩、溫馨、圓滿、感人、爆笑」等評價；
- 把時間軸逐項重寫成冗長流水帳；
- 為了卡片版面犧牲事實精度；
- 同一事件在 overview、stories、announcements 中用互相矛盾的數字、日期或名稱。

日期、數字、人名、作品名、活動名與公告內容要以來源為準；不確定時降低 `analysis_confidence`，不要補猜。

## 編輯責任與版面責任

Gemini 負責：
- 全天研究與跨視角整併；
- semantic editorial order；
- bounded public copy；
- supporting ordered `video_ids`；
- semantic `editorial_signals`；
- non-authoritative `presentation_hint` / `recommended_role`。

Gemini **不負責**：
- authoritative `overview_layout`；
- 任意 hero / secondary placement；
- CSS / frontend template；
- browser-side scoring。

`presentation_hint` 只能是 `compact | rail | lead` 的建議。後續 Holodocchi normalizer 會驗證並決定 authoritative `overview_layout`。

## 今日概覽 overview

`overview.public_summary`：
- 3–4 個 semantic beats / 段落；
- 總長建議 260–520 CJK characters；
- 用空行或等價段落分隔保留 3–4 個 beats；
- 第一段建立當日 center of gravity；
- 後續段落分別覆蓋其他主要跨頻道 / 企劃群；
- 不要寫成一個塞滿所有事件的巨型段落。

`overview.highlights`：
- 3–5 筆，依 editorial order；
- 每筆必須是 object，不得輸出單純字串；
- 每筆必須保留支持判斷的 ordered `video_ids`。

每筆欄位：
- `title`：完整編輯標題；
- `short_title`：卡片用短標題，target 12–32 CJK，hard 8–42；
- `summary`：45–110 CJK；
- `video_ids`：至少 1 筆、只能引用 Stream List 內 video_id；
- `recommended_role`：`lead_candidate | secondary_candidate | normal`。

不要用 short_title 塞入多個獨立事件；需要較長說明時放進 summary 或 detailed story。

## Stories

Stories 是跨直播／跨視角後的主要 editorial units，不是每支直播一筆。

每筆 story：
- `id`：當日內唯一且穩定；
- `rank`：1 起算的 editorial order；
- `title`：完整 detailed story 標題，禁止為卡片寬度破壞性截短；
- `short_title`：optional overview/navigation 用短標題；
- `editorial_summary`：主要 detailed-reader 主文。請把你已研究到、對讀者有價值的跨直播資訊完整整併進來，target 約 320–760 CJK characters，通常 2–5 個 semantic beats；事件本身簡單時可更短；
- `public_summary`：optional 較短版本／migration fallback，不應取代 `editorial_summary` 的資訊深度；
- `video_ids`：ordered supporting evidence，至少 1 筆；
- `member_names`：相關成員；
- `sub_events`：需要時才拆分，必須是 parent story 的子集合；
- `editorial_signals`；
- `presentation_hint`：optional、non-authoritative。

`editorial_summary` 應優先保留跨 POV 的具體內容、結果、公告、人物關係與值得閱讀的細節；不要因為前端卡片尺寸而把已研究到的資訊壓成兩三句。也不要把每支 stream summary 原封不動串接，應該做真正的 editorial synthesis。

不同 POV 若描述同一事件，應合併為同一 story / sub-event；不要用多篇重複故事灌數量。

## editorial_signals

對所有可驗證的 stream，以及需要 editorial ranking 的 story / announcement，輸出：

- `importance`: 1–5 integer
- `novelty`: 1–5 integer
- `announcement_strength`: 0–5 integer
- `community_relevance`: 1–5 integer
- `analysis_confidence`: 0.0–1.0
- `recommended_role`: `lead_candidate | secondary_candidate | normal`
- `rationale`: 簡潔且可由內容證據支持的理由

`analysis_confidence` 表示來源覆蓋與分析完整性，不是真實機率。不要把 viewer count 當成唯一 importance 判準。

## Announcements

只收錄直播中有來源支持、值得日報追蹤的公告，例如新直播／合作、演唱會、新歌／專輯、周邊、活動、會員、工商或明確未來日期。

每筆保留：
- `id`
- `rank`
- `type`
- 完整 `title`
- 完整 `summary`
- `event_date_text`（若來源有）
- ordered `video_ids`
- `member_names`
- `editorial_signals`

不要為版面對 announcement title / summary 做破壞性截斷。

## Categories

Categories 是瀏覽分組，不是另一套 story ranking。每筆使用：
- stable `key`
- human-readable `label`
- ordered `video_ids`

同一 video 可以出現在合理的多個 category，但不要建立只有措辭不同、內容高度重複的分類。

## JSON contract

JSON 頂層必須且只使用這些主要 semantic sections：

- `meta`
- `audit_stats`
- `overview`
- `stories`
- `streams`
- `announcements`
- `categories`
- `unverified`

`meta` 至少包含：

```json
{
  "schema_version": "holodocchi.gemini.daily_digest.v2",
  "target_day": "{{TARGET_DAY}}",
  "timezone": "Asia/Taipei",
  "input_file_name": "{{TARGET_DAY}}-holodocchi-gemini-input-v2-validation-20261101.md",
  "generated_at": "<ISO-8601 timestamp with offset>"
}
```

不要自行輸出 authoritative `overview_layout`。

### streams contract

每一筆 Stream List 對應一筆 `streams`，使用原本的 `input_index` 與 `video_id`，並保留：
- `input_index`
- `video_id`
- `verification_status`
- `summary`（無法驗證時為 null）
- `topics`（無法驗證時為 []）
- `story_ids`
- `announcement_ids`
- `editorial_signals`（無法驗證時可為 null）

不得捏造 Stream List 以外的 video_id 作為 evidence。

## JSON / Markdown 一致性

JSON 是 machine-readable authority；Markdown 是同一事實基礎的人類可讀日報。

Markdown 可以採自然編輯版面，不必逐欄位翻印 JSON，但以下不得與 JSON 衝突：
- stream coverage 數量；
- overview 的主要敘事；
- story / announcement 的日期、數字與事實；
- unverified 清單。

## 最終檔案

完成後，將相同事實基礎的 JSON + Markdown 存回讀取本 input 的同一 Google Drive 資料夾，使用本檔指定的 validation output filename。

不要覆蓋原始 input，也不要覆蓋既有 v1 digest。若任一 sibling 檔案無法寫回，請明確回報。

## Stream List

{{STREAM_LIST}}
