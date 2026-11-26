# Documentation Security Review Gate / 文件安全檢查 Gate

每完成一章或一批公開文件，都必須進行一次**獨立安全檢查**，與技術正確性審查分開。

Every completed public documentation chapter or batch must pass an **independent security review**, separate from technical correctness review.

## Review questions / 檢查項目

### 1. Secrets / 機密
不得包含：
- API keys, tokens, cookies, credentials
- account / zone / resource IDs that are not required publicly
- private URLs or authenticated endpoints
- private database locations
- unpublished source artifacts

### 2. Production topology / 正式環境拓樸
除非是使用者必須知道的公開介面，否則不得公開：
- exact internal worker/service names
- internal routing topology
- admin or control surfaces
- rollback version identifiers
- production release SHAs used only for operations
- exact runtime ownership maps
- incident-only infrastructure details

公開文件應優先描述抽象架構，例如：
`frontend → live data → static archives`
而不是正式環境中的實際服務名稱與管理路徑。

### 3. Local / operator information / 本機與維運資訊
不得公開：
- localhost ports
- developer machine paths
- user home directories
- machine names
- owner-only deployment commands
- local runtime process names when operationally sensitive
- internal handoff instructions

### 4. Attack-surface enumeration / 攻擊面枚舉
檢查文件是否不必要地提供：
- exact service inventory
- endpoint inventory beyond public product interfaces
- writable/control endpoint hints
- authentication assumptions
- rate-limit or protection weaknesses
- incident root-cause details that materially lower exploitation cost before remediation

### 5. Third-party and privacy / 第三方與隱私
檢查：
- 不公開個人資料
- 不把第三方內容誤標成 MIT
- 不公開未經授權的 corpus / transcripts
- 不包含不必要的原始聊天、郵件、帳號資訊

### 6. Reproducibility without operational leakage / 可重現但不洩漏維運資訊
應公開：
- algorithms
- data models
- validation logic
- failure modes
- synthetic examples
- measured parameters where safe
- architecture trade-offs

不應為了「可重現」而公開：
- actual production credentials
- exact production topology
- operator runbooks
- internal rollback procedures

## Result labels / 結果標記

每批文件完成後記錄：

- `SECURITY_REVIEW=PASS`
- `SECURITY_REVIEW=PASS_WITH_REDACTIONS`
- `SECURITY_REVIEW=HOLD`

並簡述檢查範圍與移除內容。

## Current review — Chapters 02–03

Scope:
- `02-data-engineering.md`
- `03-live-discovery.md`

Result:
`SECURITY_REVIEW=PASS`

Reason:
- no credentials, account IDs, local paths, ports or owner-only commands;
- no exact production worker names or internal service topology;
- examples are conceptual/synthetic;
- public behavior and generic algorithms are described without operational runbook details.

Open action:
- legacy public runbooks and handoff files elsewhere in the repository require a separate cleanup review and are **not** covered by this PASS.


## Review — Chapter 04 Historical streams

Scope:
- `04-historical-streams.md`

Result:
`SECURITY_REVIEW=PASS`

Checks:
- no credentials, tokens, account identifiers, private URLs, local paths or operator commands;
- no production worker/service names, rollback identifiers, admin/control endpoints or internal routing topology;
- public technical constants documented here (50-row daily page size, 200-row render batch, 60-second manifest cache) are client-side behavior visible from public source and do not grant privileged access;
- examples use synthetic/generic search inputs and do not expose private datasets;
- proposed search improvements are clearly marked as proposals rather than current implementation.

Security note:
- exposing public client-side search and cache behavior can aid implementation comparison but does not disclose a privileged control surface;
- if future chapters discuss rate limits, writable endpoints, authentication assumptions, incident details or unpatched vulnerabilities, those details require stricter review and may need redaction or delayed publication.


## Review — Chapter 03 upstream lifecycle expansion

Scope:
- `03-live-discovery.md` additions covering uploads discovery, WebSub role, tracked-roster policy, Today-to-History convergence, and historical reconciliation cadence.

Result:
`SECURITY_REVIEW=PASS_WITH_REDACTIONS`

Published safely:
- conceptual authority chain: uploads playlist + event evidence + Stream Catalog → bounded metadata verification → canonical history → static history;
- current roster cardinality (86 tracked, 1 retired, 85 active) and activation-boundary policy;
- current historical reconciliation default cadence (6 hours / 21600 seconds);
- bounded metadata verification batch size (up to 50 video IDs), because it is an algorithmic/provider API constraint useful for reproducibility;
- generic WebSub safety principles: approved roster, active leases, signature validation, idempotency, stale-event protection, and coverage gating;
- historical evidence status that an older roster once reached full lease coverage, explicitly not claimed as current live state.

Intentionally omitted / redacted:
- exact callback route;
- callback hostname or Worker/service name;
- secret-binding names or HMAC key material;
- lease database/table schema and storage location;
- renewal/control endpoint details;
- production activation commands;
- account/resource identifiers;
- current live lease inventory;
- operator-local scheduler installation details and paths.

Assessment:
The disclosed cadence and roster cardinality help others reproduce the architecture but do not grant privileged access. WebSub details are kept at protocol/design level rather than production reconnaissance level.


## Review — Chapter 05 PTT data system

Scope:
- `05-ptt-data.md`

Result:
`SECURITY_REVIEW=PASS_WITH_REDACTIONS`

Published safely:
- generic Collector/Web provenance model;
- completeness states and canonical merge policy;
- source-priority values used by the reproducible read model;
- floor/source-line identity distinction;
- historical cursor semantics and the corrected “tail is not history” lesson;
- generic timing equation for aligning PTT pushes with verified video start;
- browser-automation completeness lessons and URL-contract failure history.

Intentionally omitted / redacted:
- actual production PTT endpoint URLs;
- exact Worker/service names;
- writable or administrative routes;
- authentication/token details;
- production D1 identifiers, bindings, table names used only operationally, or live retention settings;
- local database paths, machine paths, login/session details;
- operational polling cadence for protected/internal writers;
- exact incident/runbook commands.

Assessment:
The chapter exposes reproducible data-model and integrity methods without publishing credentials or a production attack-surface map. Source-priority values and generic cursor behavior are architectural knowledge, not privileged control information.


## Review — Chapters 06–07 Multi-view player and master timeline

Scope:
- `06-multi-view-player.md`
- `07-master-timeline.md`

Result:
`SECURITY_REVIEW=PASS`

Published safely:
- public client-side player behavior and timeline schema;
- generic synchronization formulas;
- public runtime constants relevant to reproducibility (16-stream UI cap, ~900 ms event-suppression window, 500 ms reconcile cadence, 2.5 s master-drift threshold, 1.2 s seek threshold);
- segment replacement, gap handling, clock fallback and browser-autoplay limitation;
- failure modes already visible in public client source.

Checks:
- no credentials, tokens, private hostnames, internal endpoints, account/resource IDs or production-control routes;
- no operator-local commands or machine paths;
- no writable/admin API details;
- timing thresholds are client-side behavior and do not lower privileged-access barriers;
- formulas/examples use generic synthetic timelines.

Assessment:
These chapters expose reproducible synchronization engineering without revealing production topology or control surfaces.


## Review — Chapters 08–09 Collaboration identification and Watchalong

Scope:
- `08-collab-identification.md`
- `09-watchalong.md`

Result:
`SECURITY_REVIEW=PASS_WITH_REDACTIONS`

Published safely:
- distinction between candidate grouping and verified event identity;
- conservative candidate heuristics and their known limits;
- event-day rollover example as domain policy;
- public event/sync contracts at schema level;
- Watchalong host-driven timing formula, segment model, gap handling and drift thresholds;
- transcript/translation provenance checks and generic static validation logic;
- client-side progress-resume and subtitle-clock behavior.

Intentionally omitted / redacted:
- exact production collab API URLs and internal producer routes;
- actual Watchalong static origin/Worker/service names;
- production event inventory and private review selections;
- approved-sync source checkout locations;
- deployment commands, release SHAs, rollback procedures and operator-only paths;
- any unpublished source-media rights/access information;
- secret bindings, account/resource IDs and administrative endpoints.

Assessment:
The chapters publish reproducible synchronization and event-identity methods without providing a production topology map or privileged control information. Public client-visible thresholds and schema rules are retained because they are implementation knowledge, not access credentials.


## Review — Chapters 10–11 Concurrent viewers and Highlights

Scope:
- `10-concurrent-viewers.md`
- `11-highlights.md`

Result:
`SECURITY_REVIEW=PASS_WITH_REDACTIONS`

Published safely:
- current concurrent-viewer field semantics;
- reuse of the existing lifecycle metadata refresh rather than a second polling loop;
- five-minute observation cadence as public architectural behavior;
- the historical D1 bind-amplification regression (45 rows → 136 binds) and generic 30-ID chunking correction;
- explicit statement that historical samples/peaks/trends are not active;
- homepage highlight categories, ranking semantics and stable tie-breaking;
- distinction between editorial priority, popularity, and finalized Daily Digest authority.

Intentionally omitted / redacted:
- production database identifiers and binding names;
- exact writable/admin endpoints;
- Worker/service names and production topology;
- internal telemetry dashboards, account limits, billing identifiers or current quota consumption;
- deployment/rollback commands and exact operational SHAs;
- unpatched operational weaknesses beyond the already-corrected public regression.

Assessment:
The D1 regression is documented as an engineering lesson without exposing privileged access or a current exploit path. Client-visible ranking rules and cadence are reproducibility information. No production control surface is disclosed.


## Review — Chapters 12–14 Source transcripts, AI translation, Translation quality

Scope:
- `12-source-transcripts.md`
- `13-ai-translation.md`
- `14-translation-quality.md`

Result:
`SECURITY_REVIEW=PASS_WITH_REDACTIONS`

Published safely:
- transcript identity/content-hash model and deterministic segment invariants;
- separation of caption acquisition from translation;
- quality-v2 stage model (initial → QE → selective post-edit);
- historically used bounded batch examples (10-cue progressive and 20-segment acceptance configuration), clearly scoped rather than presented as universal stable values;
- progressive scheduling windows and whole-VOD-vs-one-shot distinction;
- immutable-attempt and deterministic validation principles;
- failure/recovery lessons for partial output, unknown provider outcomes, checkpoint coverage, sentence reconstruction and target-side retiming;
- multi-stage call-amplification example and A/B/C evidence rules.

Intentionally omitted / redacted:
- local workspace paths and user home directories;
- Drive folder IDs, account identities and subscription details;
- API keys, cookies, credentials, secret names and provider-session state;
- production queue file locations and operator-only scheduling commands;
- exact private receipt/ledger paths;
- unpublished transcript text, third-party subtitle bodies and captured reference frames;
- production import/deployment procedures.

Assessment:
The chapters reveal reproducible translation architecture and failure history without exposing credentials, account topology or operational control surfaces. Public numeric batch examples are retained because they are experimental/acceptance parameters useful for reproducing the engineering trade-offs, and are explicitly labeled by route and evidence status.
