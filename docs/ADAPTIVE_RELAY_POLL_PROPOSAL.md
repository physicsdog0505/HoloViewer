# Proposal: adaptive Public PTT GET polling (OFFLINE ONLY)

Status: Owner-approved **policy specification and synthetic tests**, NOT enabled in the public Reader. Approved 2026-10-10: **Mon–Fri 18:00–22:00**, **Sat–Sun 16:00–22:00** `Asia/Taipei`, polling every **10 seconds** in these windows, **120 seconds** outside them. All week days have explicit independent entries for future customization. Additional peak windows or changes remain opt-in.

## Weekly schedule (Asia/Taipei)
| Day | Peak | Interval | All other times |
|---|---|---|---|
| Mon | 18:00–22:00 | 10s | 120s |
| Tue | 18:00–22:00 | 10s | 120s |
| Wed | 18:00–22:00 | 10s | 120s |
| Thu | 18:00–22:00 | 10s | 120s |
| Fri | 18:00–22:00 | 10s | 120s |
| Sat | 16:00–22:00 | 10s | 120s |
| Sun | 16:00–22:00 | 10s | 120s |

Intervals apply to **GET scheduling**, not the existing owner-accepted Reader reveal/autoread/scroll/UI speed controls. Start is inclusive, end exclusive. No calls required exactly at the boundary; the next scheduler decision uses the current Asia/Taipei clock.

## Temporary acceleration — approved default
- A manually activated **60-minute override at 10-second polling**, ending automatically 60 minutes after activation and restoring the current day/time weekly rule; never a permanent toggle.
- Policy priority: **active time-bounded override > scheduled weekday window > 120-second default**. A current 10-second peak window remains 10 seconds if overridden with 10 seconds.
- Implement expiry as an **absolute timestamp**, not a count of polling ticks; a page reload should fail safe back to the weekly rule unless a separately authorized shared durable override mechanism exists.
- No owner/admin endpoint or management UI is authorized. A future centrally configurable, authenticated, read-only policy-delivery adapter can be proposed separately; do not expose administrative controls or tokens in Pages.
- Do not enable a new background timer for a hidden tab. Re-evaluate schedule on return to foreground. Account for request failures with bounded backoff (429/5xx), preserving cursor and previous pushes.

## Frozen contracts and constraints
- Preserve GET `tail=1` bootstrap without `after_cursor`; subsequent `after_cursor=next_cursor` pagination, same-ID conflict checks and retention PARTIAL status remain unchanged.
- Keep one timer per active AID and cancel old in-flight updates on article switch. Nothing in this proposal changes production Reader or 4174 UI, Worker/D1/Publisher, cloud deployment or existing access boundaries.
- Weekday boundaries determined from **Asia/Taipei calendar day**, not the browser's locale; future user-defined days may use the same pure policy.
- Defaults do not silently switch on activity detection. Any extra peak window, on-the-fly admin change, or behavior change requires a subsequent owner-approved implementation.
- No Gemini/API secrets, Collector, 8501/4174 admin or private SQLite may enter public config.

## Theoretical GET model (10 continuously active viewers, one AID each)
- Weekday: 4h ×3600/10 +20h×3600/120 = **2,040 GET/viewer/day**, **20,400/10 viewers/day**.
- Weekend day: 6h×3600/10 +18h×3600/120 = **2,700 GET/viewer/day**, **27,000/10 viewers/day**.
- Weekly: five weekdays + two weekend days = **156,000 GET/week across 10 viewers**, average ~**22,285.7 GET/day**.
- Comparison fixed 5s: **172,800 GET/day for 10 viewers**, 1,209,600/week; weekly reduction ~**87.10%**.
These are approximate policy-level request counts, NOT Cloudflare D1 metered rows, billing or measured production traffic. Retry, pagination, page-hidden behavior, caching and multiple watched AIDs alter actual load.

## Offline synthetic validation
`test_relay_poll_policy_proposal.mjs` verifies all seven weekdays, UTC→Taipei and edge boundaries, weekly request arithmetic, override start/expiry/cross-day, hidden tabs, and deterministic fallback after expiry. Production `RELAY_POLL_MS = 5000` remains unchanged.

## Next implementation gate (NOT executed)
1. Isolate the pure clock/weekday/override policy from this fixture and inject it **only into fetch scheduling**; zero changes to 4174-visible controls.
2. Review manual override control/auth and persistence separately; do not deploy unprotected admin endpoints.
3. Add live Reader transition/failure/cancellation regressions under disposable synthetic GET before enabling.
4. Require independent review, cost-stop rules and explicit separate owner approval before deployment or Worker/D1 calls.

## Follow-up offline risk assessment (2026-10-11)
- **Boundary wakeup:** A naive `setTimeout(run, 120000)` set at 17:59 would miss an 18:00 weekday peak start. Future scheduling should clamp the pending wait to the **next Taiwan weekday/time boundary** (and override expiry), then recompute. A boundary wakeup is not an extra overlapping GET: enforce one active request and one timer only.
- **429 / transient 5xx / timeout:** Error must never advance a Cursor or discard the existing snapshot. The policy fixture models bounded exponential retry delays and honoring `Retry-After` when larger than the normal interval. Parsing and maximum acceptable `Retry-After` remain an implementation review decision; intentionally do not call a live endpoint.
- **Background tab:** Avoid new GET while hidden and revalidate once on foreground. A resumed tab must not start two concurrent fetches or replay an outdated AID. A closed page is not centrally controllable; an admin override shared across viewers would require a separately designed authenticated configuration service.
- **Traffic scenarios:** 10 / 50 / 100 constantly active viewers make weekday GET counts 20,400 / 102,000 / 204,000 daily, weekend 27,000 / 135,000 / 270,000 daily. Two actively polled AIDs double requests. Worker request count and D1 read rows/charges are separate quantities. These are worst-case steady-state GET schedule estimates without browser throttling, HTTP cache, page visibility savings, retries or catch-up pagination.
- **Unverified:** browser timer throttling, actual live 4174 hidden-tab and reading-speed semantics, shared cache behavior, production Worker quotas/metrics, realtime traffic shape, exact site deployment SHA. None can be marked PASS on a synthetic policy test.
- **Integration gate:** first add a fake-clock simulation against the actual Reader polling lifecycle, including article switch during an outstanding GET and an abort/timeout after a schedule boundary; then independently review that change. Do not wire `proposalInterval` into the production Reader or change `RELAY_POLL_MS` based solely on this document.
