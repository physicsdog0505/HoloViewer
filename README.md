# HoloDocchi

> **繁體中文 / English**  
> HoloDocchi 是一個非官方 Hololive 粉絲專案，整合直播發現、歷史直播瀏覽、多視角觀看、同時視聽、PTT 專串閱讀、字幕與日報內容。  
> HoloDocchi is an unofficial Hololive fan project for livestream discovery, historical browsing, multi-view playback, watchalong experiences, PTT discussion timelines, subtitles, and daily digest content.

**網站 / Website:** https://holodocchi.com

> [!IMPORTANT]
> 本專案與 COVER Corp.、hololive production、YouTube、Google、PTT 均無隸屬、授權、背書或官方合作關係。  
> This project is not affiliated with, endorsed by, sponsored by, or operated by COVER Corp., hololive production, YouTube, Google, or PTT.

---

## 目錄 / Table of Contents

- [HoloDocchi 是什麼 / What HoloDocchi is](#holodocchi-是什麼--what-holodocchi-is)
- [目前功能 / Current features](#目前功能--current-features)
- [為什麼架構長這樣 / Why the architecture looks like this](#為什麼架構長這樣--why-the-architecture-looks-like-this)
- [資料怎麼處理 / How data is handled](#資料怎麼處理--how-data-is-handled)
- [資料來源與資料面 / Data sources and publication surfaces](#資料來源與資料面--data-sources-and-publication-surfaces)
- [隱私與安全邊界 / Privacy and security boundaries](#隱私與安全邊界--privacy-and-security-boundaries)
- [授權與第三方內容 / License and third-party content](#授權與第三方內容--license-and-third-party-content)
- [English full reference](#english-full-reference)

---

# HoloDocchi 是什麼 / What HoloDocchi is

HoloDocchi 的目標不是重新託管 Hololive 影片，而是把「觀看 Hololive 直播時常會同時需要的資訊」整理成一個瀏覽介面。

主要使用情境包括：

- 想快速知道現在有哪些直播
- 想查過去某一天或某位成員的直播
- 想同時觀看多個視角
- 想在 Hololive 同時視聽時同步另一個片源
- 想一邊看片、一邊看 PTT 專串或 YouTube Chat
- 想閱讀已整理的中文字幕
- 想快速回顧近期內容與相關剪輯

影片播放主要透過 YouTube 官方 iframe player。HoloDocchi 不把 YouTube 影片下載後重新託管。

---

# 目前功能 / Current features

## 1. 今日直播

首頁會整理正在直播、即將開始、狀態待更新與已結束的影片，讓使用者從「今天想看什麼」直接進入觀看。

## 2. 歷史直播

可依日期與成員查詢過去直播，也支援常用名稱、暱稱與多語別名搜尋。

## 3. 自訂觀看

可自由加入 YouTube 影片，建立單人或多人觀看版面，包含：

- 多視角排列
- 主視角切換
- 主要聲音選擇
- 連動播放／暫停
- 沉浸模式
- 多視角輪播
- 搭配討論時間軸

## 4. 多人連動

針對同一活動或合作直播整理多個視角，方便在同一介面中快速切換與比較。

## 5. 同時視聽 / Watchalong

Watchalong 不只是單純把兩個播放器放在一起，而是把：

```text
Hololive 主播時間軸
+
同步片源時間軸
+
對齊資訊
=
可同步觀看的同時視聽體驗
```

介面可支援：

- 主播畫面與同步片源
- 對齊目前位置
- 時間差微調
- 段點切換
- 並排／主畫面切換
- 連動播放
- 字幕與彈幕顯示
- PTT / YouTube Chat 閱讀

## 6. PTT 專串

可閱讀今日專串與已整理的歷史專串資料。

PTT 文章與推文屬於第三方／使用者產生內容。HoloDocchi 提供閱讀、索引與時間軸整理，不主張擁有原始文字。

## 7. 中文字幕

HoloDocchi 可為部分 VOD 提供中文字幕。

字幕資料與影片本身分離管理，避免字幕系統變成另一份重複的影片資料庫。

## 8. Docchi News / Daily Digest

將近期直播、重點內容與相關剪輯整理成較容易閱讀的日報形式。

## 9. 行程與月曆

包含直播月曆、生日、紀念日與歷史直播瀏覽，讓使用者能從時間維度回顧內容。

---

# 為什麼架構長這樣 / Why the architecture looks like this

HoloDocchi 並沒有把所有資料都塞進同一個後端。

這是刻意的。

直播狀態、歷史直播、PTT、字幕、Watchalong、Daily Digest 的更新頻率、資料量、驗證方式與回滾需求都不同。

如果全部綁在一起，會產生幾個問題：

- 一個服務故障可能影響整站
- 歷史資料與即時資料被迫共用同一生命週期
- 修改字幕時可能必須連同其他功能一起部署
- 大量唯讀歷史資料會增加動態服務成本
- 很難只回滾其中一種資料
- 很難清楚知道某一筆公開資料是怎麼產生的

因此 HoloDocchi 採用：

```text
前端
+
即時資料
+
可靜態化的歷史資料
+
獨立發布的字幕
+
獨立發布的 Watchalong 資料
+
獨立發布的 Daily Digest
```

這些資料面彼此分離，但在 HoloDocchi 網站上整合成單一使用體驗。

## Static-first

對於變動頻率低、可驗證、可重建的資料，HoloDocchi 優先使用靜態發布。

例如：

- 歷史直播資料
- 歷史 PTT
- Watchalong 定義
- VOD 字幕
- Daily Digest
- 搜尋別名

理由是：

- 更容易快取
- 更容易驗證
- 更容易重建
- 更容易獨立回滾
- 不需要每次開頁都重新查詢或重新計算
- 可降低單一後端的負擔

## Publication boundary

資料從來源到公開網站，原則上會經過：

```text
來源
→ 整理
→ 正規化
→ 驗證
→ 建立公開候選資料
→ 發布
→ HoloDocchi
```

也就是說，HoloDocchi 盡量把「資料產生」與「資料公開」分開。

這個做法有兩個目的：

1. 可以先確認資料正確，再對外發布。
2. 公開網站只需要接觸已經允許公開的資料。

## 為什麼強調可重建與可驗證

對歷史資料與字幕來說，重要的不只是「現在看起來能用」，而是未來仍能回答：

> 這份公開資料從哪裡來？  
> 當時實際發布的是哪一版？  
> 如果出錯，能不能單獨修正或回滾？

因此 HoloDocchi 的資料流程會盡量保留版本、manifest、hash 或其他可驗證資訊。

---

# 資料怎麼處理 / How data is handled

HoloDocchi 大致把資料分成四種類型。

## A. 即時或近即時資料

例如：

- 目前是否正在直播
- 即將開始的直播
- 需要較新狀態判定的資訊

這些資料適合由動態服務提供。

## B. 可重建的歷史資料

例如：

- 歷史直播
- 歷史 PTT
- 成員與別名資料

這些內容變動頻率較低，適合整理後以靜態方式提供。

## C. 經過整理或審核的內容

例如：

- 中文字幕
- Watchalong 對齊資料
- Daily Digest

這些內容不是「取得來源後立刻公開」，而是經過整理、驗證或審核後再發布。

## D. 不對外公開的營運資料

例如：

- 驗證紀錄
- 內部檢查資料
- 未公開來源資料
- 憑證與金鑰
- 維運用紀錄

這些內容不屬於 HoloDocchi 網站提供給使用者的公開資料。

公開原始碼不代表所有營運資料都應該公開。

---

# 資料來源與資料面 / Data sources and publication surfaces

## YouTube

HoloDocchi 使用 YouTube 相關資料來整理直播與歷史影片，影片播放主要透過官方 YouTube player。

HoloDocchi 不主張擁有 YouTube 上的影片、縮圖、聊天室內容或其他第三方素材。

## PTT

HoloDocchi 會整理 PTT 專串與推文時間軸，讓使用者可以在觀看影片時一起閱讀。

PTT 原始文章與推文仍屬原作者及平台規範所涵蓋的內容。

## Watchalong

Watchalong 使用獨立的事件與對齊資料，描述：

- 哪一支 Hololive 影片
- 對應哪一個同步片源
- 何時開始對齊
- 如何切換段落

這些資料與一般直播列表分開管理，因為它們的更新方式與驗證方式不同。

## 字幕

字幕以單一影片為單位管理。

這樣可以讓字幕修正獨立進行，不需要連同整個直播資料一起更新。

## Daily Digest

Daily Digest 屬於整理後內容，更新節奏與直播資料不同，因此獨立處理。

---

# 隱私與安全邊界 / Privacy and security boundaries

HoloDocchi 對外只提供網站功能與必要的公開資料。

以下資訊不屬於公開產品內容：

- API keys
- 帳號憑證
- 私人 cookies / session
- 私有資料庫
- 未公開研究資料
- 內部維運紀錄
- 個人資料
- 其他只用於維護網站的資訊

網站本身不應要求使用者接觸這些資訊。

---

# 授權與第三方內容 / License and third-party content

## 程式碼

除非個別檔案另有標示，本專案作者擁有並有權授權的程式碼，以 **MIT License** 釋出。

請參閱：

- [LICENSE](LICENSE)
- [DATA_SOURCES_AND_ATTRIBUTION.md](DATA_SOURCES_AND_ATTRIBUTION.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [REFERENCES.md](REFERENCES.md)

## MIT 不代表所有內容都是 MIT

MIT license 不會自動把第三方內容變成本專案的著作。

尤其以下內容不會因為出現在 HoloDocchi 而被重新授權成 MIT：

- Hololive / HOLOSTARS 名稱、品牌、角色、商標與相關素材
- YouTube 影片、縮圖、metadata、chat 內容
- PTT 文章與推文
- 第三方字幕或 transcript
- 外部來源的文字、圖片或影音
- 外部服務提供的資料

這些內容仍受各自權利人與平台條款約束。

## Fan project disclaimer

HoloDocchi 是非官方粉絲專案。

本專案沒有聲稱擁有 Hololive / HOLOSTARS 的角色、品牌或原始影音內容。

---

# English full reference

## What HoloDocchi is

HoloDocchi is an unofficial fan-built viewing interface for the Hololive ecosystem.

It does not re-host Hololive videos. Playback is primarily provided through the official YouTube embedded player.

The project brings together:

- current livestream discovery;
- historical stream browsing;
- custom single-view and multi-view playback;
- collaboration / multi-perspective viewing;
- synchronized watchalong playback;
- PTT discussion timelines;
- YouTube Chat related viewing interfaces;
- VOD subtitles;
- Daily Digest / Docchi News;
- schedule, birthday, anniversary, and historical calendar views.

## Why the architecture is split

HoloDocchi deliberately does not place every dataset behind one monolithic backend.

Live state, historical video data, PTT archives, subtitles, Watchalong event definitions, and Daily Digest content have different update frequencies, validation requirements, storage characteristics, and rollback needs.

The system therefore separates:

```text
frontend
+
live / near-live data
+
historical static data
+
subtitle publication
+
Watchalong publication
+
Daily Digest publication
```

These surfaces are separate internally but are presented as one product at holodocchi.com.

## Static-first where appropriate

Historical or reviewed data is a good fit for static publication when it does not need to be recomputed on every request.

Examples include:

- historical stream data;
- PTT archives;
- Watchalong definitions;
- subtitle files;
- Daily Digest artifacts;
- search aliases.

This provides:

- better caching;
- easier validation;
- deterministic artifacts;
- independent rollback;
- reduced coupling;
- lower dynamic-service load.

## Publication boundary

The general data flow is:

```text
source
→ organization
→ normalization
→ validation
→ public candidate
→ publication
→ HoloDocchi
```

The goal is to separate data creation from public delivery.

Only information intended for public use should cross that boundary.

## Data classes

### Live or near-live data

Current stream status and other freshness-sensitive information are better suited to dynamic delivery.

### Rebuildable historical data

Historical stream information, PTT archives, and aliases are better suited to validated static publication.

### Reviewed content

Subtitles, Watchalong alignment data, and Daily Digest content can pass through additional review or validation before publication.

### Non-public operational data

Credentials, private databases, internal validation evidence, unpublished source material, and maintenance records are not part of the public product.

Open-source code does not mean all operational data must be public.

## Data sources

### YouTube

HoloDocchi uses YouTube-related information to organize livestreams and historical videos. Playback is primarily handled by the official YouTube player.

HoloDocchi does not claim ownership of YouTube-hosted videos, thumbnails, chat messages, or other third-party material.

### PTT

HoloDocchi may normalize and present PTT discussion timelines for viewing purposes.

Original posts and pushes remain third-party/user-generated content.

### Watchalong

Watchalong alignment information is handled separately because it has a different validation and update model from general livestream data.

### Subtitles

Subtitle artifacts are managed per video so corrections can be released independently from the rest of the stream catalog.

### Daily Digest

Daily Digest content has its own editorial and update cadence and is therefore handled separately.

## Privacy and security

HoloDocchi publicly exposes only the website and data necessary for its public features.

Credentials, private databases, internal maintenance records, unpublished research material, and personal data are not part of the public product.

## License

Project-owned software that the project has the right to license is released under the MIT License unless otherwise noted.

The MIT License does **not** relicense third-party content such as Hololive intellectual property, YouTube content or metadata, PTT posts, or other externally sourced material.

See:

- `LICENSE`
- `DATA_SOURCES_AND_ATTRIBUTION.md`
- `THIRD_PARTY_NOTICES.md`
- `REFERENCES.md`
