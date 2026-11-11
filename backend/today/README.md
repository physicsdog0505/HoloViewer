# Issue #47 — backend-only offline contract and deployment HOLD

This is an isolated **prototype** on a draft branch. It makes **no network calls**. No `site/**`, live Worker, PTT, 4174, or real D1 changes. The D1 migration SQL is a **proposal**, not deployed and not invoked.

Run offline tests: `python -B -m unittest -v backend.today.test_today_offline`.

Data contract: `GET /v1/catalog/today` stays compatible with Public `streams[]`, `video_id`, `title`, `channel_name`, `channel_id`, and `lifecycle_state`. Proposed additive `schema_version`, `as_of`, `freshness` and `completeness` are for owner review, not visible yet in unmodified frontend.

Do not use `hololive_channels.prototype.json` as an approved roster: it describes a 66-channel canary, not a permanent production roster. Public must accept only owner-signed, versioned roster IDs; currently no production roster provided. Upload playlist head-page discovery is incomplete for some preannounced streams. Unknown/gap is honest; it does not mean zero broadcasts.

Proposal: dedicated Cloudflare Cron Worker, single-writer lease/run_id, bounded per-channel uploads-page scan every 30 minutes, known-active batched videos.list check every 10 minutes, quota reservation before API requests and backoff on errors; alternate secured external publisher if Cloudflare execution/plan cannot support it. Never perform YouTube requests from visitor GET. Exact sources: channels.list contentDetails once, playlistItems.list pages (1 unit/request), videos.list snippet/liveStreamingDetails/status batch (1 unit/request). 66*48 + 72 = 3,240 request units/day illustrative, not verified quota; extra pages/retries add cost. Reserve 1,500 of assumed 10k project units/day pending actual console check. For D1, 500 content changes + 3,168 per-channel watermark writes + 48 run writes = 3,716 written rows/day (upper illustrative, optimize to change-only writes); 111,480 / 30 days. Shared account usage, actual free/paid limits and write charges need owner validation.

Critical limitations: current Python sqlite writer is a D1 **analog**, NOT a transactional D1 HTTP adapter; SQL migration has not been applied, and raw YouTube normalization fixtures are synthetic (real structures, no live observation). Cron registration, leases, quota counters, provider HTTP client and D1 integration are NOT built or verified. Do not interpret this PR as production-ready.

Approval gate: owner roster/version; API envelope/UI stale handling; exact provider quota & Cloudflare plan, dedicated DB and least privilege; review real response fixtures; implement and validate actual D1 conditional monotonic writes and cron execution under separately approved staging; independent security review; separate explicit live API/D1/deployment approval. Roll back by disabling scheduled trigger + serving last good snapshot as stale; restore prior API revision; never delete local/private DB or PTT data.
