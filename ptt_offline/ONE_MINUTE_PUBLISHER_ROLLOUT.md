# #48 PTT snapshot cadence and rollout contract

## Operator-editable schedule contract (Asia/Taipei)

**Current owner-requested rule, 2026-10-16**: regular period **07:00–01:59** every **60 seconds**; overnight period **02:00–06:59** every **600 seconds**. At 02:00 switch to aligned 02:00/02:10/…/06:50 slots; at 07:00 return to every minute. Times follow `Asia/Taipei` (not container/system UTC). This is the **snapshot/publish inspection interval**, not a limit of 25 messages per minute or a request to stop the upstream Collector. Empty snapshots send zero HTTP POST. Subsequent changes must update this document, #48 issue and boundary tests together. The local CLI accepts an explicit `--interval-seconds 60|120` override for temporary controlled trials; omitting the flag uses this daypart policy. It does not authorize production changes, secret toggling or new D1 writes.


Status: IMPLEMENTED OFFLINE, **NOT ACTIVATED**, 24-hour cloud cost/latency ACCEPTANCE PENDING.

The previous five-row single-POST canary is NOT the production Publisher. The
latest #48 source includes a bounded recurring entry `ptt_offline.recurring_publisher`.
It performs one local checkpoint inspection every 60 seconds (120 optional).
No new/changed rows means no signed POST; no full-table upload. AID-specific
ACK and uncertain-outcome stop files live in the given persistent state directory.

## Source-only dry-run (does not contact Cloudflare)

```bash
python3 -B -m ptt_offline.recurring_publisher \
  --source /path/to/hololive_ptt.sqlite3 \
  --state-dir /persistent/ptt-publisher-state \
  --metrics /persistent/ptt-publisher-state/minute-metrics.jsonl \
  --iterations 1
```

A 24-hour local dry-run can specify `--iterations 1440`; this is NOT a
substitute for actual 24h owner-approved live traffic and Cloudflare analytics.

## Bounded live proposal — owner/#45 must approve first

The Worker is OFF by default. Configure independent managed
`PTT_PUBLISH_HMAC_SECRET` and `PTT_TIME_AUTHORITY_SECRET`; review a stable
`PTT_PUBLISH_ENABLED` gate and separate emergency OFF operation.
Do not toggle the gate via per-minute `wrangler secret put` or by redeploying
for each snapshot. The proposed steady-state caps below MUST match between
Worker and local CLI and undergo reviewed staging/load verification:

- `PTT_PUBLISH_MAX_ROWS=25` (previous default 5)
- `PTT_PUBLISH_MAX_BYTES=131072` (128 KiB)
- `PTT_PUBLISH_MAX_QUERIES=150`, `PTT_PUBLISH_MAX_WRITES=80`
- Wall-clock Taipei daypart cadence: 60s except 02:00–06:59 every 600s; max one active Publisher process
- **zero automatic retries** on unknown remote commit, durable STOP latch
- normal day/night AID separation, source-year ambiguous rows remain pending

```bash
# PROPOSED ONLY. Do not run without approved cloud target/caps/gates:
python3 -B -m ptt_offline.recurring_publisher \
  --source /path/to/hololive_ptt.sqlite3 \
  --state-dir /persistent/ptt-publisher-state \
  --metrics /persistent/ptt-publisher-state/minute-metrics.jsonl \
  --iterations 1440 --batch-cap 25 \
  --send --approve-live-capture-policy
```

Live mode ALSO requires `PTT_ALLOW_CAPTURE_TIME_POLICY=true` and both
separate secrets already available to the process. Existing HMAC endpoint is
`https://holoviewer-public-api.singlebagel.workers.dev/private/ptt/publish`.
Never commit secret values. An uncertain ACK requires read-only D1 reconciliation
before manual restart. Keep #47 Today publishing independently disabled.

## Required measured acceptance — not yet achieved

Capture actual Cloudflare requests by route (GET/POST/health), D1 rows
read/written, SQL calls, database bytes, 429/5xx, latency, no-op publishes,
local snapshot counts and D1-to-Public freshness, hourly peaks and
24-hour totals. Local JSONL cannot provide billable Cloudflare analytics by itself.
Confirm both day/night switches, seven-day history paging, source gaps, and
Public Reader rendering real pushes. First owner activation requires distinct
approval; previous authorization for five one-shot rows does NOT authorize
this 24-hour recurring service. No R2 is required for first week but capacity
must be tracked before any bulk history backfill.
