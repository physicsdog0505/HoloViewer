# Proposal: adaptive Public PTT GET polling (OFFLINE ONLY)

Status: DESIGN + synthetic contract tests; not activated. Owner parameters 2026-10-10: peak interval **10 seconds**, off-peak **120 seconds**, **6 hours/day peak**, estimate **10 simultaneous viewers**. The **six-hour clock window has not been specified**; no production schedule or 4174 UI change is authorized.

## Frozen boundaries
- Change only the **network GET schedule**, never the owner-accepted Reader reveal/auto-reading speeds (5/3/1 seconds or current 4174 behavior), layout, selection, scroll, or timeline state.
- Continue the established Worker v1 protocol: initial `tail=1` without `after_cursor`; then cursor GET with previous `next_cursor`; stable-ID dedupe and retention PARTIAL remain unchanged.
- No client-side API tokens, no local Collector/8501/4174 admin endpoints, no Cloudflare schema/Publisher changes.
- Timezone must explicitly be `Asia/Taipei`; peak **6-hour window boundaries are pending owner selection**. Daylight-saving transitions should be treated deterministically if timezone policy changes.
- Background tabs should pause GET and revalidate on foreground return (not guess completeness). Failed GET, 429 and 5xx must preserve cursor/data, never tight-loop; adopt bounded retry/backoff only after separate review.
- An idle/no-new-data response must not be reported as a missing history snapshot. On change of AID, cancel pending scheduled work; no request from old AID can update the active UI.

## Request-volume arithmetic (no cache/no background suppression)
At 10 viewers each continuously monitoring one AID all day:
- Peak: 6 h × 3600 / 10 = **2,160 GET/viewer/day**
- Off-peak: 18 h × 3600 / 120 = **540 GET/viewer/day**
- Total: **2,700 GET/viewer/day**; ×10 = **27,000 GET/day**
- Baseline fixed 5-second interval: 17,280 GET/viewer/day; ×10 = **172,800/day**
- Theoretical reduction: **84.375%** before pagination, reconnect, extra routes, inactive-tab pauses or caching.
These are Worker request estimates **not** D1 rows read, billable cost or actual usage limits.

## Next authorized implementation proposal (NOT executed)
1. First obtain owner-approved clock bounds for the 6 peak hours. Prefer a named static policy file, not hardcoded implicit local browser timezone.
2. Extract a pure `nextPollInterval(nowTaipei, visibility, errorState)` policy with injectable clock, then apply only to `pollRelay` scheduling with a single timer. Existing 4174 visible controls do not change.
3. Offline test peak start/end, midnight-crossing six-hour windows, UTC vs Taiwan locale, background→foreground, 429/5xx backoff, no overlap, article-switch cancellation, cursor/tail continuity and duplicate-safe data.
4. Estimate traffic under 1/10/100 clients, hidden tabs and multi-page catches; define monitoring and stop budget before a bounded live canary.
5. Independent review then separately request approval for integration/deployment. No new Worker/D1/Pages activation by this proposal.

## Offline fixture
`test_relay_poll_policy_proposal.mjs` validates the calculation and proposed pure policy against a **sample** 18:00–00:00 Taipei window. This sample is NOT a user-approved actual peak schedule and does not change running Reader behavior.
