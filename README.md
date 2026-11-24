# HoloViewer / HoloDocchi

> **繁體中文 / English bilingual README**  
> HoloDocchi 是一個非官方 Hololive 粉絲專案，整合直播發現、歷史直播瀏覽、多視角觀看、同時視聽、PTT 專串閱讀、字幕與日報資料。  
> HoloDocchi is an unofficial Hololive fan project for livestream discovery, historical browsing, multi-view playback, watchalong experiences, PTT discussion timelines, subtitles, and daily digest data.

**網站 / Website:** https://holodocchi.com  
**Repository:** `physicsdog0505/HoloViewer`

> [!IMPORTANT]
> 本專案與 COVER Corp.、hololive production、YouTube、Google、PTT 均無隸屬、授權、背書或官方合作關係。  
> This project is not affiliated with, endorsed by, sponsored by, or operated by COVER Corp., hololive production, YouTube, Google, or PTT.

---

## 目錄 / Table of Contents

- [專案是什麼 / What this project is](#專案是什麼--what-this-project-is)
- [目前功能 / Current features](#目前功能--current-features)
- [為什麼架構長這樣 / Why the architecture looks like this](#為什麼架構長這樣--why-the-architecture-looks-like-this)
- [整體架構 / Architecture overview](#整體架構--architecture-overview)
- [資料怎麼處理 / How data is handled](#資料怎麼處理--how-data-is-handled)
- [各資料面 / Data publication surfaces](#各資料面--data-publication-surfaces)
- [本機開發 / Local development](#本機開發--local-development)
- [測試與 release gate / Testing and release gates](#測試與-release-gate--testing-and-release-gates)
- [Repository 結構 / Repository layout](#repository-結構--repository-layout)
- [Production 與公開 repo 的邊界 / Production and public-repository boundaries](#production-與公開-repo-的邊界--production-and-public-repository-boundaries)
- [授權與第三方內容 / License and third-party content](#授權與第三方內容--license-and-third-party-content)
- [貢獻 / Contributing](#貢獻--contributing)
- [English full reference](#english-full-reference)

---

# 專案是什麼 / What this project is

HoloDocchi 的目標不是重新託管 Hololive 影片，而是把「觀看 Hololive 直播時常會同時需要的資訊」整理成一個瀏覽介面。

目前公開網站的核心內容包括：

- 今日 Hololive / HOLOSTARS 等直播整理
- 歷史直播查詢
- 自訂單人／多人 YouTube 觀看
- 多視角排列與主視角切換
- 同時視聽（Watchalong）雙時間軸對齊
- PTT 今日專串與歷史專串資料
- YouTube Chat 相關閱讀／重播介面
- VOD 中文字幕
- 本機字幕載入與 A/B 比較
- Docchi News / Daily Digest
- 行程、生日、紀念日與歷史直播月曆
- 多人連動／collab 瀏覽

影片播放主要透過 YouTube 官方 iframe player。HoloDocchi 不把 YouTube 影片下載後重新託管。

---

# 目前功能 / Current features

## 1. 今日直播

首頁會依公開資料整理正在直播、即將開始、狀態待更新與已結束的影片。

目前介面可依群組篩選：

- Hololive
- HOLOSTARS
- mekPark
- 全部

網站的目標是提供「從今天想看什麼」到「直接進入觀看模式」的入口，而不是只做直播列表。

## 2. 歷史直播

歷史頁面可依日期與成員搜尋過去直播。

成員搜尋支援別名／多語稱呼對照，相關 alias 靜態資料放在：

```text
site/data/search/
site/data/search/aliases/
```

歷史直播資料並不要求每次開頁都回查遠端 API；可重建、變動頻率低的內容會優先使用靜態資料面。

## 3. 自訂觀看

使用者可：

- 貼上 YouTube URL 或 Video ID
- 從直播列表或歷史影片加入影片
- 一次觀看一個或多個影片
- 使用自動、平均排列、主視角等版型
- 指定主要音訊
- 全部播放／暫停
- 使用沉浸模式
- 在多視角中輪播主視角
- 視情況搭配 PTT 討論時間軸

## 4. 多人連動

Collab 介面用來整理同一活動／合作直播中的多個視角，讓使用者比較容易建立多視角觀看情境。

## 5. 同時視聽 / Watchalong

Watchalong 是和一般多視角不同的功能。

其核心模型是：

```text
Hololive host timeline
        +
external/source video timeline
        +
alignment offset / segment mapping
        =
synchronized watchalong experience
```

支援的介面能力包括：

- Hololive 主畫面與同步片源
- 對齊目前位置
- offset 微調
- 段點切換
- 並排／動畫優先
- 連動播放
- 字幕／彈幕顯示
- 本機字幕檔載入
- PTT / YouTube Chat 閱讀

Watchalong 的資料有自己的 static asset surface，不與一般 VOD 字幕或 PTT static 混在同一個發布目標。

## 6. PTT 專串

網站可顯示 PTT 今日專串，也支援歷史月份的 PTT static assets。

PTT 是獨立資料來源，不被當成 HoloDocchi 自己創作的內容。原始文章與推文的權利仍屬其原作者及相關平台規範所涵蓋範圍。

## 7. 中文字幕

一般 VOD 字幕使用獨立的 subtitle static surface。

公開資料主要採：

```text
/data/subtitles/videos/<video_id>.json
/data/subtitles/index.json
/data/subtitles/manifests/by-vod-month/<YYYY-MM>.json
```

字幕發布與 Watchalong 是不同 publication pipeline。

## 8. Docchi News / Daily Digest

Daily Digest 使用獨立 static surface，以月份與日期為單位提供整理後內容及 related clips 資料。

這使日報內容可以獨立建立、驗證、回滾，不需要和主 frontend 同時部署。

---

# 為什麼架構長這樣 / Why the architecture looks like this

HoloDocchi 一開始曾經只有非常小的公開 smoke preview，但目前架構已經演化成「前端 + 多個獨立資料發布面」。

這個拆法是刻意的。

它主要解決以下問題。

## 1. 不讓所有東西共用一個後端

直播狀態、歷史 YouTube metadata、PTT 歷史資料、字幕、Watchalong、Daily Digest 的更新頻率與風險完全不同。

如果所有資料都塞進一個 API：

- 一個服務出錯可能讓整站一起失效
- 歷史資料會被迫和即時資料共用生命週期
- rollback 很難只回滾一種資料
- deployment blast radius 變大
- 大量唯讀資料會增加動態 API 成本
- 無法清楚區分「資料產生」和「資料發布」

因此目前採用多 surface。

## 2. 能靜態化的資料盡量靜態化

大量資料一旦確認後不需要每次請求都重新計算，例如：

- 歷史 YouTube catalog
- 歷史 PTT
- Watchalong event definitions
- VOD subtitle files
- Daily Digest
- aliases

這些資料適合：

```text
source
  → normalize
  → validate
  → build candidate
  → release gate
  → immutable/static publication
```

而不是：

```text
browser
  → dynamic server
  → database query
  → transform every request
```

這樣做的好處是可驗證、可快取、成本較低，而且比較容易保留 exact artifact。

## 3. Publication boundary 是安全邊界

HoloDocchi 刻意把「資料蒐集／研究／產生」與「公開發布」分開。

也就是：

```text
private/local authority
        ↓
validation
        ↓
public candidate
        ↓
explicit release gate
        ↓
public static surface
```

公開網站不應直接讀取本機 private SQLite、內部工作目錄、API token 或 Collector runtime。

## 4. 各資料面可以獨立 rollback

例如字幕發生錯誤時，不需要重新部署整個 frontend。

Watchalong event 有問題時，也不需要更動 YouTube catalog。

因此各 surface 有獨立：

- asset tree
- validation
- deployment script
- Cloudflare target
- cache behavior

## 5. 避免把 development runtime 當 production database

目前公開 frontend 是 Cloudflare static site / Worker asset 架構。

本機開發 runtime 的目的主要是重現 production asset behavior，不是讓公開網站依賴開發者電腦。

因此 production 不應依賴：

- 開發者 Mac 是否在線
- 本機 Streamlit
- 本機 SQLite
- localhost API
- private worktree

## 6. Exact artifact 比「重新算一次應該一樣」更重要

對歷史資料、字幕與 publication candidate，我們偏好：

- manifest
- hash
- content-addressed receipt
- deterministic rebuild
- explicit candidate tree
- readback / validation

原因是公開資料如果日後要除錯，必須能回答：

> 當時實際發布的是哪一份資料？

而不是只知道「當時某個 script 大概跑過」。

---

# 整體架構 / Architecture overview

目前概念上可以畫成：

```text
                         ┌──────────────────────────┐
                         │       Browser/User       │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ holodocchi.com frontend  │
                         │ Cloudflare static assets │
                         └───────┬──────┬──────┬───┘
                                 │      │      │
                 ┌───────────────┘      │      └────────────────┐
                 ▼                      ▼                       ▼
      ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
      │ Public API       │   │ YouTube Static   │   │ PTT Static       │
      │ live/read models │   │ historical/VOD   │   │ historical data  │
      └──────────────────┘   └──────────────────┘   └──────────────────┘

                 ▼                      ▼                       ▼
      ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
      │ Watchalong Static│   │ VOD Subtitle     │   │ Daily Digest     │
      │ event definitions│   │ Static Assets    │   │ Static Assets    │
      └──────────────────┘   └──────────────────┘   └──────────────────┘
```

公開 frontend 的主要設定可在：

```text
site/assets/config.js
```

看到。

目前 repo 中可見的公開資料端點包括：

```text
Public API
https://holoviewer-public-api.singlebagel.workers.dev

YouTube Static Assets
https://holoviewer-youtube-static-assets.singlebagel.workers.dev

Watchalong Static Assets
https://holoviewer-watchalong-static-assets.singlebagel.workers.dev

VOD Subtitle Static Assets
https://holoviewer-vod-subtitles-static-assets.singlebagel.workers.dev

Daily Digest Static Assets
https://holoviewer-daily-digest-static-assets.singlebagel.workers.dev
```

PTT historical assets 依月份可能由不同 static target 提供。實際 mapping 以 `site/assets/config.js` 為準。

> [!NOTE]
> workers.dev endpoint 是部署細節，不代表永久 public API compatibility contract。第三方整合前請先檢查目前程式碼與資料 schema。

---

# 資料怎麼處理 / How data is handled

這是 HoloDocchi 最重要的設計原則之一。

## 資料分類

我們把資料概念上分成四類：

### A. 即時或近即時資料

例如：

- 直播 lifecycle / live state
- 今天正在發生的觀看資訊
- 需要較新狀態判定的資料

這類資料較適合 public API。

### B. 可重建的歷史資料

例如：

- YouTube historical catalog
- PTT historical months
- member aliases

這類資料會優先轉成 static assets。

### C. 人工／半人工審核後的 publication artifacts

例如：

- 中文字幕
- Watchalong event alignment
- Daily Digest

這類資料不是「抓到就立刻上線」，而是經過 staging / validation 後再發佈。

### D. Private operational evidence

例如：

- publication receipts
- local checkpoints
- internal validation evidence
- private source corpus
- secrets / credentials
- local databases

這些資料不應因為 public repo 採 MIT 就自動公開，也不屬於前端執行所需的 public assets。

---

## 資料流原則

一般情況：

```text
source
  ↓
collection / ingestion
  ↓
normalization
  ↓
validation
  ↓
candidate artifact
  ↓
release gate
  ↓
public surface
  ↓
browser
```

並不是所有 source collection code 都位於本 public repository。

這個 repo 的角色是：

1. 公開 frontend
2. 公開資料 schema / consumer
3. 部分 public asset builders
4. public release tooling
5. validation / regression tests
6. 可公開的 publication artifacts

---

# 各資料面 / Data publication surfaces

## Public frontend

目錄：

```text
site/
```

Cloudflare config：

```text
cloudflare/wrangler.json
```

正式 custom domain：

```text
holodocchi.com
```

這一層負責 UI，不應擁有所有資料的唯一 source of truth。

---

## Public API

前端目前使用：

```text
https://holoviewer-public-api.singlebagel.workers.dev
```

Public API 適合需要動態讀取或較新狀態的資料。

它和 static historical assets 是不同責任。

---

## YouTube Static Assets

用途包括可靜態化的 YouTube / VOD catalog 資料。

設計原則是避免歷史頁面每次開啟都重新從動態來源重建所有過去資料。

---

## PTT Static Assets

PTT 歷史資料依月份發布。

前端 config 會指定每個月份使用的 base URL 與 manifest，例如：

```text
/ptt/v1/manifests/static-assets-full-YYYY-MM.json
```

為什麼 PTT historical 走 static：

- 歷史內容不需要高頻寫入
- 月份可獨立驗證
- manifest 可描述完整 publication candidate
- 大量唯讀請求不必打主要動態 DB
- 可獨立重新發布單一月份

PTT 資料不是 MIT code license 所涵蓋的「我們創作的程式碼」。

---

## Watchalong Static Assets

Repo 目錄：

```text
watchalong-static/data/watchalong/
```

主要包含：

```text
manifest.json
events/<event>.json
```

對應 Cloudflare target：

```text
holoviewer-watchalong-static-assets
```

Watchalong event 會描述觀看同步所需的公開資料，而不是把同步行為硬編碼在 frontend。

這使 event 可以獨立新增或修正。

---

## VOD Subtitle Static Assets

Repo 目錄：

```text
vod-subtitles-static/data/subtitles/
```

公開 contract：

```text
videos/<video_id>.json
index.json
manifests/by-vod-month/<YYYY-MM>.json
```

設計上字幕檔本身是 per-video authority。

字幕 availability index 不重複保存影片 title、thumbnail、member 等 YouTube catalog metadata，避免形成第二份互相可能漂移的 VOD metadata database。

詳細 publication contract 可參考：

```text
docs/VOD_SUBTITLE_STATIC_ASSETS.md
```

---

## Daily Digest Static Assets

Repo 目錄：

```text
daily-digest-static/data/daily-digest/
```

前端會依月份讀取：

```text
/data/daily-digest/months/{month}.json
```

related clips 則使用日期資料。

Daily Digest 之所以獨立，是因為內容生成、審核、更新頻率與直播 catalog 不同。

---

## Search aliases

搜尋 alias 屬於小型、可版本化、可 review 的靜態資料：

```text
site/data/search/
data/search/
```

它讓搜尋介面不必把暱稱規則塞進後端程式。

---

# 本機開發 / Local development

目前正式 public frontend 的本機 acceptance runtime 使用 Cloudflare Wrangler，而不是舊 Streamlit preview。

## 需求

至少需要：

- Node.js
- npm / npx
- Python 3
- Cloudflare Wrangler（由 npx 執行即可）

## 啟動

```sh
git clone https://github.com/physicsdog0505/HoloViewer.git
cd HoloViewer
sh scripts/start_public_local.sh
```

預設：

```text
http://127.0.0.1:8788/
```

改 port：

```sh
HOLOVIEWER_PUBLIC_LOCAL_PORT=8790 sh scripts/start_public_local.sh
```

這個本機環境使用 repo 中真正的：

```text
cloudflare/wrangler.json
site/**
```

因此比較接近 production frontend。

## 舊 Streamlit preview

Repo 根目錄仍保留：

```text
app.py
public_snapshot.py
```

這是專案早期 public smoke-preview lineage，目前**不是 HoloDocchi production frontend 的主要架構**。

不要因為看到 `app.py` 就把它視為目前網站的正式 entrypoint。

---

# 測試與 release gate / Testing and release gates

本機 preflight：

```sh
sh scripts/check_public_local.sh
```

目前測試包含 Python 與 JavaScript regression checks。

公開 repo 中也有多個針對：

- frontend
- Watchalong
- VOD subtitle
- YouTube static
- viewer integration
- browser lifecycle
- static release gate

的測試檔。

## Production release 原則

本專案採「先本機 acceptance，再 release」的思路。

CI 成功本身不代表 production 已更新。

對 production 判定應區分：

```text
source commit
candidate artifact
release execution
live deployed state
```

如果四者沒有對齊，就不應只因 GitHub 顯示綠燈而宣稱 production 已完成。

---

# Repository 結構 / Repository layout

主要目錄：

```text
.
├── site/                         # production public frontend assets
│   ├── index.html
│   ├── viewer/
│   ├── watchalong-viewer/
│   ├── ptt-today/
│   ├── assets/
│   └── data/
│
├── cloudflare/                   # frontend/static Cloudflare configs
│   ├── wrangler.json
│   ├── watchalong-static-assets.wrangler.json
│   ├── vod-subtitle-static-assets.wrangler.json
│   └── daily-digest-static-assets.wrangler.json
│
├── watchalong-static/            # Watchalong public assets
├── vod-subtitles-static/         # General VOD subtitle public assets
├── daily-digest-static/          # Daily Digest public assets
│
├── scripts/                      # build, validation and release helpers
├── docs/                         # architecture / contracts / handoffs
├── data/                         # small public/versioned support data
│
├── test_*.py                     # Python regression tests
├── test_*.js                     # JS regression tests
│
├── app.py                        # legacy Streamlit smoke preview
└── public_snapshot.py            # legacy preview helper
```

---

# Production 與公開 repo 的邊界 / Production and public-repository boundaries

這個 repository 是公開程式碼與公開 publication tooling 的重要部分，但不代表「所有 production 內部資料都應該存在 GitHub」。

公開 repo 不應包含：

- API keys
- Cloudflare secrets
- Google credentials
- private cookies / session data
- PTT login credentials
- local private SQLite databases
- unpublished source corpus
- private translation research artifacts
- publication receipts that are intentionally private
- user personal data
- machine-specific secrets

公開 frontend 應只依賴明確允許的 public endpoints / static assets。

---

# 授權與第三方內容 / License and third-party content

## 程式碼

除非個別檔案另有標示，本 repository 中由本專案作者擁有並有權授權的程式碼，以 **MIT License** 釋出。

請參閱：

```text
LICENSE
```

## MIT 不等於「所有資料都是 MIT」

MIT license 不會自動把第三方內容變成本專案的著作。

尤其以下項目不能單純因為出現在 repository 或網站上就視為 MIT：

- Hololive / HOLOSTARS 名稱、品牌、角色、商標與相關素材
- YouTube 影片、縮圖、metadata、chat 內容
- PTT 文章與推文
- 第三方字幕／transcript
- 第三方來源的文字、圖片或影音
- 外部服務提供的資料

這些內容仍受各自的權利人、來源網站與適用條款約束。

詳細說明：

- [DATA_SOURCES_AND_ATTRIBUTION.md](DATA_SOURCES_AND_ATTRIBUTION.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [REFERENCES.md](REFERENCES.md)

## Fan project disclaimer

HoloDocchi 是非官方粉絲專案。

本專案沒有聲稱擁有 Hololive / HOLOSTARS 的角色、品牌或原始影音內容。

---

# 貢獻 / Contributing

目前專案正在逐步把原本偏單人開發的流程整理成較容易由外部理解與貢獻的形式。

如果要提交修改，建議：

1. 先確認修改的是 frontend、哪一個 static surface，或 publication tooling。
2. 不要把不同 data surface 無必要地合併。
3. 新增資料時保留來源與 schema 邊界。
4. 不要提交 secrets 或 private operational artifacts。
5. 先在本機 public runtime 驗證。
6. 執行相關 regression tests。
7. PR 中說明影響哪個 publication surface，以及是否需要獨立 deployment。

更完整的 contribution guide 會持續補充。

---

# English full reference

## What HoloDocchi is

HoloDocchi is an unofficial fan-built viewing interface for the Hololive ecosystem.

It does not re-host Hololive videos. YouTube playback is primarily provided through the official YouTube iframe player.

The project brings together several things fans often need at the same time:

- current livestream discovery;
- historical stream browsing;
- custom single-view and multi-view playback;
- collaboration / multi-perspective viewing;
- synchronized watchalong playback;
- PTT discussion timelines;
- YouTube Chat related viewing interfaces;
- VOD subtitles;
- local subtitle comparison;
- Daily Digest / Docchi News;
- schedule, birthday, anniversary, and historical calendar views.

## Why the system is split into multiple publication surfaces

The project deliberately does not put every dataset behind one monolithic backend.

Live state, historical YouTube catalogs, PTT archives, subtitles, watchalong event definitions, and Daily Digest content have different:

- update frequencies;
- validation requirements;
- rollback needs;
- storage characteristics;
- copyright/source considerations;
- operational risk profiles.

For that reason, HoloDocchi separates the public frontend from multiple public API/static-asset surfaces.

The general model is:

```text
private or source authority
        ↓
normalization
        ↓
validation
        ↓
public candidate
        ↓
explicit release gate
        ↓
public API/static surface
        ↓
browser
```

This separation is intentional.

### Static-first where appropriate

Historical or reviewed data should not require a dynamic database query on every page load when the same data can be built and verified ahead of time.

Static publication is preferred for data such as:

- historical YouTube catalogs;
- PTT archives;
- Watchalong definitions;
- subtitle files;
- Daily Digest artifacts;
- search aliases.

Benefits include:

- lower coupling;
- easier caching;
- deterministic artifacts;
- independent rollback;
- smaller deployment blast radius;
- lower runtime cost;
- clearer provenance.

### Publication boundaries are also security boundaries

The public site should not directly depend on:

- a developer workstation;
- private SQLite databases;
- local-only services;
- private translation corpora;
- credentials or API secrets;
- internal publication receipts.

Only explicitly public artifacts should cross the publication boundary.

### Independent rollback

A subtitle correction should not require redeploying the entire frontend.

A Watchalong event correction should not require changing the YouTube historical catalog.

A PTT historical-month rebuild should not require modifying the live API.

This is why each surface has its own asset tree, validation rules, release tooling, and deployment target.

## Current high-level architecture

```text
Browser
  │
  ▼
holodocchi.com
Cloudflare-hosted frontend assets
  │
  ├── Public API
  ├── YouTube Static Assets
  ├── PTT Static Assets
  ├── Watchalong Static Assets
  ├── VOD Subtitle Static Assets
  └── Daily Digest Static Assets
```

The frontend endpoint map is visible in:

```text
site/assets/config.js
```

## Data handling

HoloDocchi conceptually separates data into four classes.

### 1. Live or near-live data

Examples include stream lifecycle and other state where freshness matters.

This is better suited to a public API.

### 2. Rebuildable historical data

Examples include historical YouTube catalog data, PTT historical months, and aliases.

These are strong candidates for static publication.

### 3. Reviewed publication artifacts

Examples include subtitles, Watchalong alignment definitions, and Daily Digest content.

These should pass through staging and validation before publication.

### 4. Private operational evidence

Examples include private receipts, checkpoints, unpublished source corpora, credentials, and local databases.

These are not public application assets and are not made public merely because the application code is open source.

## Public frontend

The production frontend is located under:

```text
site/
```

and is configured through:

```text
cloudflare/wrangler.json
```

The custom domain is:

```text
holodocchi.com
```

The old root-level Streamlit `app.py` remains as legacy smoke-preview code and should not be mistaken for the current production frontend.

## Public API

The frontend currently references:

```text
https://holoviewer-public-api.singlebagel.workers.dev
```

for data that remains appropriate for dynamic/public API access.

## YouTube static data

Historical/VOD catalog information can be served from a dedicated static surface so that browsing old streams does not require rebuilding all historical state dynamically for each request.

## PTT static data

PTT archive data is published in month-scoped manifests.

This makes it possible to validate and release one month independently and keeps large historical read traffic away from the dynamic API path.

PTT source text is third-party content and is not relicensed as MIT merely because code consuming it is MIT-licensed.

## Watchalong static data

Public Watchalong artifacts live under:

```text
watchalong-static/data/watchalong/
```

A Watchalong event definition is data consumed by the player, rather than a hard-coded frontend-only behavior.

That allows events and alignment corrections to be released independently.

## VOD subtitle static data

General VOD subtitles live under:

```text
vod-subtitles-static/data/subtitles/
```

The public contract includes per-video subtitle assets plus global and per-VOD-month availability manifests.

Subtitle availability indexes intentionally avoid duplicating full YouTube metadata, reducing the chance of creating two conflicting metadata authorities.

## Daily Digest static data

Daily Digest data is stored under:

```text
daily-digest-static/data/daily-digest/
```

It is independent because editorial/generation cadence and review behavior are different from live stream catalog data.

## Local development

Start the current public frontend locally with:

```sh
git clone https://github.com/physicsdog0505/HoloViewer.git
cd HoloViewer
sh scripts/start_public_local.sh
```

Default URL:

```text
http://127.0.0.1:8788/
```

Run local preflight with:

```sh
sh scripts/check_public_local.sh
```

## Release model

Passing CI does not by itself prove that production has been updated.

Source state, release candidate, release execution, and observed live state are distinct things.

The project therefore favors explicit release gates and observable production verification over treating a green CI badge as production acceptance.

## License

Code owned by the project and eligible for relicensing is released under the MIT License unless otherwise noted.

The MIT license does **not** relicense third-party content such as Hololive intellectual property, YouTube content/metadata, PTT posts, or other externally sourced material.

See:

- `LICENSE`
- `DATA_SOURCES_AND_ATTRIBUTION.md`
- `THIRD_PARTY_NOTICES.md`
- `REFERENCES.md`

---

## Status of this README

This document describes the current public-repository architecture and replaces the repository's original “Streamlit smoke preview only” description.

Because HoloDocchi is actively developed, exact endpoints, schemas, features, and deployment boundaries may evolve. When code and documentation disagree, treat the current code and validated deployment state as the technical source of truth, then update the documentation.
