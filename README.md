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

### 繁體中文
- [HoloDocchi 是什麼](#holodocchi-是什麼)
- [目前功能](#目前功能)
- [為什麼架構長這樣](#為什麼架構長這樣)
- [資料怎麼處理](#資料怎麼處理)
- [資料來源與資料面](#資料來源與資料面)
- [隱私與安全邊界](#隱私與安全邊界)
- [授權與第三方內容](#授權與第三方內容)

### English
- [What HoloDocchi is](#what-holodocchi-is)
- [Current features](#current-features)
- [Why the architecture looks like this](#why-the-architecture-looks-like-this)
- [How data is handled](#how-data-is-handled)
- [Data sources and publication surfaces](#data-sources-and-publication-surfaces)
- [Privacy and security boundaries](#privacy-and-security-boundaries)
- [License and third-party content](#license-and-third-party-content)

---

# 繁體中文

## HoloDocchi 是什麼

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

## 目前功能

### 1. 今日直播

首頁會整理正在直播、即將開始、狀態待更新與已結束的影片，讓使用者從「今天想看什麼」直接進入觀看。

### 2. 歷史直播

可依日期與成員查詢過去直播，也支援常用名稱、暱稱與多語別名搜尋。

### 3. 自訂觀看

可自由加入 YouTube 影片，建立單人或多人觀看版面，包含：

- 多視角排列
- 主視角切換
- 主要聲音選擇
- 連動播放／暫停
- 沉浸模式
- 多視角輪播
- 搭配討論時間軸

### 4. 多人連動

針對同一活動或合作直播整理多個視角，方便在同一介面中快速切換與比較。

### 5. 同時視聽 / Watchalong

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

### 6. PTT 專串

可閱讀今日專串與已整理的歷史專串資料。

PTT 文章與推文屬於第三方／使用者產生內容。HoloDocchi 提供閱讀、索引與時間軸整理，不主張擁有原始文字。

### 7. 中文字幕

HoloDocchi 可為部分 VOD 提供中文字幕。

字幕資料與影片本身分離管理，避免字幕系統變成另一份重複的影片資料庫。

### 8. Docchi News / Daily Digest

將近期直播、重點內容與相關剪輯整理成較容易閱讀的日報形式。

### 9. 行程與月曆

包含直播月曆、生日、紀念日與歷史直播瀏覽，讓使用者能從時間維度回顧內容。

---

## 為什麼架構長這樣

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

### Static-first

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

### Publication boundary

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

### 為什麼強調可重建與可驗證

對歷史資料與字幕來說，重要的不只是「現在看起來能用」，而是未來仍能回答：

> 這份公開資料從哪裡來？  
> 當時實際發布的是哪一版？  
> 如果出錯，能不能單獨修正或回滾？

因此 HoloDocchi 的資料流程會盡量保留版本、manifest、hash 或其他可驗證資訊。

---

## 資料怎麼處理

HoloDocchi 大致把資料分成四種類型。

### A. 即時或近即時資料

例如：

- 目前是否正在直播
- 即將開始的直播
- 需要較新狀態判定的資訊

這些資料適合由動態服務提供。

### B. 可重建的歷史資料

例如：

- 歷史直播
- 歷史 PTT
- 成員與別名資料

這些內容變動頻率較低，適合整理後以靜態方式提供。

### C. 經過整理或審核的內容

例如：

- 中文字幕
- Watchalong 對齊資料
- Daily Digest

這些內容不是「取得來源後立刻公開」，而是經過整理、驗證或審核後再發布。

### D. 不對外公開的營運資料

例如：

- 驗證紀錄
- 內部檢查資料
- 未公開來源資料
- 憑證與金鑰
- 維運用紀錄

這些內容不屬於 HoloDocchi 網站提供給使用者的公開資料。

公開原始碼不代表所有營運資料都應該公開。

---

## 資料來源與資料面

### YouTube

HoloDocchi 使用 YouTube 相關資料來整理直播與歷史影片，影片播放主要透過官方 YouTube player。

HoloDocchi 不主張擁有 YouTube 上的影片、縮圖、聊天室內容或其他第三方素材。

### PTT

HoloDocchi 會整理 PTT 專串與推文時間軸，讓使用者可以在觀看影片時一起閱讀。

PTT 原始文章與推文仍屬原作者及平台規範所涵蓋的內容。

### Watchalong

Watchalong 使用獨立的事件與對齊資料，描述：

- 哪一支 Hololive 影片
- 對應哪一個同步片源
- 何時開始對齊
- 如何切換段落

這些資料與一般直播列表分開管理，因為它們的更新方式與驗證方式不同。

### 字幕

字幕以單一影片為單位管理。

這樣可以讓字幕修正獨立進行，不需要連同整個直播資料一起更新。

### Daily Digest

Daily Digest 屬於整理後內容，更新節奏與直播資料不同，因此獨立處理。

---

## 隱私與安全邊界

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

## 授權與第三方內容

### 程式碼

除非個別檔案另有標示，本專案作者擁有並有權授權的程式碼，以 **MIT License** 釋出。

請參閱：

- [LICENSE](LICENSE)
- [DATA_SOURCES_AND_ATTRIBUTION.md](DATA_SOURCES_AND_ATTRIBUTION.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [REFERENCES.md](REFERENCES.md)

### MIT 不代表所有內容都是 MIT

MIT license 不會自動把第三方內容變成本專案的著作。

尤其以下內容不會因為出現在 HoloDocchi 而被重新授權成 MIT：

- Hololive / HOLOSTARS 名稱、品牌、角色、商標與相關素材
- YouTube 影片、縮圖、metadata、chat 內容
- PTT 文章與推文
- 第三方字幕或 transcript
- 外部來源的文字、圖片或影音
- 外部服務提供的資料

這些內容仍受各自權利人與平台條款約束。

### Fan project disclaimer

HoloDocchi 是非官方粉絲專案。

本專案沒有聲稱擁有 Hololive / HOLOSTARS 的角色、品牌或原始影音內容。

---

# English

## What HoloDocchi is

HoloDocchi is not intended to re-host Hololive videos. Its goal is to organize the information viewers commonly want while watching Hololive streams into a single browsing and viewing interface.

Typical use cases include:

- quickly seeing what is live right now;
- finding streams from a particular day or member;
- watching multiple perspectives at the same time;
- synchronizing another source while watching a Hololive watchalong;
- watching a video while reading a PTT thread or YouTube Chat;
- reading prepared Traditional Chinese subtitles;
- quickly reviewing recent content and related clips.

Video playback is primarily provided through the official YouTube iframe player. HoloDocchi does not download and re-host YouTube videos.

---

## Current features

### 1. Today's livestreams

The home page organizes videos that are live, upcoming, awaiting updated status, or already ended, allowing viewers to move directly from “what should I watch today?” into playback.

### 2. Historical streams

Past streams can be searched by date and member. Common names, nicknames, and multilingual aliases are also supported.

### 3. Custom viewing

Users can freely add YouTube videos and create single-view or multi-view layouts, including:

- multi-perspective layouts;
- primary-view switching;
- primary-audio selection;
- linked play / pause;
- immersive mode;
- rotating focus among multiple views;
- discussion-timeline integration where applicable.

### 4. Collaboration / multi-perspective viewing

Multiple perspectives from the same event or collaboration can be organized together for quick switching and comparison within one interface.

### 5. Watchalong

Watchalong is more than simply placing two video players next to each other. It combines:

```text
Hololive host timeline
+
synchronized source timeline
+
alignment information
=
a synchronized watchalong experience
```

The interface can support:

- the host video and synchronized source;
- aligning the current playback position;
- fine adjustment of timing differences;
- segment switching;
- side-by-side and primary-view switching;
- linked playback;
- subtitle and danmaku display;
- PTT / YouTube Chat viewing.

### 6. PTT threads

Users can read the current day's thread and organized historical thread data.

PTT articles and pushes are third-party / user-generated content. HoloDocchi provides reading, indexing, and timeline organization, but does not claim ownership of the original text.

### 7. Traditional Chinese subtitles

HoloDocchi can provide Traditional Chinese subtitles for selected VODs.

Subtitle data is managed separately from the videos themselves so that the subtitle system does not become a duplicate video metadata database.

### 8. Docchi News / Daily Digest

Recent streams, notable content, and related clips are organized into a more readable daily digest format.

### 9. Schedule and calendar

The site includes stream calendars, birthdays, anniversaries, and historical-stream browsing so users can explore content from a time-based perspective.

---

## Why the architecture looks like this

HoloDocchi does not place all of its data behind a single backend.

This is intentional.

Livestream state, historical streams, PTT data, subtitles, Watchalong data, and Daily Digest content have different update frequencies, data volumes, validation methods, and rollback requirements.

Putting everything together would create several problems:

- one service failure could affect the entire site;
- historical data and live data would be forced to share the same lifecycle;
- correcting subtitles could require deploying unrelated features at the same time;
- large volumes of read-only historical data would increase dynamic-service cost;
- rolling back only one type of data would become difficult;
- it would be harder to determine how a specific public artifact was produced.

HoloDocchi therefore separates:

```text
frontend
+
live data
+
historical data suitable for static publication
+
independently published subtitles
+
independently published Watchalong data
+
independently published Daily Digest data
```

These data surfaces are separate from one another, while HoloDocchi combines them into a single user experience.

### Static-first

For data that changes infrequently and can be validated and rebuilt, HoloDocchi prefers static publication.

Examples include:

- historical stream data;
- historical PTT data;
- Watchalong definitions;
- VOD subtitles;
- Daily Digest content;
- search aliases.

The reasons are:

- easier caching;
- easier validation;
- easier rebuilding;
- easier independent rollback;
- no need to query or recompute the same information every time a page is opened;
- lower load on a single dynamic backend.

### Publication boundary

From source to public website, data generally passes through:

```text
source
→ organization
→ normalization
→ validation
→ public candidate
→ publication
→ HoloDocchi
```

In other words, HoloDocchi tries to separate “producing data” from “publishing data.”

This serves two purposes:

1. Data can be checked before it is made public.
2. The public website only needs access to information that has been approved for public delivery.

### Why rebuildability and verifiability matter

For historical data and subtitles, it is not enough that something “works right now.” The project should still be able to answer later:

> Where did this public data come from?  
> Which exact version was actually published at the time?  
> If something is wrong, can it be corrected or rolled back independently?

For this reason, HoloDocchi's data workflows aim to preserve versions, manifests, hashes, or other verifiable information where appropriate.

---

## How data is handled

HoloDocchi broadly separates data into four categories.

### A. Live or near-live data

Examples include:

- whether a stream is currently live;
- upcoming streams;
- information that requires relatively fresh status evaluation.

This type of data is better suited to dynamic delivery.

### B. Rebuildable historical data

Examples include:

- historical streams;
- historical PTT data;
- member and alias data.

These change less frequently and are suitable for organized static publication.

### C. Organized or reviewed content

Examples include:

- Traditional Chinese subtitles;
- Watchalong alignment data;
- Daily Digest content.

These are not necessarily published immediately after a source is obtained. They can go through organization, validation, or review before publication.

### D. Non-public operational data

Examples include:

- validation records;
- internal inspection data;
- unpublished source material;
- credentials and keys;
- maintenance records.

These are not part of the public data provided to HoloDocchi users.

Open-source code does not mean that all operational data should be public.

---

## Data sources and publication surfaces

### YouTube

HoloDocchi uses YouTube-related information to organize livestreams and historical videos. Video playback is primarily provided through the official YouTube player.

HoloDocchi does not claim ownership of videos, thumbnails, chat content, or other third-party material hosted on YouTube.

### PTT

HoloDocchi organizes PTT threads and push timelines so users can read them while watching videos.

Original PTT articles and pushes remain content covered by their original authors' rights and the platform's applicable rules.

### Watchalong

Watchalong uses separate event and alignment data describing:

- which Hololive video is involved;
- which synchronized source corresponds to it;
- when alignment begins;
- how segments are switched.

This information is managed separately from the general livestream list because its update and validation requirements are different.

### Subtitles

Subtitles are managed on a per-video basis.

This allows subtitle corrections to be handled independently without requiring the entire livestream dataset to be updated at the same time.

### Daily Digest

Daily Digest is organized editorial content with a different update cadence from livestream data, so it is handled separately.

---

## Privacy and security boundaries

HoloDocchi publicly provides only the website features and public data required for those features.

The following are not part of the public product:

- API keys;
- account credentials;
- private cookies / sessions;
- private databases;
- unpublished research material;
- internal maintenance records;
- personal data;
- other information used only to maintain the service.

The website itself should not require users to access this information.

---

## License and third-party content

### Code

Unless otherwise noted in an individual file, code owned by the project authors and eligible for licensing is released under the **MIT License**.

See:

- [LICENSE](LICENSE)
- [DATA_SOURCES_AND_ATTRIBUTION.md](DATA_SOURCES_AND_ATTRIBUTION.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [REFERENCES.md](REFERENCES.md)

### MIT does not mean all content is MIT-licensed

The MIT License does not automatically turn third-party content into project-owned material.

In particular, the following are not relicensed under MIT merely because they appear in or are referenced by HoloDocchi:

- Hololive / HOLOSTARS names, brands, characters, trademarks, and related material;
- YouTube videos, thumbnails, metadata, and chat content;
- PTT articles and pushes;
- third-party subtitles or transcripts;
- externally sourced text, images, or audiovisual material;
- data provided by external services.

These materials remain subject to the rights of their respective owners and applicable platform terms.

### Fan project disclaimer

HoloDocchi is an unofficial fan project.

The project does not claim ownership of Hololive / HOLOSTARS characters, brands, or original audiovisual content.
