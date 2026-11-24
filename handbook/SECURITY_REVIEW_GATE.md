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
